#!/usr/bin/env python3
"""Windows runtime for Vocal-Scriber."""

from __future__ import annotations

import signal
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

SYSTEM = "Windows"

WINDOWS_HOSTAPI_PRIORITY = {
    "Windows DirectSound": 0,
    "MME": 1,
    "Windows WASAPI": 2,
    "Windows WDM-KS": 3,
}


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


def iter_input_device_fallbacks(device_index: int, device_info: dict):
    """Yield fallback devices for the same hardware ordered by host API stability."""
    yield device_index, device_info

    normalized_name = device_info["name"].lower()
    normalized_prefix = normalized_name.split("(")[0].strip()
    exact_matches = []
    prefix_matches = []

    for index, candidate in enumerate(sd.query_devices()):
        if index == device_index or candidate["max_input_channels"] <= 0:
            continue

        candidate_name = candidate["name"].lower()
        candidate_hostapi = sd.query_hostapis(candidate["hostapi"])["name"]
        candidate_entry = (
            WINDOWS_HOSTAPI_PRIORITY.get(candidate_hostapi, 99),
            index,
            candidate,
        )

        if candidate_name == normalized_name:
            exact_matches.append(candidate_entry)
        elif normalized_prefix and len(normalized_prefix) >= 8 and candidate_name.startswith(normalized_prefix):
            prefix_matches.append(candidate_entry)

    matches = exact_matches if exact_matches else prefix_matches
    for _, index, candidate in sorted(matches, key=lambda item: (item[0], item[1])):
        yield index, candidate


def open_input_stream_with_fallback():
    """Open an input stream, retrying equivalent Windows backends when needed."""
    selected_index, selected_info = get_input_device_details(selected_device)
    last_error = None

    for attempt_index, (device_index, device_info) in enumerate(
        iter_input_device_fallbacks(selected_index, selected_info),
        start=1,
    ):
        stream_sample_rate = get_supported_input_sample_rate(
            device_index,
            device_info,
            debug=config.debug,
        )
        hostapi_name = sd.query_hostapis(device_info["hostapi"])["name"]
        if config.debug:
            default_suffix = " (system default)" if selected_device is None and device_index == selected_index else ""
            print(
                f"[DEBUG] Recording from: {device_info['name']} @ {stream_sample_rate} Hz "
                f"via {hostapi_name}{default_suffix}"
            )

        try:
            input_stream = sd.InputStream(
                samplerate=stream_sample_rate,
                channels=1,
                dtype="float32",
                callback=audio_callback,
                device=device_index,
            )
            input_stream.start()

            if config.debug and attempt_index > 1:
                print(f"[DEBUG] Fallback input backend succeeded on device {device_index}")

            return input_stream, stream_sample_rate
        except Exception as exc:
            last_error = exc
            if config.debug:
                print(f"[DEBUG] Failed to start input stream on device {device_index} via {hostapi_name}: {exc}")

    if last_error is not None:
        raise last_error
    raise RuntimeError("No working input device found.")


def check_dependencies() -> None:
    """Verify runtime prerequisites."""
    ensure_microphone_available()
    if config.gui and not GUI_AVAILABLE:
        print("Warning: tkinter not available, GUI disabled")
        config.gui = False


def load_whisper_model() -> None:
    """Load the Windows local backend or an API backend."""
    global whisper_model, whisper_device

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
        import torch
        import whisper
    except ImportError:
        print("Windows local transcription requires torch and openai-whisper.")
        print("Run the Windows setup script to install the CUDA 13-ready backend.")
        raise SystemExit(1) from None

    def warm_up_model(model, device_name: str) -> None:
        test_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        if device_name == "cuda":
            torch.zeros(1, device="cuda")
        with suppress_stdout():
            model.transcribe(
                test_audio,
                language=LANGUAGE,
                fp16=device_name == "cuda",
                verbose=False,
                condition_on_previous_text=False,
            )

    print(f"Loading Whisper model '{config.model}'... (first run downloads ~150MB)")

    runtime_candidates = []
    try:
        if torch.cuda.is_available():
            runtime_candidates.append("cuda")
    except Exception as exc:
        if config.debug:
            print(f"[DEBUG] Could not query CUDA devices: {exc}")

    runtime_candidates.append("cpu")
    last_error = None

    for device_name in runtime_candidates:
        try:
            if device_name == "cuda":
                print("Trying GPU acceleration for Whisper...")

            candidate_model = whisper.load_model(config.model, device=device_name)

            if device_name == "cuda":
                warm_up_model(candidate_model, device_name)

            whisper_model = candidate_model
            whisper_device = device_name
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
    """Accumulate audio chunks and feed the floating GUI if enabled."""
    audio_chunks.append(indata.copy())

    try:
        if gui_controller and gui_controller.is_recording():
            rms = float(np.sqrt(np.mean(indata ** 2)))
            gui_controller.audio_level_queue.put_nowait(rms)
    except Exception:
        pass


def start_recording() -> None:
    """Start recording from the microphone."""
    global audio_chunks, stream, recording_sample_rate

    audio_chunks = []
    stream, recording_sample_rate = open_input_stream_with_fallback()
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
    global whisper_model, whisper_device

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

    def do_transcribe():
        return whisper_model.transcribe(
            audio_for_whisper,
            language=LANGUAGE,
            fp16=whisper_device == "cuda",
            initial_prompt=initial_prompt,
            verbose=False,
            condition_on_previous_text=False,
        )

    try:
        with suppress_stdout():
            result = do_transcribe()
    except Exception as exc:
        error_message = str(exc).lower()
        should_fallback_to_cpu = whisper_device == "cuda" and any(
            token in error_message
            for token in (
                "cublas",
                "cudnn",
                "cuda",
                "cufft",
                "curand",
                "device-side",
                "out of memory",
            )
        )
        if not should_fallback_to_cpu:
            raise

        if config.debug:
            print(f"[DEBUG] Whisper GPU runtime failed during transcription: {exc}")
        print("Whisper GPU runtime unavailable; retrying on CPU.")

        import torch
        import whisper

        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

        whisper_model = whisper.load_model(config.model, device="cpu")
        whisper_device = "cpu"

        with suppress_stdout():
            result = do_transcribe()

    text = result.get("text", "").strip()
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
    """Run the Windows runtime."""
    global config, gui_controller, selected_device

    config = parse_args()

    print("Vocal-Scriber - Voice Typing for Your Terminal")
    print("=" * 45)
    print(f"System: {SYSTEM}")
    print(f"Default local backend: PyTorch Whisper ({DEFAULT_MODEL})")

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

    hotkey = keyboard.Key.f9
    set_terminal_title("Vocal-Scriber - Ready")

    print("\nReady! Press F9 to record.")
    if visualization_available:
        print("Floating window visualization enabled")
    print("Press Ctrl+C to exit.\n")

    handler = create_hotkey_handler(hotkey)
    listener = None
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
                    gui_controller.quit()
                except Exception:
                    pass

        signal.signal(signal.SIGINT, signal_handler)

        if not visualization_available:
            listener = keyboard.Listener(on_press=handler)
            listener.start()
            while listener.is_alive() and not shutdown_requested:
                listener.join(0.5)
        else:
            def start_keyboard_listener():
                nonlocal listener
                with keyboard.Listener(on_press=handler) as listener:
                    listener.join()

            keyboard_thread = threading.Thread(target=start_keyboard_listener, daemon=True)
            keyboard_thread.start()
            gui_controller.run_mainloop()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
