#!/usr/bin/env python3
"""Package entrypoint for Vocal-Scriber."""

from __future__ import annotations

import platform
def main() -> None:
    """Dispatch to the supported platform runtime."""
    system = platform.system()

    if system == "Darwin":
        from .platforms.macos import main as runtime_main
    elif system == "Windows":
        from .platforms.windows import main as runtime_main
    else:
        print("Vocal-Scriber currently supports macOS and Windows.")
        print(f"Detected unsupported platform: {system}")
        raise SystemExit(1)

    runtime_main()


if __name__ == "__main__":
    main()
