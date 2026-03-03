#!/usr/bin/env python3
"""
Vocal-Scriber - Push-to-talk voice typing for your terminal.

Press a hotkey, speak, press again - your words appear wherever you're typing.
Works on Linux, Windows, and macOS with local Whisper transcription.

Usage:
    python vocal-scriber.py [--api URL] [--model MODEL] [--hotkey KEY]

Examples:
    python vocal-scriber.py                          # Use local faster-whisper
    python vocal-scriber.py --api http://localhost:8002/transcribe  # Use API
    python vocal-scriber.py --model small            # Use small model
    python vocal-scriber.py --hotkey f8              # Use F8 instead of F9
"""

import argparse
import io
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyperclip
import requests
import sounddevice as sd
from pynput import keyboard
from scipy.io import wavfile

# === Configuration ===
SAMPLE_RATE = 16000
LANGUAGE = "en"
DEFAULT_MODEL = "base"
SYSTEM = platform.system()  # "Linux", "Windows", "Darwin" (macOS)

# Terminal identifiers per OS
TERMINALS = {
    "Linux": [
        "gnome-terminal", "xterm", "konsole", "alacritty", "kitty",
        "terminator", "tilix", "xfce4-terminal", "urxvt", "st",
        "sakura", "guake", "tilda", "hyper", "wezterm"
    ],
    "Windows": [
        "WindowsTerminal", "cmd.exe", "powershell", "pwsh",
        "ConEmu", "mintty", "Hyper", "Terminus"
    ],
    "Darwin": [
        "Terminal", "iTerm", "iTerm2", "Hyper", "kitty",
        "alacritty", "wezterm"
    ]
}


# === State ===
class State:
    IDLE = 0
    RECORDING = 1
    TRANSCRIBING = 2


state = State.IDLE
state_lock = threading.Lock()
audio_chunks: list[np.ndarray] = []
stream: sd.InputStream | None = None
target_window = None
whisper_model = None
config = None


