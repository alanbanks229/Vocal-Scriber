#!/usr/bin/env python3
"""
Vocal-Scriber - Push-to-talk voice typing for your terminal.

Press F9, speak, press F9 again - your words appear wherever you're typing.
Works on Linux, Windows, and macOS with local Whisper transcription.
Always uses English language and F9 hotkey.

Usage:
    python vocal-scriber.py [--api URL] [--model MODEL]

Examples:
    python vocal-scriber.py                          # Use local faster-whisper (small model)
    python vocal-scriber.py --api http://localhost:8002/transcribe  # Use API
    python vocal-scriber.py --model base             # Use base model instead of small
    python vocal-scriber.py --debug --device         # Debug mode with device selector
"""

import argparse
import contextlib
import io
import os
import platform
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

import numpy as np
import pyperclip
import requests
import sounddevice as sd
from pynput import keyboard
from scipy.io import wavfile

# GUI imports (fail gracefully if not available)
GUI_AVAILABLE = False
GUIController = None
try:
    import tkinter as tk
    from gui.gui_controller import GUIController
    GUI_AVAILABLE = True
except ImportError:
    pass

# === Configuration ===
SAMPLE_RATE = 16000
LANGUAGE = "en"
DEFAULT_MODEL = "small"
SYSTEM = platform.system()  # "Linux", "Windows", "Darwin" (macOS)


# === Utility Functions ===
@contextlib.contextmanager
def suppress_stdout():
    """Temporarily redirect stdout to devnull."""
    old_stdout = sys.stdout
    with open(os.devnull, 'w') as devnull:
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout


# === State ===
class State:
    IDLE = 0
    RECORDING = 1
    TRANSCRIBING = 2


state = State.IDLE
state_lock = threading.Lock()
audio_chunks: list[np.ndarray] = []
stream: sd.InputStream | None = None
whisper_model = None
config = None
selected_device = None  # Will store the selected audio input device index
gui_controller = None  # GUIController instance for waveform visualization


# === Argument Parsing ===
def parse_args():
    parser = argparse.ArgumentParser(
        description="Push-to-talk voice typing for your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vocal-scriber.py                     # Use local faster-whisper (small model)
  python vocal-scriber.py --api http://localhost:8002/transcribe
  python vocal-scriber.py --model base        # Use 'base' model instead
  python vocal-scriber.py --debug --device    # Debug mode with device selector
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
        "--debug",
        action="store_true",
        help="Enable debug output"
    )
    parser.add_argument(
        "--vocab",
        default=None,
        help="Additional vocabulary/technical terms to help Whisper recognize (comma-separated)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.005,
        help="Audio energy threshold for speech detection (lower=more sensitive, default: 0.005)"
    )
    parser.add_argument(
        "--device",
        action="store_true",
        help="Show interactive microphone device selector"
    )

    # Visualization options
    parser.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="Enable floating window visualization (default: menu bar on macOS)"
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Disable all visualization (audio-only mode)"
    )
    parser.add_argument(
        "--gui-position",
        default="bottom-center",
        choices=["bottom-center", "top-center", "bottom-left", "bottom-right"],
        help="GUI window position (default: bottom-center)"
    )
    parser.add_argument(
        "--gui-offset-x",
        type=int,
        default=0,
        help="Horizontal offset from gui-position in pixels (default: 0)"
    )
    parser.add_argument(
        "--gui-offset-y",
        type=int,
        default=-50,
        help="Vertical offset from gui-position in pixels (default: -50)"
    )
    parser.add_argument(
        "--gui-monitor",
        default="active",
        help="Monitor for GUI: 'active', 'primary', or index (0, 1, 2, etc.) (default: active)"
    )
    parser.add_argument(
        "--gui-width",
        type=int,
        default=400,
        help="GUI window width in pixels (default: 400)"
    )
    parser.add_argument(
        "--gui-height",
        type=int,
        default=100,
        help="GUI window height in pixels (default: 100)"
    )
    parser.add_argument(
        "--gui-opacity",
        type=float,
        default=0.85,
        help="GUI window transparency 0.0-1.0 (default: 0.85)"
    )
    parser.add_argument(
        "--gui-theme",
        default="dark",
        choices=["dark", "light"],
        help="GUI color theme (default: dark)"
    )

    args = parser.parse_args()

    # Handle --no-gui flag
    if args.no_gui:
        args.gui = False

    return args


