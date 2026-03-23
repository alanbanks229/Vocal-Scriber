#!/usr/bin/env python3
"""Windows runtime for Vocal-Scriber."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

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
    _windows_devices_share_identity,
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


@dataclass
class RuntimeCallbacks:
    """Optional callbacks for non-console Windows app integrations."""

    on_status: Callable[[str, str], None] | None = None
    on_debug: Callable[[str], None] | None = None
    on_error: Callable[[str], None] | None = None


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
listener: keyboard.Listener | None = None
runtime_callbacks = RuntimeCallbacks()
console_output_enabled = True
runtime_started = False
runtime_prepared = False


@contextmanager
def whisper_progress_context(whisper_module=None):
    """Disable tqdm-based Whisper progress output when no console is available."""
    if console_output_enabled:
        yield
        return

    import tqdm as tqdm_module

    original_global_tqdm = tqdm_module.tqdm
    original_whisper_tqdm = getattr(whisper_module, "tqdm", None) if whisper_module else None

    with open(os.devnull, "w", encoding="utf-8") as null_stream:
        def silent_tqdm(*args, **kwargs):
            kwargs.setdefault("disable", True)
            kwargs.setdefault("file", null_stream)
            return original_global_tqdm(*args, **kwargs)

        tqdm_module.tqdm = silent_tqdm
        if whisper_module is not None and original_whisper_tqdm is not None:
            whisper_module.tqdm = silent_tqdm
        try:
            yield
        finally:
            tqdm_module.tqdm = original_global_tqdm
            if whisper_module is not None and original_whisper_tqdm is not None:
                whisper_module.tqdm = original_whisper_tqdm


def _print(message: str) -> None:
    if console_output_enabled:
        print(message)


def _emit_debug(message: str) -> None:
    debug_enabled = bool(config and getattr(config, "debug", False))
    if debug_enabled and console_output_enabled:
        print(message)
    if debug_enabled and runtime_callbacks.on_debug:
        runtime_callbacks.on_debug(message)


def _emit_status(status: str, detail: str = "") -> None:
    if console_output_enabled:
        show_status(status, detail)
    if runtime_callbacks.on_status:
        runtime_callbacks.on_status(status, detail)


def _emit_error(detail: str) -> None:
    if runtime_callbacks.on_error:
        runtime_callbacks.on_error(detail)


def switch_audio_device(device_index: int) -> None:
    """Switch to a different audio input device during runtime."""
    global selected_device, stream

    if stream:
        _emit_debug("[DEBUG] Stopping stream to switch device")
        stream.stop()
        stream.close()
        stream = None

    selected_device = device_index
    if config and getattr(config, "debug", False):
        device_info = sd.query_devices(device_index)
        _emit_debug(f"[DEBUG] Switched to device {device_index}: {device_info['name']}")


def iter_input_device_fallbacks(device_index: int, device_info: dict):
    """Yield fallback devices for the same hardware ordered by host API stability."""
    yield device_index, device_info

    matches = []

    for index, candidate in enumerate(sd.query_devices()):
        if index == device_index or candidate["max_input_channels"] <= 0:
            continue

        candidate_hostapi = sd.query_hostapis(candidate["hostapi"])["name"]
        candidate_entry = (
            WINDOWS_HOSTAPI_PRIORITY.get(candidate_hostapi, 99),
            index,
            candidate,
        )

        if _windows_devices_share_identity(device_info, candidate):
            matches.append(candidate_entry)

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
            debug=bool(config and getattr(config, "debug", False)),
        )
        hostapi_name = sd.query_hostapis(device_info["hostapi"])["name"]
        default_suffix = " (system default)" if selected_device is None and device_index == selected_index else ""
        _emit_debug(
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

            if attempt_index > 1:
                _emit_debug(f"[DEBUG] Fallback input backend succeeded on device {device_index}")

            return input_stream, stream_sample_rate
        except Exception as exc:
            last_error = exc
            _emit_debug(f"[DEBUG] Failed to start input stream on device {device_index} via {hostapi_name}: {exc}")

    if last_error is not None:
        raise last_error
    raise RuntimeError("No working input device found.")


def check_dependencies() -> None:
    """Verify runtime prerequisites."""
    ensure_microphone_available()
    if config.gui and not GUI_AVAILABLE:
        _print("Warning: tkinter not available, GUI disabled")
        config.gui = False


def load_whisper_model() -> None:
    """Load the Windows local backend or an API backend."""
    global whisper_model, whisper_device

    if config.api:
        try:
            health_url = config.api.rsplit("/", 1)[0] + "/health"
            response = requests.get(health_url, timeout=2)
            info = response.json()
            _print(f"Using Whisper API: model={info.get('default_model', 'unknown')}")
        except Exception:
            _print(f"Using Whisper API: {config.api}")
        return

    try:
        import torch
        import whisper
    except ImportError:
        _print("Windows local transcription requires torch and openai-whisper.")
        _print("Run the Windows setup script to install the CUDA 13-ready backend.")
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
                verbose=None,
                condition_on_previous_text=False,
            )

    download_root = getattr(config, "model_download_root", None)
    _print(f"Loading Whisper model '{config.model}'... (first run downloads ~150MB)")

    runtime_candidates = []
    try:
        if torch.cuda.is_available():
            runtime_candidates.append("cuda")
    except Exception as exc:
        _emit_debug(f"[DEBUG] Could not query CUDA devices: {exc}")

    runtime_candidates.append("cpu")
    last_error = None

    for device_name in runtime_candidates:
        try:
            if device_name == "cuda":
                _print("Trying GPU acceleration for Whisper...")

            with whisper_progress_context(whisper):
                candidate_model = whisper.load_model(
                    config.model,
                    device=device_name,
                    download_root=download_root,
                )

            if device_name == "cuda":
                warm_up_model(candidate_model, device_name)

            whisper_model = candidate_model
            whisper_device = device_name
            runtime_label = "GPU" if device_name == "cuda" else "CPU"
            _print(f"Model loaded on {runtime_label}.")
            return
        except Exception as exc:
            last_error = exc
            _emit_debug(f"[DEBUG] Whisper init failed on {device_name}: {exc}")
            if device_name == "cuda" and console_output_enabled:
                _print("GPU unavailable for Whisper; falling back to CPU.")

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
    _emit_status("[RECORDING]", "Press hotkey to stop")


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
    _emit_status("[TRANSCRIBING]", "Processing speech...")

    if not audio_chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(audio_chunks).flatten()


def transcribe(audio: np.ndarray) -> str:
    """Transcribe recorded audio to text."""
    global whisper_model, whisper_device

    if recording_sample_rate != SAMPLE_RATE:
        _emit_debug(f"[DEBUG] Resampling audio from {recording_sample_rate} Hz to {SAMPLE_RATE} Hz")
        audio = resample_audio(audio, recording_sample_rate, SAMPLE_RATE)

    if len(audio) < SAMPLE_RATE * 0.5:
        return ""

    if not has_speech(audio, config.threshold, debug=bool(getattr(config, "debug", False))):
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
            verbose=None,
            condition_on_previous_text=False,
        )

    try:
        with suppress_stdout(), whisper_progress_context():
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

        _emit_debug(f"[DEBUG] Whisper GPU runtime failed during transcription: {exc}")
        _print("Whisper GPU runtime unavailable; retrying on CPU.")

        import torch
        import whisper

        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

        with whisper_progress_context(whisper):
            whisper_model = whisper.load_model(
                config.model,
                device="cpu",
                download_root=getattr(config, "model_download_root", None),
            )
        whisper_device = "cpu"

        with suppress_stdout(), whisper_progress_context():
            result = do_transcribe()

    text = result.get("text", "").strip()
    return post_process_transcription(text)


def transcribe_and_paste(audio: np.ndarray) -> None:
    """Background thread: transcribe and paste."""
    global state

    try:
        _emit_debug("[DEBUG] Starting transcription worker")
        _emit_status("[TRANSCRIBING]", "Running Whisper inference...")
        text = transcribe(audio)
        _emit_debug(f"[DEBUG] Transcription result: '{text}'")
        _emit_debug(f"[DEBUG] Is hallucination: {is_hallucination(text) if text else 'N/A (empty)'}")

        if text and not is_hallucination(text):
            _emit_debug("[DEBUG] Transcription complete; pasting text")
            _emit_status("[PASTING]", "Sending text to the active app...")
            paste_text(text, SYSTEM, debug=bool(getattr(config, "debug", False)))
            beep_success()
            set_terminal_title("Vocal-Scriber - Done")
            _emit_status("[DONE]", text[:60])
        else:
            beep_error()
            set_terminal_title("Vocal-Scriber - Ready")
            _emit_status("[NO SPEECH]", "Nothing detected")
    except Exception as exc:
        beep_error()
        set_terminal_title("Vocal-Scriber - Error")
        _emit_status("[ERROR]", str(exc)[:60])
        _emit_error(str(exc))
    finally:
        with state_lock:
            state = State.IDLE
        time.sleep(1.5)
        set_terminal_title("Vocal-Scriber - Ready")
        _emit_status("[READY]", "Press F9 to record")


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
            if console_output_enabled and getattr(config, "debug", False):
                traceback.print_exc()
            beep_error()
            set_terminal_title("Vocal-Scriber - Error")
            _emit_status("[ERROR]", str(exc)[:60])
            _emit_error(str(exc))

    return on_press


def prepare_runtime(
    runtime_config,
    device_index: int | None,
    callbacks: RuntimeCallbacks | None = None,
    console_output: bool = True,
):
    """Prepare the Windows runtime without arming the hotkey listener."""
    global config, gui_controller, selected_device
    global runtime_callbacks, console_output_enabled, runtime_prepared

    config = runtime_config
    selected_device = device_index
    runtime_callbacks = callbacks or RuntimeCallbacks()
    console_output_enabled = console_output

    if runtime_prepared:
        return bool(gui_controller)

    check_dependencies()

    if selected_device is None:
        if console_output_enabled:
            selected_device = select_audio_device()
        else:
            raise RuntimeError("No microphone selected for Windows app mode.")

    _emit_status("[STARTING]", "Loading Whisper model...")
    load_whisper_model()

    visualization_available = False
    if config.gui and GUI_AVAILABLE:
        try:
            gui_controller = GUIController(config)
            gui_controller.create_window()
            visualization_available = True
            _emit_debug("[DEBUG] Floating window GUI initialized")
        except Exception as exc:
            _emit_debug(f"[DEBUG] GUI window initialization failed: {exc}")
            config.gui = False
            gui_controller = None

    runtime_prepared = True
    return visualization_available


def start_hotkey_listener() -> None:
    """Arm the Windows hotkey listener after runtime preparation completes."""
    global listener, runtime_started

    if runtime_started:
        return
    if not runtime_prepared:
        raise RuntimeError("Runtime must be prepared before starting the hotkey listener.")

    hotkey = keyboard.Key.f9
    set_terminal_title("Vocal-Scriber - Ready")

    listener = keyboard.Listener(on_press=create_hotkey_handler(hotkey))
    listener.start()
    runtime_started = True

    _emit_status("[READY]", "Press F9 to record")


def initialize_runtime(
    runtime_config,
    device_index: int | None,
    callbacks: RuntimeCallbacks | None = None,
    console_output: bool = True,
):
    """Initialize the Windows runtime without entering a blocking loop."""
    if runtime_started:
        return bool(gui_controller)

    visualization_available = prepare_runtime(
        runtime_config=runtime_config,
        device_index=device_index,
        callbacks=callbacks,
        console_output=console_output,
    )
    start_hotkey_listener()

    return visualization_available


def shutdown_runtime() -> None:
    """Stop the Windows runtime and release listeners/resources."""
    global stream, listener, gui_controller, runtime_started, runtime_prepared, state

    if stream:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        stream = None

    if listener:
        try:
            listener.stop()
        except Exception:
            pass
        listener = None

    if gui_controller:
        try:
            gui_controller.quit()
        except Exception:
            pass
        gui_controller = None

    with state_lock:
        state = State.IDLE
    runtime_started = False
    runtime_prepared = False


def is_runtime_active() -> bool:
    """Return whether the background runtime is currently active."""
    return bool(runtime_started and listener and listener.is_alive())


def main() -> None:
    """Run the Windows runtime."""
    global config

    config = parse_args()

    _print("Vocal-Scriber - Voice Typing for Your Terminal")
    _print("=" * 45)
    _print(f"System: {SYSTEM}")
    _print(f"Default local backend: PyTorch Whisper ({DEFAULT_MODEL})")

    visualization_available = initialize_runtime(
        runtime_config=config,
        device_index=None,
        callbacks=RuntimeCallbacks(),
        console_output=True,
    )

    _print("\nReady! Press F9 to record.")
    if visualization_available:
        _print("Floating window visualization enabled")
    _print("Press Ctrl+C to exit.\n")

    shutdown_requested = False

    def signal_handler(sig, frame):
        nonlocal shutdown_requested
        shutdown_requested = True
        _print("\nShutting down...")
        shutdown_runtime()

    try:
        signal.signal(signal.SIGINT, signal_handler)

        if visualization_available and gui_controller:
            gui_controller.run_mainloop()
        else:
            while listener and listener.is_alive() and not shutdown_requested:
                listener.join(0.5)
    except KeyboardInterrupt:
        _print("\nBye!")
    finally:
        shutdown_runtime()


if __name__ == "__main__":
    main()
