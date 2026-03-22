#!/usr/bin/env python3
"""Shared helpers for the platform-specific Vocal-Scriber runtimes."""

from __future__ import annotations

import argparse
import contextlib
import io
import math
import os
import re
import subprocess
import sys
import threading
import time

import numpy as np
import pyperclip
import requests
import sounddevice as sd
from scipy.io import wavfile
from scipy.signal import resample_poly

SAMPLE_RATE = 16000
LANGUAGE = "en"
DEFAULT_MODEL = "small"

WINDOWS_DEVICE_MENU_PRIORITY = {
    "MME": 0,
    "Windows DirectSound": 1,
    "Windows WASAPI": 2,
    "Windows WDM-KS": 3,
}

WINDOWS_HIDDEN_DEVICE_NAMES = {
    "Microsoft Sound Mapper - Input",
    "Primary Sound Capture Driver",
}

WINDOWS_HIDDEN_DEVICE_PREFIXES = (
    "Input (",
)

WINDOWS_GENERIC_GROUP_PREFIXES = {
    "microphone",
    "headset",
    "input",
    "output",
    "line",
    "speaker",
}

GUI_AVAILABLE = False
GUIController = None
try:
    import tkinter as _tk  # noqa: F401
    from .ui.controller import GUIController

    GUI_AVAILABLE = True
except ImportError:
    pass

HALLUCINATIONS = [
    "thanks for watching",
    "thank you for watching",
    "thanks for listening",
    "thank you for listening",
    "subscribe",
    "like and subscribe",
    "see you next time",
    "bye",
    "goodbye",
    "the end",
    "silence",
    "no speech",
    "inaudible",
    "[music]",
    "(music)",
    "you",
    "i",
    "so",
    "uh",
    "um",
    "hmm",
    "huh",
    "ah",
    "oh",
]


@contextlib.contextmanager
def suppress_stdout():
    """Temporarily redirect stdout to devnull."""
    old_stdout = sys.stdout
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout


def parse_args() -> argparse.Namespace:
    """Parse shared CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Push-to-talk voice typing for your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m vocal_scriber
  python -m vocal_scriber --api http://localhost:8002/transcribe
  python -m vocal_scriber --model base
  python -m vocal_scriber --debug --device
  python -m vocal_scriber --vocab "Kubernetes,Docker,React"
        """,
    )
    parser.add_argument(
        "--api",
        "-a",
        help="Whisper API URL (if not set, uses a local Whisper backend)",
    )
    parser.add_argument(
        "--api-model",
        default=None,
        help="Model name for OpenAI-compatible APIs (default: whisper-1)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Whisper model size (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    parser.add_argument(
        "--vocab",
        default=None,
        help="Additional vocabulary/technical terms to help Whisper recognize",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.005,
        help="Audio energy threshold for speech detection (default: 0.005)",
    )
    parser.add_argument(
        "--device",
        action="store_true",
        help="Show interactive microphone device selector",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="Enable floating window visualization",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Disable all visualization (audio-only mode)",
    )
    parser.add_argument(
        "--gui-position",
        default="bottom-center",
        choices=["bottom-center", "top-center", "bottom-left", "bottom-right"],
        help="GUI window position (default: bottom-center)",
    )
    parser.add_argument(
        "--gui-offset-x",
        type=int,
        default=0,
        help="Horizontal offset from gui-position in pixels (default: 0)",
    )
    parser.add_argument(
        "--gui-offset-y",
        type=int,
        default=-50,
        help="Vertical offset from gui-position in pixels (default: -50)",
    )
    parser.add_argument(
        "--gui-monitor",
        default="active",
        help="Monitor for GUI: 'active', 'primary', or index (default: active)",
    )
    parser.add_argument(
        "--gui-width",
        type=int,
        default=400,
        help="GUI window width in pixels (default: 400)",
    )
    parser.add_argument(
        "--gui-height",
        type=int,
        default=100,
        help="GUI window height in pixels (default: 100)",
    )
    parser.add_argument(
        "--gui-opacity",
        type=float,
        default=0.85,
        help="GUI window transparency 0.0-1.0 (default: 0.85)",
    )
    parser.add_argument(
        "--gui-theme",
        default="dark",
        choices=["dark", "light"],
        help="GUI color theme (default: dark)",
    )

    args = parser.parse_args()
    if args.no_gui:
        args.gui = False
    return args