# === Device Selection ===
def select_audio_device():
    """Interactive microphone selection."""
    global selected_device

    devices = sd.query_devices()
    input_devices = []

    # Collect all input devices
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            input_devices.append({
                'index': i,
                'name': device['name'],
                'channels': device['max_input_channels'],
                'sample_rate': device['default_samplerate'],
                'hostapi': sd.query_hostapis(device['hostapi'])['name'],
                'is_default': i == sd.default.device[0]
            })

    if not input_devices:
        print("No input devices found!")
        sys.exit(1)

    print("\nAvailable Microphones:")
    print("=" * 60)

    for idx, dev in enumerate(input_devices, 1):
        default_marker = " ⭐ (current system default)" if dev['is_default'] else ""
        print(f"\n{idx}. {dev['name']}{default_marker}")
        print(f"   Channels: {dev['channels']}, Sample Rate: {dev['sample_rate']:.0f} Hz")

    print("\n" + "=" * 60)

    # Prompt user for selection
    while True:
        try:
            choice = input(f"\nSelect microphone (1-{len(input_devices)}) or press Enter for default: ").strip()

            if choice == "":
                # Use system default
                selected_device = None
                default_dev = next(d for d in input_devices if d['is_default'])
                print(f"Using default: {default_dev['name']}\n")
                return

            choice_num = int(choice)
            if 1 <= choice_num <= len(input_devices):
                selected_device = input_devices[choice_num - 1]['index']
                print(f"Selected: {input_devices[choice_num - 1]['name']}\n")
                return
            else:
                print(f"Please enter a number between 1 and {len(input_devices)}")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)


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

    # Check GUI dependencies if enabled
    if config.gui and not GUI_AVAILABLE:
        print("Warning: tkinter not available, GUI disabled")
        config.gui = False


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
    """Show status message."""
    sys.stdout.write('\n')
    if detail:
        print(f"{status} {detail}")
    else:
        print(status)
    sys.stdout.flush()


# === Recording ===
def audio_callback(indata, frames, time_info, status):
    """Accumulate audio chunks and send levels to GUI."""
    audio_chunks.append(indata.copy())

    # Calculate RMS level for visualization (GUI window or menu bar) (fail silently)
    try:
        if gui_controller and gui_controller.is_recording():
            rms = float(np.sqrt(np.mean(indata ** 2)))
            gui_controller.audio_level_queue.put_nowait(rms)
    except:
        pass  # Never let visualization break audio capture


def start_recording():
    """Start recording from microphone."""
    global stream, audio_chunks
    audio_chunks = []

    # Use selected device if specified, otherwise use system default
    stream_params = {
        'samplerate': SAMPLE_RATE,
        'channels': 1,
        'dtype': 'float32',
        'callback': audio_callback
    }
    if selected_device is not None:
        stream_params['device'] = selected_device
        if config.debug:
            device_info = sd.query_devices(selected_device)
            print(f"[DEBUG] Recording from: {device_info['name']}")
    elif config.debug:
        device_info = sd.query_devices(sd.default.device[0])
        print(f"[DEBUG] Recording from: {device_info['name']} (system default)")

    stream = sd.InputStream(**stream_params)
    stream.start()
    beep_start()

    # Show visualization (GUI window or menu bar)
    if gui_controller:
        try:
            gui_controller.show()
        except:
            pass  # Don't break recording if visualization fails

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

    # Hide visualization (GUI window or menu bar)
    if gui_controller:
        try:
            gui_controller.hide()
        except:
            pass  # Don't break recording if visualization fails

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

    # Check if text is ONLY hallucination words/phrases
    if len(t) < 30:
        for hall in HALLUCINATIONS:
            # Check if the hallucination phrase is the entire content (with small variation)
            if hall in t and len(t) <= len(hall) + 5:
                return True

    return False


