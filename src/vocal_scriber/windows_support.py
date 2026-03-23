"""Windows app support helpers for packaged Vocal-Scriber builds."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .common import DEFAULT_MODEL, list_input_devices, parse_args

APP_NAME = "Vocal-Scriber"
APP_DIR_NAME = "VocalScriber"
LOG_FILE_NAME = "vocal-scriber.log"

DEFAULT_SETTINGS: dict[str, Any] = {
    "model": DEFAULT_MODEL,
    "selected_device_index": None,
    "selected_device_name": None,
    "first_run_complete": False,
    "debug": False,
}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required Windows environment variable is missing: {name}")
    return value


def get_appdata_dir() -> Path:
    return Path(_require_env("APPDATA")) / APP_DIR_NAME


def get_local_appdata_dir() -> Path:
    return Path(_require_env("LOCALAPPDATA")) / APP_DIR_NAME


def get_settings_path() -> Path:
    return get_appdata_dir() / "settings.json"


def get_logs_dir() -> Path:
    return get_local_appdata_dir() / "logs"


def get_log_path() -> Path:
    return get_logs_dir() / LOG_FILE_NAME


def get_model_cache_dir() -> Path:
    return get_local_appdata_dir() / "models"


def ensure_app_directories() -> None:
    get_appdata_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_model_cache_dir().mkdir(parents=True, exist_ok=True)


def load_app_settings() -> dict[str, Any]:
    """Load packaged Windows app settings, resetting safely if corrupted."""
    ensure_app_directories()
    settings_path = get_settings_path()
    if not settings_path.exists():
        return dict(DEFAULT_SETTINGS)

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        corrupt_path = settings_path.with_suffix(".corrupt.json")
        try:
            shutil.move(str(settings_path), str(corrupt_path))
        except Exception:
            pass
        return dict(DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    settings.update(data)
    return settings


def save_app_settings(settings: dict[str, Any]) -> None:
    """Persist packaged Windows app settings."""
    ensure_app_directories()
    settings_path = get_settings_path()
    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings)
    settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_runtime_config(settings: dict[str, Any]):
    """Build a runtime namespace for the packaged Windows tray app."""
    config = parse_args([])
    config.model = settings.get("model") or DEFAULT_MODEL
    config.debug = bool(settings.get("debug", False))
    config.gui = False
    config.no_gui = True
    config.model_download_root = str(get_model_cache_dir())
    return config


def resolve_saved_input_device(settings: dict[str, Any]) -> int | None:
    """Resolve the stored device selection to a currently available device."""
    input_devices = list_input_devices()
    if not input_devices:
        return None

    saved_index = settings.get("selected_device_index")
    saved_name = settings.get("selected_device_name")

    if saved_index is not None:
        for device in input_devices:
            if device["index"] == saved_index:
                return saved_index

    if saved_name:
        for device in input_devices:
            if device["name"] == saved_name:
                return device["index"]

    default_device = next((device for device in input_devices if device["is_default"]), None)
    if default_device:
        return default_device["index"]

    return input_devices[0]["index"]


def get_device_display_name(device_index: int | None) -> str | None:
    """Return the friendly display name for a stored input device."""
    if device_index is None:
        return None

    for device in list_input_devices():
        if device["index"] == device_index:
            return device["name"]
    return None


def configure_file_logger(debug: bool = False) -> logging.Logger:
    """Create a simple file logger for the packaged Windows app."""
    ensure_app_directories()
    logger = logging.getLogger("vocal_scriber.windows_app")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    handler = logging.FileHandler(get_log_path(), encoding="utf-8")
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.info("Starting %s %s", APP_NAME, __version__)
    return logger
