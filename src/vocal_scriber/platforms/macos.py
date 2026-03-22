#!/usr/bin/env python3
"""macOS runtime for Vocal-Scriber."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
import traceback

import numpy as np
import requests
import sounddevice as sd
from pynput import keyboard

from ..common import (
    DEFAULT_MODEL,
    GUI_AVAILABLE,
    GUIController,
    LANGUAGE,
    SAMPLE_RATE,
    build_initial_prompt,
    ensure_microphone_available,
    get_input_device_details,
    get_supported_input_sample_rate,
    has_speech,
    is_hallucination,
    make_wav_buffer,
    parse_args,
    paste_text,
    play_beep,
    post_process_transcription,
    resample_audio,
    select_audio_device,
    set_terminal_title,
    show_status,
    suppress_stdout,
    transcribe_api,
)

SYSTEM = "Darwin"


class State:
    IDLE = 0
    RECORDING = 1
    TRANSCRIBING = 2


state = State.IDLE
state_lock = threading.Lock()
audio_chunks: list[np.ndarray] = []
stream: sd.InputStream | None = None
whisper_model = None
whisper_device = None
whisper_compute_type = None
config = None
selected_device = None
gui_controller = None
recording_sample_rate = SAMPLE_RATE


def switch_audio_device(device_index: int) -> None:
    """Switch to a different audio input device during runtime."""
    global selected_device, stream

    if stream:
        if config.debug:
            print("[DEBUG] Stopping stream to switch device")
        stream.stop()
        stream.close()
        stream = None

    selected_device = device_index
    if config.debug:
        device_info = sd.query_devices(device_index)
        print(f"[DEBUG] Switched to device {device_index}: {device_info['name']}")


def check_dependencies() -> None:
    """Verify runtime prerequisites."""
    ensure_microphone_available()
    if config.gui and not GUI_AVAILABLE:
        print("Warning: tkinter not available, GUI disabled")
        config.gui = False


def load_whisper_model() -> None:
    """Load local Whisper model if API mode is not enabled."""
    global whisper_model, whisper_device, whisper_compute_type

    if config.api:
        try:
            health_url = config.api.rsplit("/", 1)[0] + "/health"
            response = requests.get(health_url, timeout=2)
            info = response.json()
            print(f"Using Whisper API: model={info.get('default_model', 'unknown')}")
        except Exception:
            print(f"Using Whisper API: {config.api}")
        return

    try:
        import ctranslate2
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed for macOS.")
        print("Run scripts/setup-macos.sh or install the package with the [macos] extra.")
        raise SystemExit(1) from None

    def warm_up_model(model: WhisperModel) -> None:
        test_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with suppress_stdout():
            segments, _ = model.transcribe(
                test_audio,
                language=LANGUAGE,
                without_timestamps=True,
            )
            list(segments)

    print(f"Loading Whisper model '{config.model}'... (first run downloads ~150MB)")

    runtime_candidates: list[tuple[str, str]] = []
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            runtime_candidates.append(("cuda", "auto"))
    except Exception as exc:
        if config.debug:
            print(f"[DEBUG] Could not query CUDA devices: {exc}")

    runtime_candidates.append(("cpu", "auto"))
    last_error = None

    for device_name, compute_type in runtime_candidates:
        try:
            if device_name == "cuda":
                print("Trying GPU acceleration for Whisper...")

            candidate_model = WhisperModel(
                config.model,
                device=device_name,
                compute_type=compute_type,
            )

            if device_name == "cuda":
                warm_up_model(candidate_model)

            whisper_model = candidate_model
            whisper_device = device_name
            whisper_compute_type = compute_type
            runtime_label = "GPU" if device_name == "cuda" else "CPU"
            print(f"Model loaded on {runtime_label}.")
            return
        except Exception as exc:
            last_error = exc
            if config.debug:
                print(f"[DEBUG] Whisper init failed on {device_name}: {exc}")
            elif device_name == "cuda":
                print("GPU unavailable for Whisper; falling back to CPU.")

    raise last_error if last_error is not None else RuntimeError("Unable to initialize Whisper model")


def beep_start() -> None:
    play_beep(880, 0.08)


def beep_stop() -> None:
    play_beep(440, 0.12)


def beep_error() -> None:
    play_beep(220, 0.2)


def beep_success() -> None:
    play_beep(660, 0.08)


def audio_callback(indata, frames, time_info, status) -> None:
    """Accumulate audio chunks and feed the visualization."""
    audio_chunks.append(indata.copy())

    try:
        if gui_controller and gui_controller.is_recording():
            rms = float(np.sqrt(np.mean(indata ** 2)))
            gui_controller.audio_level_queue.put_nowait(rms)
    except Exception:
        pass


def open_input_stream():
    """Open the selected input stream."""
    device_index, device_info = get_input_device_details(selected_device)
    stream_sample_rate = get_supported_input_sample_rate(
        device_index,
        device_info,
        debug=config.debug,
    )
    hostapi_name = sd.query_hostapis(device_info["hostapi"])["name"]
    if config.debug:
        print(
            f"[DEBUG] Recording from: {device_info['name']} @ "
            f"{stream_sample_rate} Hz via {hostapi_name}"
        )

    input_stream = sd.InputStream(
        samplerate=stream_sample_rate,
        channels=1,
        dtype="float32",
        callback=audio_callback,
        device=device_index,
    )
    input_stream.start()
    return input_stream, stream_sample_rate


def start_recording() -> None:
    """Start recording from the microphone."""
    global audio_chunks, stream, recording_sample_rate

    audio_chunks = []
    stream, recording_sample_rate = open_input_stream()
    beep_start()

    if gui_controller:
        try:
            gui_controller.show()
        except Exception:
            pass

    set_terminal_title("Vocal-Scriber - Recording")
    show_status("[RECORDING]", "Press hotkey to stop")


def stop_recording() -> np.ndarray:
    """Stop recording and return the captured audio."""
    global stream

    time.sleep(0.3)

    if stream:
        stream.stop()
        stream.close()
        stream = None
    beep_stop()

    if gui_controller:
        try:
            gui_controller.hide()
        except Exception:
            pass

    set_terminal_title("Vocal-Scriber - Transcribing")
    show_status("[TRANSCRIBING]", "Processing speech...")

    if not audio_chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(audio_chunks).flatten()


def transcribe(audio: np.ndarray) -> str:
    """Transcribe recorded audio to text."""
    global whisper_model, whisper_device, whisper_compute_type

    if recording_sample_rate != SAMPLE_RATE:
        if config.debug:
            print(f"[DEBUG] Resampling audio from {recording_sample_rate} Hz to {SAMPLE_RATE} Hz")
        audio = resample_audio(audio, recording_sample_rate, SAMPLE_RATE)

    if len(audio) < SAMPLE_RATE * 0.5:
        return ""

    if not has_speech(audio, config.threshold, debug=config.debug):
        return ""

    if config.api:
        text = transcribe_api(config.api, make_wav_buffer(audio), config.api_model)
        return post_process_transcription(text)

    audio_for_whisper = audio.astype(np.float32)
    initial_prompt = build_initial_prompt(config.vocab)

    try:
        with suppress_stdout():
            segments, _ = whisper_model.transcribe(
                audio_for_whisper,
                language=LANGUAGE,
                initial_prompt=initial_prompt,
            )
    except RuntimeError as exc:
        error_message = str(exc).lower()
        should_fallback_to_cpu = (
            whisper_device == "cuda"
            and any(token in error_message for token in ("cublas", "cudnn", "cuda", "curand", "cufft"))
        )
        if not should_fallback_to_cpu:
            raise

        if config.debug:
            print(f"[DEBUG] Whisper GPU runtime failed during transcription: {exc}")
        print("Whisper GPU runtime unavailable; retrying on CPU.")

        from faster_whisper import WhisperModel

        whisper_model = WhisperModel(config.model, device="cpu", compute_type="auto")
        whisper_device = "cpu"
        whisper_compute_type = "auto"

        with suppress_stdout():
            segments, _ = whisper_model.transcribe(
                audio_for_whisper,
                language=LANGUAGE,
                initial_prompt=initial_prompt,
            )

    text = " ".join(segment.text.strip() for segment in segments).strip()
    return post_process_transcription(text)


def transcribe_and_paste(audio: np.ndarray) -> None:
    """Background thread: transcribe and paste."""
    global state

    try:
        text = transcribe(audio)
        if config.debug:
            print(f"[DEBUG] Transcription result: '{text}'")
            print(f"[DEBUG] Is hallucination: {is_hallucination(text) if text else 'N/A (empty)'}")

        if text and not is_hallucination(text):
            paste_text(text, SYSTEM, debug=config.debug)
            beep_success()
            set_terminal_title("Vocal-Scriber - Done")
            show_status("[DONE]", text[:60])
        else:
            beep_error()
            set_terminal_title("Vocal-Scriber - Ready")
            show_status("[NO SPEECH]", "Nothing detected")
    except Exception as exc:
        beep_error()
        set_terminal_title("Vocal-Scriber - Error")
        show_status("[ERROR]", str(exc)[:60])
    finally:
        with state_lock:
            state = State.IDLE
        time.sleep(1.5)
        set_terminal_title("Vocal-Scriber - Ready")
        show_status("[READY]", "Press F9 to record")


def create_hotkey_handler(hotkey):
    """Create the shared hotkey handler."""

    def on_press(key):
        global state

        if key != hotkey:
            return

        try:
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
                        daemon=True,
                    ).start()
        except Exception as exc:
            with state_lock:
                state = State.IDLE
            if config.debug:
                traceback.print_exc()
            beep_error()
            set_terminal_title("Vocal-Scriber - Error")
            show_status("[ERROR]", str(exc)[:60])

    return on_press


def main() -> None:
    """Run the macOS runtime."""
    global config, gui_controller, selected_device

    config = parse_args()

    print("Vocal-Scriber - Voice Typing for Your Terminal")
    print("=" * 45)
    print(f"System: {SYSTEM}")
    print(f"Default local backend: faster-whisper ({DEFAULT_MODEL})")

    check_dependencies()
    selected_device = select_audio_device()
    load_whisper_model()

    visualization_available = False

    if config.gui and GUI_AVAILABLE:
        try:
            gui_controller = GUIController(config)
            gui_controller.create_window()
            visualization_available = True
            if config.debug:
                print("[DEBUG] Floating window GUI initialized")
        except Exception as exc:
            if config.debug:
                print(f"[DEBUG] GUI window initialization failed: {exc}")
            config.gui = False
            gui_controller = None
    elif not config.gui:
        try:
            try:
                from Cocoa import NSStatusBar  # noqa: F401
            except ImportError:
                print("\nWarning: menu bar icon unavailable.")
                print("PyObjC is not installed. Install the package with the [macos] extra to enable it.\n")
                gui_controller = None
            else:
                gui_controller = GUIController(config)

                def quit_from_menu():
                    if config.debug:
                        print("\n[DEBUG] Quit requested from menu bar")
                    if gui_controller:
                        gui_controller.stop()
                    raise SystemExit(0)

                gui_controller.quit_callback = quit_from_menu
                gui_controller.create_window()

                if gui_controller.menubar_waveform:
                    current_device = selected_device
                    if current_device is None:
                        current_device = sd.default.device[0]
                    gui_controller.menubar_waveform.set_current_device(current_device)
                    gui_controller.menubar_waveform.device_change_callback = switch_audio_device
                    gui_controller.menubar_waveform.quit_callback = quit_from_menu

                visualization_available = True
                if config.debug:
                    print("[DEBUG] Menu bar visualization initialized (default mode)")
        except Exception as exc:
            if config.debug:
                print(f"[DEBUG] Menu bar initialization failed: {exc}")
            else:
                print(f"\nWarning: could not create menu bar icon: {exc}\n")
            gui_controller = None

    hotkey = keyboard.Key.f9
    set_terminal_title("Vocal-Scriber - Ready")

    print("\nReady! Press F9 to record.")
    if visualization_available:
        if config.gui:
            print("Floating window visualization enabled")
        else:
            print("Menu bar visualization enabled (use --gui for floating window)")
    print("Press Ctrl+C to exit.\n")

    handler = create_hotkey_handler(hotkey)

    old_settings = None
    termios_mod = None
    if sys.stdin.isatty():
        try:
            import termios as termios_mod

            old_settings = termios_mod.tcgetattr(sys.stdin)
            new_settings = termios_mod.tcgetattr(sys.stdin)
            new_settings[3] = new_settings[3] & ~(termios_mod.ECHO | termios_mod.ICANON)
            termios_mod.tcsetattr(sys.stdin, termios_mod.TCSADRAIN, new_settings)
        except Exception as exc:
            if config.debug:
                print(f"[DEBUG] Could not configure terminal: {exc}")
            old_settings = None
            termios_mod = None

    listener = None
    keyboard_thread = None
    shutdown_requested = False

    try:
        def signal_handler(sig, frame):
            nonlocal shutdown_requested, listener
            shutdown_requested = True
            print("\nShutting down...")

            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

            if listener:
                try:
                    listener.stop()
                except Exception:
                    pass

            if gui_controller:
                try:
                    if config.gui:
                        gui_controller.quit()
                    elif gui_controller.menubar_waveform and gui_controller.menubar_waveform.quit_callback:
                        gui_controller.menubar_waveform.quit_callback()
                    else:
                        gui_controller.stop()
                except Exception:
                    pass

        signal.signal(signal.SIGINT, signal_handler)

        if not visualization_available:
            listener = keyboard.Listener(on_press=handler)
            listener.start()
            while listener.is_alive() and not shutdown_requested:
                listener.join(0.5)
        elif config.gui:
            def start_keyboard_listener():
                nonlocal listener
                with keyboard.Listener(on_press=handler) as listener:
                    listener.join()

            keyboard_thread = threading.Thread(target=start_keyboard_listener, daemon=True)
            keyboard_thread.start()
            gui_controller.run_mainloop()
        else:
            def start_keyboard_listener():
                nonlocal listener
                with keyboard.Listener(on_press=handler) as listener:
                    listener.join()

            keyboard_thread = threading.Thread(target=start_keyboard_listener, daemon=True)
            keyboard_thread.start()

            if config.debug:
                print("[DEBUG] Running NSApplication event loop for menu bar")

            from Cocoa import NSApplication, NSApplicationActivationPolicyAccessory
            from Foundation import NSTimer

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1,
                gui_controller.menubar_waveform,
                "checkShouldQuit:",
                None,
                True,
            )

            app.run()
    except KeyboardInterrupt:
        print("\nBye!")
    finally:
        if old_settings and termios_mod:
            try:
                termios_mod.tcsetattr(sys.stdin, termios_mod.TCSADRAIN, old_settings)
            except Exception:
                pass


if __name__ == "__main__":
    main()