# === Argument Parsing ===
def parse_args():
    parser = argparse.ArgumentParser(
        description="Push-to-talk voice typing for your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vocal-scriber.py                     # Use local faster-whisper
  python vocal-scriber.py --api http://localhost:8002/transcribe
  python vocal-scriber.py --model small       # Use 'small' model for better accuracy
  python vocal-scriber.py --hotkey f8         # Use F8 instead of F9
  python vocal-scriber.py --vocab "Kubernetes,Docker,React"  # Add custom vocabulary
        """
    )
    parser.add_argument(
        "--api", "-a",
        help="Whisper API URL (if not set, uses local faster-whisper)"
    )
    parser.add_argument(
        "--api-model",
        default=None,
        help="Model name for OpenAI-compatible APIs (default: whisper-1)"
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Whisper model size: tiny, base, small, medium, large-v3 (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--hotkey", "-k",
        default="f9",
        help="Hotkey to use (default: f9). Examples: f8, f10, f12"
    )
    parser.add_argument(
        "--language", "-l",
        default=LANGUAGE,
        help=f"Language code for transcription (default: {LANGUAGE})"
    )
    parser.add_argument(
        "--minimal", "-M",
        action="store_true",
        help="Minimal UI - only show status (great for demos)"
    )
    parser.add_argument(
        "--paste-delay",
        type=float,
        default=0.05,
        help="Delay in seconds before pasting (increase if paste goes to wrong window)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output to troubleshoot window focus issues"
    )
    parser.add_argument(
        "--manual-focus-delay",
        type=float,
        default=0.0,
        help="Seconds to wait after transcription before pasting (gives you time to manually click)"
    )
    parser.add_argument(
        "--refocus",
        action="store_true",
        help="Try to refocus the original window before pasting (disabled by default)"
    )
    parser.add_argument(
        "--vocab",
        default=None,
        help="Additional vocabulary/technical terms to help Whisper recognize (comma-separated)"
    )
    return parser.parse_args()


# === Dependency Checks ===
def check_dependencies():
    """Verify system dependencies based on OS."""
    if SYSTEM == "Linux":
        missing = []
        for cmd in ("xdotool", "xclip"):
            try:
                subprocess.run(["which", cmd], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                missing.append(cmd)
        if missing:
            print(f"Missing Linux dependencies: {', '.join(missing)}")
            print(f"Install with: sudo apt install {' '.join(missing)}")
            sys.exit(1)

    # Check microphone
    try:
        devices = sd.query_devices()
        if not any(d['max_input_channels'] > 0 for d in devices):
            print("No microphone detected!")
            sys.exit(1)
    except Exception as e:
        print(f"Audio device error: {e}")
        sys.exit(1)


def load_whisper_model():
    """Load local Whisper model if not using API."""
    global whisper_model
    if config.api:
        # Test API connection
        try:
            health_url = config.api.rsplit('/', 1)[0] + "/health"
            resp = requests.get(health_url, timeout=2)
            info = resp.json()
            print(f"Using Whisper API: model={info.get('default_model', 'unknown')}")
        except:
            print(f"Using Whisper API: {config.api}")
    else:
        # Use faster-whisper
        try:
            from faster_whisper import WhisperModel
            print(f"Loading Whisper model '{config.model}'... (first run downloads ~150MB)")
            whisper_model = WhisperModel(config.model, device="auto", compute_type="auto")
            print("Model loaded.")
        except ImportError:
            print("faster-whisper not installed!")
            print("Install with: pip install faster-whisper")
            print("Or use --api flag to connect to a Whisper API server")
            sys.exit(1)


# === Audio Feedback ===
def beep(freq: float, duration: float, volume: float = 0.12):
    """Play beep without blocking."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    wave = (volume * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    try:
        sd.play(wave, SAMPLE_RATE)
    except:
        pass  # Ignore audio errors


def beep_start():
    beep(880, 0.08)

def beep_stop():
    beep(440, 0.12)

def beep_error():
    beep(220, 0.2)

def beep_success():
    beep(660, 0.08)


# === Terminal Title (visual status) ===
def set_terminal_title(title: str):
    """Set terminal window title for visual status."""
    # ANSI escape sequence to set terminal title
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def show_status(status: str, detail: str = ""):
    """Show status in minimal mode (clears and centers)."""
    if not config.minimal:
        if detail:
            print(f"{status} {detail}")
        else:
            print(status)
        return

    # Clear screen and show centered status
    sys.stdout.write("\033[2J\033[H")  # Clear screen, move to top
    sys.stdout.write("\n" * 8)  # Padding from top
    sys.stdout.write(f"{'─' * 40}\n")
    sys.stdout.write(f"{status:^40}\n")
    if detail:
        # Truncate detail if too long
        detail = detail[:36] + "..." if len(detail) > 36 else detail
        sys.stdout.write(f"{detail:^40}\n")
    sys.stdout.write(f"{'─' * 40}\n")
    sys.stdout.flush()


# === Window Management (OS-specific) ===
def get_active_window():
    """Get the currently focused window identifier."""
    try:
        if SYSTEM == "Linux":
            return subprocess.check_output(
                ["xdotool", "getactivewindow"],
                stderr=subprocess.DEVNULL
            ).strip()
        elif SYSTEM == "Windows":
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        elif SYSTEM == "Darwin":
            # Get both name and bundle identifier
            script = '''
            tell application "System Events"
                set frontProc to first process whose frontmost is true
                set procName to name of frontProc
                set procBundle to bundle identifier of frontProc
                return procName & "|" & procBundle
            end tell
            '''
            result = subprocess.check_output(["osascript", "-e", script], stderr=subprocess.DEVNULL)
            return result.strip()
    except:
        return None
    return None


def is_vscode(window_id) -> bool:
    """Check if window is VS Code."""
    if not window_id:
        return False
    try:
        if SYSTEM == "Darwin":
            window_str = window_id.decode() if isinstance(window_id, bytes) else str(window_id)
            # Check for VS Code bundle identifier or name
            return ("com.microsoft.vscode" in window_str.lower() or
                    "visual studio code" in window_str.lower() or
                    ("|" in window_str and "electron" in window_str.lower() and
                     "com.microsoft.vscode" in window_str.lower()))
    except:
        pass
    return False


def focus_window(window_id):
    """Focus a specific window."""
    if not window_id:
        return
    try:
        if SYSTEM == "Linux":
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                stderr=subprocess.DEVNULL
            )
        elif SYSTEM == "Windows":
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(window_id)
        elif SYSTEM == "Darwin":
            # macOS: window_id format is "name|bundle_id"
            window_str = window_id.decode() if isinstance(window_id, bytes) else str(window_id)
            app_name = window_str.split("|")[0] if "|" in window_str else window_str

            # Special handling for VS Code - focus terminal pane
            if is_vscode(window_id):
                if config.debug:
                    print(f"[DEBUG] Activating VS Code using open command...")

                # Use bundle identifier to activate the correct app (more reliable)
                window_str = window_id.decode() if isinstance(window_id, bytes) else str(window_id)
                bundle_id = window_str.split("|")[1] if "|" in window_str else "com.microsoft.VSCode"

                # Try using 'open' command which works better with full-screen apps
                result = subprocess.run(
                    ["open", "-b", bundle_id],
                    capture_output=True, text=True
                )
                if config.debug and result.returncode != 0:
                    print(f"[DEBUG] Open command error: {result.stderr}")

                time.sleep(0.5)

                # Then send Ctrl+` to focus terminal
                focus_script = '''
                tell application "System Events"
                    key code 50 using control down
                end tell
                '''
                result = subprocess.run(["osascript", "-e", focus_script],
                                       capture_output=True, text=True)
                time.sleep(0.25)

                if config.debug:
                    if result.returncode != 0:
                        print(f"[DEBUG] Terminal focus error: {result.stderr}")
                    else:
                        print(f"[DEBUG] VS Code terminal focus sent")
            else:
                # Normal activation for other apps
                script = f'tell application "{app_name}" to activate'
                subprocess.run(["osascript", "-e", script], stderr=subprocess.DEVNULL)
    except:
        pass