def has_speech(audio: np.ndarray, threshold: float = None) -> bool:
    """Check if audio contains actual speech (energy-based)."""
    if threshold is None:
        threshold = config.threshold if config else 0.005
    energy = np.sqrt(np.mean(audio ** 2))
    has_speech_result = energy > threshold

    if config and config.debug:
        print(f"[DEBUG] Audio energy: {energy:.6f}, threshold: {threshold:.6f}, has_speech: {has_speech_result}")

    return has_speech_result


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
            "language": LANGUAGE,
            "response_format": "json"
        }
    else:
        # Custom API format (e.g., local faster-whisper server)
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {"language": LANGUAGE}

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

        # Suppress faster-whisper stdout to prevent output interference
        with suppress_stdout():
            segments, _ = whisper_model.transcribe(
                audio_for_whisper,
                language=LANGUAGE,
                initial_prompt=initial_prompt
            )
        text = " ".join(seg.text.strip() for seg in segments).strip()

    # Apply post-processing to fix common misrecognitions
    return post_process_transcription(text)


# === Paste ===
def paste_text(text: str):
    """Paste text into the frontmost window."""
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

    # Small delay to let transcription UI clear
    time.sleep(0.1)

    # Send paste command to frontmost app
    if SYSTEM == "Linux":
        # Try both terminal and non-terminal paste shortcuts
        subprocess.run(["xdotool", "key", "ctrl+shift+v"], stderr=subprocess.DEVNULL)
    elif SYSTEM == "Windows":
        import pyautogui
        pyautogui.hotkey('ctrl', 'v')
    elif SYSTEM == "Darwin":
        if config.debug:
            print(f"[DEBUG] Sending paste to frontmost app")
        paste_script = '''
        tell application "System Events"
            keystroke "v" using command down
        end tell
        '''
        result = subprocess.run(["osascript", "-e", paste_script],
                               capture_output=True, text=True)
        if config.debug and result.returncode != 0:
            print(f"[DEBUG] Paste error: {result.stderr}")

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

        if config.debug:
            print(f"[DEBUG] Transcription result: '{text}'")
            print(f"[DEBUG] Is hallucination: {is_hallucination(text) if text else 'N/A (empty)'}")

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

    # Show device selector if requested
    if config.device:
        select_audio_device()

    load_whisper_model()

    # Initialize visualization (GUI window or menu bar icon)
    global gui_controller
    visualization_available = False

    if config.gui and GUI_AVAILABLE:
        # GUI mode: Create floating window
        try:
            gui_controller = GUIController(config)
            gui_controller.create_window()
            visualization_available = True
            if config.debug:
                print("[DEBUG] Floating window GUI initialized")
        except Exception as e:
            if config.debug:
                print(f"[DEBUG] GUI window initialization failed: {e}")
            config.gui = False
            gui_controller = None
    elif not config.gui and sys.platform == 'darwin':
        # Menu bar mode (macOS default): Create menu bar icon
        try:
            # Check if PyObjC is available before attempting menu bar creation
            try:
                from Cocoa import NSStatusBar
            except ImportError:
                print("\n⚠️  WARNING: Menu bar icon unavailable")
                print("PyObjC is not installed. Install with:")
                print("  pip install pyobjc-framework-Cocoa")
                print("\nApp will continue without menu bar visualization.\n")
                gui_controller = None
            else:
                # PyObjC available, proceed with menu bar creation
                gui_controller = GUIController(config)

                # Set quit callback before creating window
                # This will be called from the menu bar quit action
                def quit_from_menu():
                    """Handle quit request from menu bar."""
                    if config.debug:
                        print("\n[DEBUG] Quit requested from menu bar")
                    # Signal the GUI controller to stop
                    if gui_controller:
                        gui_controller.stop()
                    # Exit the program
                    sys.exit(0)

                gui_controller.quit_callback = quit_from_menu
                gui_controller.create_window()  # Creates menu bar icon (not window)
                visualization_available = True
                if config.debug:
                    print("[DEBUG] Menu bar visualization initialized (default mode)")
        except Exception as e:
            # Other errors during menu bar creation (not import errors)
            if config.debug:
                print(f"[DEBUG] Menu bar initialization failed: {e}")
            else:
                print(f"\n⚠️  WARNING: Could not create menu bar icon: {e}\n")
            gui_controller = None

    hotkey = keyboard.Key.f9
    set_terminal_title("Vocal-Scriber - Ready")

    print(f"\nReady! Press F9 to record.")
    if visualization_available:
        if config.gui:
            print("Floating window visualization enabled")
        else:
            print("Menu bar visualization enabled (use --gui for floating window)")
    print("Press Ctrl+C to exit.\n")

    handler = create_hotkey_handler(hotkey)

    # Store original terminal settings to suppress keyboard echo
    old_settings = None
    if sys.stdin.isatty():
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            # Disable echo and canonical mode to prevent escape sequences from appearing
            new_settings = termios.tcgetattr(sys.stdin)
            new_settings[3] = new_settings[3] & ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, new_settings)
        except Exception as e:
            if config.debug:
                print(f"[DEBUG] Could not configure terminal: {e}")
            old_settings = None

    # Threading model based on visualization mode:
    # - No visualization: keyboard listener on main thread
    # - GUI window mode: keyboard in background, tkinter mainloop on main thread
    # - Menu bar mode (macOS): keyboard in background, Cocoa event loop on main thread
    listener = None
    keyboard_thread = None

    try:
        if not visualization_available:
            # No visualization: run keyboard listener on main thread
            with keyboard.Listener(on_press=handler) as listener:
                listener.join()
        elif config.gui:
            # GUI window mode: keyboard in background, tkinter on main thread
            def start_keyboard_listener():
                """Run keyboard listener in background thread."""
                nonlocal listener
                with keyboard.Listener(on_press=handler) as listener:
                    listener.join()

            keyboard_thread = threading.Thread(target=start_keyboard_listener, daemon=True)
            keyboard_thread.start()

            # Set up Ctrl+C handler for clean shutdown
            def signal_handler(sig, frame):
                print("\nShutting down...")
                if listener:
                    listener.stop()
                if gui_controller:
                    gui_controller.quit()

            signal.signal(signal.SIGINT, signal_handler)

            # Run GUI mainloop on main thread (blocks until quit)
            gui_controller.run_mainloop()
        else:
            # Menu bar mode (macOS): keyboard in background, Cocoa event loop on main thread
            def start_keyboard_listener():
                """Run keyboard listener in background thread."""
                nonlocal listener
                with keyboard.Listener(on_press=handler) as listener:
                    listener.join()

            keyboard_thread = threading.Thread(target=start_keyboard_listener, daemon=True)
            keyboard_thread.start()

            # Set up Ctrl+C handler for clean shutdown
            running = True

            def signal_handler(sig, frame):
                nonlocal running
                print("\nShutting down...")
                running = False
                if listener:
                    listener.stop()
                if gui_controller:
                    gui_controller.stop()

            signal.signal(signal.SIGINT, signal_handler)

            # Run Cocoa event loop on main thread for NSTimer to work
            # This keeps the menu bar icon updating and processes Cocoa events
            if config.debug:
                print("[DEBUG] Running Cocoa event loop for menu bar updates")

            from Foundation import NSRunLoop, NSDefaultRunLoopMode, NSDate
            runloop = NSRunLoop.currentRunLoop()

            # Run event loop until interrupted
            while running and keyboard_thread.is_alive():
                # Process events for 0.1 seconds, then check if we should continue
                runloop.runMode_beforeDate_(
                    NSDefaultRunLoopMode,
                    NSDate.dateWithTimeIntervalSinceNow_(0.1)
                )

    except KeyboardInterrupt:
        print("\nBye!")
    finally:
        # Always restore terminal settings
        if old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except:
                pass


if __name__ == "__main__":
    main()