def ensure_microphone_available() -> None:
    """Fail fast when no audio input device is configured."""
    try:
        devices = sd.query_devices()
    except Exception as exc:
        print(f"Audio device error: {exc}")
        raise SystemExit(1) from exc

    if not any(device["max_input_channels"] > 0 for device in devices):
        print("No microphone detected.")
        raise SystemExit(1)


def _collect_input_devices() -> list[dict]:
    """Return all PortAudio input devices with host API metadata."""
    devices = sd.query_devices()
    input_devices: list[dict] = []
    for index, device in enumerate(devices):
        if device["max_input_channels"] <= 0:
            continue
        hostapi_name = sd.query_hostapis(device["hostapi"])["name"]
        input_devices.append(
            {
                "index": index,
                "name": device["name"],
                "channels": device["max_input_channels"],
                "sample_rate": device["default_samplerate"],
                "hostapi": hostapi_name,
                "is_default": index == sd.default.device[0],
            }
        )
    return input_devices


def _normalize_windows_display_name(name: str) -> str | None:
    """Normalize noisy PortAudio device names into a friendlier Windows display name."""
    display_name = " ".join(name.split())
    display_name = re.sub(r" Wave\)$", ")", display_name)

    if display_name in WINDOWS_HIDDEN_DEVICE_NAMES:
        return None
    if any(display_name.startswith(prefix) for prefix in WINDOWS_HIDDEN_DEVICE_PREFIXES):
        return None
    if "@System32\\" in display_name:
        return None

    return display_name


def _windows_group_prefix(display_name: str) -> str | None:
    """Return a stable prefix we can use to collapse backend aliases for the same mic."""
    prefix = display_name.split("(", 1)[0].strip().lower()
    if not prefix or prefix in WINDOWS_GENERIC_GROUP_PREFIXES or len(prefix) < 8:
        return None
    return prefix


def _windows_input_device_sort_key(device: dict) -> tuple[int, int]:
    """Prefer the friendliest Windows backend when collapsing duplicate mic entries."""
    return (
        WINDOWS_DEVICE_MENU_PRIORITY.get(device["hostapi"], 99),
        device["index"],
    )


def _collapse_windows_input_devices(input_devices: list[dict]) -> list[dict]:
    """Collapse raw Windows host API duplicates into one logical mic entry."""
    groups: dict[str, list[dict]] = {}
    ordered_keys: list[str] = []
    prefix_to_group_key: dict[str, str] = {}

    for device in input_devices:
        display_name = _normalize_windows_display_name(device["name"])
        if not display_name:
            continue

        candidate = dict(device)
        candidate["display_name"] = display_name
        exact_key = display_name.lower()
        prefix_key = _windows_group_prefix(display_name)

        if exact_key in groups:
            group_key = exact_key
        elif prefix_key and prefix_key in prefix_to_group_key:
            group_key = prefix_to_group_key[prefix_key]
        else:
            group_key = exact_key
            groups[group_key] = []
            ordered_keys.append(group_key)
            if prefix_key:
                prefix_to_group_key[prefix_key] = group_key

        groups[group_key].append(candidate)

    collapsed_devices: list[dict] = []
    for group_key in ordered_keys:
        candidates = sorted(groups[group_key], key=_windows_input_device_sort_key)
        representative = candidates[0].copy()
        representative["name"] = representative.pop("display_name")
        representative["is_default"] = any(candidate["is_default"] for candidate in candidates)
        representative["hostapis"] = list(dict.fromkeys(candidate["hostapi"] for candidate in candidates))
        collapsed_devices.append(representative)

    return collapsed_devices


def list_input_devices() -> list[dict]:
    """Return the user-facing input device list for the current platform."""
    input_devices = _collect_input_devices()
    if sys.platform == "win32":
        collapsed_devices = _collapse_windows_input_devices(input_devices)
        return collapsed_devices or input_devices
    return input_devices