def is_terminal_window(window_id) -> bool:
    """Check if the window is a terminal."""
    try:
        if SYSTEM == "Linux":
            wm_class = subprocess.check_output(
                ["xprop", "-id", window_id, "WM_CLASS"],
                stderr=subprocess.DEVNULL
            ).decode().lower()
            return any(t in wm_class for t in TERMINALS.get("Linux", []))

        elif SYSTEM == "Windows":
            import ctypes
            buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(window_id, buffer, 256)
            title = buffer.value.lower()
            class_buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(window_id, class_buffer, 256)
            class_name = class_buffer.value
            return any(t.lower() in title or t.lower() in class_name.lower()
                      for t in TERMINALS.get("Windows", []))

        elif SYSTEM == "Darwin":
            # VS Code with terminal counts as terminal
            if is_vscode(window_id):
                return True
            # window_id format is "name|bundle_id"
            window_str = window_id.decode() if isinstance(window_id, bytes) else str(window_id)
            app_name = window_str.split("|")[0] if "|" in window_str else window_str
            return any(t.lower() in app_name.lower() for t in TERMINALS.get("Darwin", []))
    except:
        pass
    return False


# === Recording ===
def audio_callback(indata, frames, time_info, status):
    """Accumulate audio chunks."""
    audio_chunks.append(indata.copy())


def start_recording():
    """Start recording from microphone."""
    global stream, audio_chunks, target_window
    target_window = get_active_window()
    if config.debug and target_window:
        window_str = target_window.decode() if isinstance(target_window, bytes) else str(target_window)
        print(f"[DEBUG] Captured window: {window_str}")
        print(f"[DEBUG] Is VS Code: {is_vscode(target_window)}")
    audio_chunks = []
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        callback=audio_callback
    )
    stream.start()
    beep_start()
    set_terminal_title("🎤 RECORDING...")
    show_status("🎤 RECORDING", "Press hotkey to stop")


def stop_recording() -> np.ndarray:
    """Stop recording, return audio array."""
    global stream
    # Add a small delay to capture the end of speech before stopping
    time.sleep(0.3)

    if stream:
        stream.stop()
        stream.close()
        stream = None
    beep_stop()
    set_terminal_title("⏳ Transcribing...")
    show_status("⏳ TRANSCRIBING", "Processing speech...")

    if not audio_chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(audio_chunks).flatten()


# === Transcription ===
# Common Whisper hallucinations on silence/noise
HALLUCINATIONS = [
    "thanks for watching", "thank you for watching", "thanks for listening",
    "thank you for listening", "subscribe", "like and subscribe",
    "see you next time", "bye", "goodbye", "the end",
    "silence", "no speech", "inaudible", "[music]", "(music)",
    "you", "i", "so", "uh", "um", "hmm", "huh", "ah", "oh",
]


def is_hallucination(text: str) -> bool:
    """Check if text is likely a Whisper hallucination."""
    t = text.lower().strip()
    if len(t) < 3:
        return True
    return any(h in t for h in HALLUCINATIONS) and len(t) < 30


def has_speech(audio: np.ndarray, threshold: float = 0.01) -> bool:
    """Check if audio contains actual speech (energy-based)."""
    energy = np.sqrt(np.mean(audio ** 2))
    return energy > threshold


def is_openai_api(url: str) -> bool:
    """Check if URL looks like an OpenAI-compatible API."""
    openai_patterns = ["/v1/audio/transcriptions", "/v1/audio/", "openai", "groq", "deepgram"]
    return any(p in url.lower() for p in openai_patterns)