def select_audio_device() -> int:
    """Interactive microphone selection."""
    input_devices = list_input_devices()

    if not input_devices:
        print("No input devices found.")
        raise SystemExit(1)

    print("\nAvailable Microphones:")
    print("=" * 60)

    for menu_index, device in enumerate(input_devices, start=1):
        default_marker = " * current system default" if device["is_default"] else ""
        print(f"\n{menu_index}. {device['name']}{default_marker}")
        if sys.platform == "win32":
            print(
                f"   Preferred backend: {device['hostapi']} | Channels: {device['channels']} | "
                f"Sample Rate: {device['sample_rate']:.0f} Hz"
            )
        else:
            print(
                f"   Host API: {device['hostapi']} | Channels: {device['channels']} | "
                f"Sample Rate: {device['sample_rate']:.0f} Hz"
            )

    print(f"\n{'=' * 60}")
    if sys.platform == "win32":
        print("Windows backend duplicates are grouped into one entry per microphone.")

    while True:
        try:
            default_device = next((device for device in input_devices if device["is_default"]), None)
            choice = input(
                f"\nSelect microphone (1-{len(input_devices)}) or press Enter for default: "
            ).strip()
            if choice == "":
                if default_device is None:
                    default_device = input_devices[0]
                    print(f"Using first available: {default_device['name']}\n")
                else:
                    print(f"Using default: {default_device['name']}\n")
                return default_device["index"]

            selected_index = int(choice)
            if 1 <= selected_index <= len(input_devices):
                selected_device = input_devices[selected_index - 1]["index"]
                print(f"Selected: {input_devices[selected_index - 1]['name']}\n")
                return selected_device

            print(f"Please enter a number between 1 and {len(input_devices)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            raise SystemExit(0) from None


def get_input_device_details(selected_device: int | None) -> tuple[int, dict]:
    """Return the active input device index and device info."""
    device_index = selected_device if selected_device is not None else sd.default.device[0]
    if device_index is None or device_index < 0:
        raise RuntimeError("No default input device is configured.")
    return device_index, sd.query_devices(device_index)


def get_supported_input_sample_rate(
    device_index: int,
    device_info: dict,
    debug: bool = False,
) -> int:
    """Choose a working input sample rate for the selected device."""
    try:
        sd.check_input_settings(
            device=device_index,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
        return SAMPLE_RATE
    except Exception:
        fallback_rate = int(round(device_info["default_samplerate"]))
        if fallback_rate <= 0:
            raise

        sd.check_input_settings(
            device=device_index,
            samplerate=fallback_rate,
            channels=1,
            dtype="float32",
        )

        if debug:
            print(
                f"[DEBUG] {SAMPLE_RATE} Hz unsupported on {device_info['name']}; "
                f"falling back to {fallback_rate} Hz"
            )

        return fallback_rate


def set_terminal_title(title: str) -> None:
    """Set terminal title."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def show_status(status: str, detail: str = "") -> None:
    """Print a status line without fancy Unicode."""
    sys.stdout.write("\n")
    if detail:
        print(f"{status} {detail}")
    else:
        print(status)
    sys.stdout.flush()


def play_beep(freq: float, duration: float, volume: float = 0.12) -> None:
    """Play a short sine-wave beep without blocking."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    wave = (volume * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    try:
        sd.play(wave, SAMPLE_RATE)
    except Exception:
        pass


def resample_audio(
    audio: np.ndarray,
    original_rate: int,
    target_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Resample captured audio to Whisper's expected sample rate."""
    original_rate = int(round(original_rate))
    target_rate = int(round(target_rate))

    if len(audio) == 0 or original_rate == target_rate:
        return audio.astype(np.float32, copy=False)

    common_divisor = math.gcd(original_rate, target_rate)
    resampled = resample_poly(
        audio,
        target_rate // common_divisor,
        original_rate // common_divisor,
    )
    return resampled.astype(np.float32, copy=False)


def make_wav_buffer(audio: np.ndarray) -> io.BytesIO:
    """Create an in-memory WAV buffer for API transcription."""
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_buffer = io.BytesIO()
    wavfile.write(wav_buffer, SAMPLE_RATE, audio_int16)
    wav_buffer.seek(0)
    return wav_buffer


def has_speech(audio: np.ndarray, threshold: float, debug: bool = False) -> bool:
    """Check if audio contains enough energy to be speech."""
    energy = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    has_speech_result = energy > threshold
    if debug:
        print(
            f"[DEBUG] Audio energy: {energy:.6f}, "
            f"threshold: {threshold:.6f}, has_speech: {has_speech_result}"
        )
    return has_speech_result


def is_openai_api(url: str) -> bool:
    """Check if the configured API looks OpenAI-compatible."""
    openai_patterns = [
        "/v1/audio/transcriptions",
        "/v1/audio/",
        "openai",
        "groq",
        "deepgram",
    ]
    lowered = url.lower()
    return any(pattern in lowered for pattern in openai_patterns)


def transcribe_api(api_url: str, wav_buffer: io.BytesIO, api_model: str | None) -> str:
    """Transcribe using an HTTP API."""
    wav_buffer.seek(0)

    files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
    if is_openai_api(api_url):
        data = {
            "model": api_model or "whisper-1",
            "language": LANGUAGE,
            "response_format": "json",
        }
    else:
        data = {"language": LANGUAGE}

    response = requests.post(api_url, files=files, data=data, timeout=60)
    response.raise_for_status()

    try:
        result = response.json()
        return result.get("text", "").strip()
    except Exception:
        return response.text.strip()


def build_initial_prompt(vocab: str | None) -> str:
    """Construct a light domain hint for Whisper."""
    prompt = "Claude, Claude Code, Anthropic, OpenAI, Docker, Kubernetes, PowerShell"
    if vocab:
        prompt = f"{prompt}, {vocab}"
    return prompt


def post_process_transcription(text: str) -> str:
    """Fix a few high-frequency misrecognitions."""
    replacements = [
        (r"\bCloud Code\b", "Claude Code"),
        (r"\bCloud Sonnett?\b", "Claude Sonnet"),
        (r"\bCloud Opus\b", "Claude Opus"),
        (r"\bCloud Haiku\b", "Claude Haiku"),
        (r"\bCloud AI\b", "Claude AI"),
        (r"\bAnthropica?\b", "Anthropic"),
    ]

    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def is_hallucination(text: str) -> bool:
    """Check if the transcription is likely just silence/noise hallucination."""
    lowered = text.lower().strip()
    if len(lowered) < 3:
        return True

    if len(lowered) < 30:
        for hallucination in HALLUCINATIONS:
            if hallucination in lowered and len(lowered) <= len(hallucination) + 5:
                return True
    return False


def paste_text(text: str, system: str, debug: bool = False) -> None:
    """Paste text into the currently focused application."""
    if debug:
        print(f"[DEBUG] Pasting text: '{text[:50]}...'")

    try:
        old_clipboard = pyperclip.paste()
    except Exception:
        old_clipboard = None

    pyperclip.copy(text)
    time.sleep(0.1)

    if debug:
        clipboard_check = pyperclip.paste()
        print(f"[DEBUG] Clipboard verified: {clipboard_check[:50]}...")

    time.sleep(0.1)

    if system == "Windows":
        import pyautogui

        pyautogui.hotkey("ctrl", "v")
    elif system == "Darwin":
        paste_script = """
        tell application "System Events"
            keystroke "v" using command down
        end tell
        """
        result = subprocess.run(
            ["osascript", "-e", paste_script],
            capture_output=True,
            text=True,
            check=False,
        )
        if debug and result.returncode != 0:
            print(f"[DEBUG] Paste error: {result.stderr}")
    else:
        subprocess.run(
            ["xdotool", "key", "ctrl+shift+v"],
            stderr=subprocess.DEVNULL,
            check=False,
        )

    if old_clipboard is None:
        return

    def restore_clipboard() -> None:
        time.sleep(0.5)
        try:
            pyperclip.copy(old_clipboard)
        except Exception:
            pass

    threading.Thread(target=restore_clipboard, daemon=True).start()