def transcribe_api(wav_buffer: io.BytesIO) -> str:
    """Transcribe using API (supports OpenAI-compatible and custom APIs)."""
    wav_buffer.seek(0)

    if is_openai_api(config.api):
        # OpenAI-compatible API format
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {
            "model": config.api_model or "whisper-1",
            "language": config.language,
            "response_format": "json"
        }
    else:
        # Custom API format (e.g., local faster-whisper server)
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {"language": config.language}

    resp = requests.post(config.api, files=files, data=data, timeout=60)
    resp.raise_for_status()

    # Handle both JSON {"text": "..."} and plain text responses
    try:
        result = resp.json()
        return result.get("text", "").strip()
    except:
        return resp.text.strip()


def post_process_transcription(text: str) -> str:
    """Fix common misrecognitions in transcription."""
    import re

    # Pattern-based replacements for Claude-related terms
    # Use word boundaries to avoid false positives
    replacements = [
        (r'\bCloud Code\b', 'Claude Code'),
        (r'\bCloud Sonnett?\b', 'Claude Sonnet'),
        (r'\bCloud Opus\b', 'Claude Opus'),
        (r'\bCloud Haiku\b', 'Claude Haiku'),
        (r'\bCloud AI\b', 'Claude AI'),
        (r'\bAnthropica?\b', 'Anthropic'),
    ]

    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def transcribe(audio: np.ndarray) -> str:
    """Transcribe audio to text."""
    if len(audio) < SAMPLE_RATE * 0.5:  # < 500ms
        return ""

    # Check if audio has enough energy (not just silence)
    if not has_speech(audio):
        return ""

    # Convert to int16 WAV
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_buffer = io.BytesIO()
    wavfile.write(wav_buffer, SAMPLE_RATE, audio_int16)
    wav_buffer.seek(0)

    if config.api:
        text = transcribe_api(wav_buffer)
    else:
        # Use local model with initial_prompt for better recognition of technical terms
        wav_buffer.seek(0)
        audio_for_whisper = audio.astype(np.float32)

        # Provide context to help Whisper recognize technical terms
        initial_prompt = "Claude, Claude Code, Cloud, Anthropic, OpenAI, Docker container"

        # Add custom vocabulary if provided
        if config.vocab:
            initial_prompt += ", " + config.vocab

        segments, _ = whisper_model.transcribe(
            audio_for_whisper,
            language=config.language,
            initial_prompt=initial_prompt
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()

    # Apply post-processing to fix common misrecognitions
    return post_process_transcription(text)


# === Paste ===
def paste_text(text: str):
    """Paste text into the target window."""
    if config.debug:
        print(f"[DEBUG] Pasting text: '{text[:50]}...'")

    # Save old clipboard
    try:
        old_clipboard = pyperclip.paste()
    except:
        old_clipboard = None

    # Set new clipboard
    pyperclip.copy(text)
    time.sleep(0.1)

    # Verify clipboard
    if config.debug:
        clipboard_check = pyperclip.paste()
        print(f"[DEBUG] Clipboard verified: {clipboard_check[:50]}...")

    # Manual focus delay (gives user time to click into terminal)
    if config.manual_focus_delay > 0:
        if config.debug:
            print(f"[DEBUG] Waiting {config.manual_focus_delay}s for manual focus...")
        time.sleep(config.manual_focus_delay)

    # Focus original window (only if --refocus is set)
    if config.refocus:
        if config.debug and target_window:
            window_str = target_window.decode() if isinstance(target_window, bytes) else str(target_window)
            print(f"[DEBUG] Focusing window: {window_str}")
            print(f"[DEBUG] Is VS Code: {is_vscode(target_window)}")

        focus_window(target_window)

        # Extra delay for VS Code on macOS to let terminal focus settle
        delay = config.paste_delay
        if SYSTEM == "Darwin" and is_vscode(target_window):
            delay = max(delay, 0.35)

        if config.debug:
            print(f"[DEBUG] Paste delay: {delay}s")

        time.sleep(delay)
    else:
        if config.debug:
            print(f"[DEBUG] Skipping window focus (default behavior)")
        # Small delay to let transcription UI clear
        time.sleep(0.1)

    # Determine paste shortcut
    is_terminal = is_terminal_window(target_window) if target_window else False

    if config.debug:
        print(f"[DEBUG] Is terminal: {is_terminal}")

    if SYSTEM == "Linux":
        key = "ctrl+shift+v" if is_terminal else "ctrl+v"
        subprocess.run(["xdotool", "key", key], stderr=subprocess.DEVNULL)

    elif SYSTEM == "Windows":
        import pyautogui
        if is_terminal:
            # Windows Terminal and modern terminals use Ctrl+V
            pyautogui.hotkey('ctrl', 'v')
        else:
            pyautogui.hotkey('ctrl', 'v')

    elif SYSTEM == "Darwin":
        # By default, just send keystroke to frontmost app
        if not config.refocus:
            if config.debug:
                print(f"[DEBUG] Sending paste via AppleScript to frontmost process")

            paste_script = '''
            tell application "System Events"
                keystroke "v" using command down
            end tell
            '''
            result = subprocess.run(["osascript", "-e", paste_script],
                                   capture_output=True, text=True)
            if config.debug:
                if result.returncode != 0:
                    print(f"[DEBUG] Paste error: {result.stderr}")
                else:
                    print(f"[DEBUG] Paste command sent to frontmost process")
        # For VS Code, use AppleScript to send paste command for better reliability
        elif is_vscode(target_window):
            window_str = target_window.decode() if isinstance(target_window, bytes) else str(target_window)
            app_name = window_str.split("|")[0] if "|" in window_str else window_str

            if config.debug:
                print(f"[DEBUG] Sending paste via AppleScript to {app_name}")

            paste_script = f'''
            tell application "System Events"
                tell process "{app_name}"
                    keystroke "v" using command down
                end tell
            end tell
            '''
            result = subprocess.run(["osascript", "-e", paste_script],
                                   capture_output=True, text=True)
            if config.debug:
                if result.returncode != 0:
                    print(f"[DEBUG] Paste error: {result.stderr}")
                else:
                    print(f"[DEBUG] Paste command sent via AppleScript")
        else:
            # For other apps, use pyautogui
            import pyautogui
            if config.debug:
                print(f"[DEBUG] Sending paste command: Command+V via pyautogui")
            pyautogui.hotkey('command', 'v')
            if config.debug:
                print(f"[DEBUG] Paste command sent")

    # Restore old clipboard
    if old_clipboard:
        def restore():
            time.sleep(0.5)
            try:
                pyperclip.copy(old_clipboard)
            except:
                pass
        threading.Thread(target=restore, daemon=True).start()


# === Main Logic ===
def transcribe_and_paste(audio: np.ndarray):
    """Background thread: transcribe and paste."""
    global state
    try:
        text = transcribe(audio)
        if text and not is_hallucination(text):
            paste_text(text)
            beep_success()
            set_terminal_title("Vocal-Scriber ✅")
            show_status("✅ DONE", text[:50])
        else:
            beep_error()
            set_terminal_title("Vocal-Scriber")
            show_status("❌ NO SPEECH", "Nothing detected")
    except Exception as e:
        beep_error()
        set_terminal_title("Vocal-Scriber ❌")
        show_status("❌ ERROR", str(e)[:30])
    finally:
        with state_lock:
            state = State.IDLE
        # Reset to ready after a moment
        time.sleep(1.5)
        set_terminal_title("Vocal-Scriber - Ready")
        show_status("● READY", "Press F9 to record")


def get_hotkey(key_name: str):
    """Convert key name string to pynput key."""
    key_name = key_name.lower().strip()
    key_map = {
        "f1": keyboard.Key.f1, "f2": keyboard.Key.f2, "f3": keyboard.Key.f3,
        "f4": keyboard.Key.f4, "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10, "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
    }
    return key_map.get(key_name, keyboard.Key.f9)


def create_hotkey_handler(hotkey):
    """Create the hotkey handler function."""
    def on_press(key):
        global state
        if key != hotkey:
            return

        with state_lock:
            if state == State.IDLE:
                state = State.RECORDING
                start_recording()
            elif state == State.RECORDING:
                state = State.TRANSCRIBING
                audio = stop_recording()
                threading.Thread(
                    target=transcribe_and_paste,
                    args=(audio,),
                    daemon=True
                ).start()
            # TRANSCRIBING: ignore

    return on_press


def main():
    global config
    config = parse_args()

    print("Vocal-Scriber - Voice Typing for Your Terminal")
    print("=" * 45)
    print(f"System: {SYSTEM}")

    check_dependencies()
    load_whisper_model()

    hotkey = get_hotkey(config.hotkey)
    set_terminal_title("Vocal-Scriber - Ready")

    if config.minimal:
        show_status("● READY", f"Press {config.hotkey.upper()} to record")
    else:
        print(f"\nReady! Press {config.hotkey.upper()} to record.")
        print("Press Ctrl+C to exit.\n")

    handler = create_hotkey_handler(hotkey)
    with keyboard.Listener(on_press=handler) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\nBye!")


if __name__ == "__main__":
    main()
