# `pyproject.toml` in Plain English

This repo now uses [`pyproject.toml`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/pyproject.toml) as the main source of truth for the Python package setup.

## What `pyproject.toml` is

Think of `pyproject.toml` as the file that tells Python tooling:

- what this project is called
- which Python version it needs
- which dependencies it needs
- which extra dependencies belong to macOS vs Windows
- how the project should be installed and built

Before this change, that information was spread across top-level `requirements*.txt` files for the main app. Now the main app is package-based, so that metadata lives in one place.

## What this repo uses it for

In this repo, `pyproject.toml` defines:

- project name: `vocal-scriber`
- Python requirement: `>=3.11`
- shared dependencies:
  `numpy`, `scipy`, `sounddevice`, `pynput`, `pyperclip`, `requests`, `screeninfo`
- optional platform extras:
  - `macos`: `faster-whisper`, `pyobjc-framework-Cocoa`
  - `windows`: `openai-whisper`, `pyautogui`, `pystray`, `pillow`
  - `windows-build`: `pyinstaller`
- package layout:
  code lives under [`src/vocal_scriber/`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/src/vocal_scriber)

## Why the old `requirements.txt` files went away

The main app no longer installs from:

```text
requirements-common.txt
requirements-macos.txt
requirements-windows.txt
```

Instead, it installs from the package metadata in `pyproject.toml`.

The one exception is diarization:

- [`tools/diarization/requirements.txt`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/tools/diarization/requirements.txt) still exists
- that is intentional because diarization is a separate macOS-only tool, not part of the main package

## What `python -m pip install -e ".[windows]"` means

This is the new Windows install shape:

```powershell
python -m pip install -e ".[windows]"
```

Broken down:

- `python -m pip`
  Run `pip` through the currently selected Python interpreter.
  This is safer than calling bare `pip` because it guarantees which Python environment is being used.

- `install`
  Install the project into the current virtual environment.

- `-e`
  "Editable install."
  This means the environment points at the repo source directly instead of copying files into site-packages.
  If we edit files in `src/`, the installed app sees those changes immediately.

- `.`
  Install the current folder as a package.

- `.[windows]`
  Also install the optional dependency group named `windows`.

The macOS equivalent is:

```bash
python -m pip install -e ".[macos]"
```

## Why `python -m vocal_scriber` is the new run command

This repo is now a package, so we run the package instead of a root script.

```powershell
python -m vocal_scriber --debug
```

Broken down:

- `python -m`
  Ask Python to run a module or package

- `vocal_scriber`
  The package name to run

Python then looks for:

- [`src/vocal_scriber/__main__.py`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/src/vocal_scriber/__main__.py)

and executes that file as the package entrypoint.

So this:

```powershell
python -m vocal_scriber --debug
```

is the package-based replacement for the old script-style command:

```powershell
python .\vocal-scriber.py --debug
```

## How the setup scripts use `pyproject.toml`

The setup scripts still do the environment creation and activation:

- [`scripts/setup-windows.ps1`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/scripts/setup-windows.ps1)
- [`scripts/setup-macos.sh`](/C:/Users/Alan/Local_Documents/Github/Vocal-Scriber/scripts/setup-macos.sh)

After activation, they now install the package from `pyproject.toml`:

- Windows:
  `python -m pip install --no-build-isolation -e ".[windows]"`
- macOS:
  `python -m pip install --no-build-isolation -e ".[macos]"`

On Windows, the setup script also installs the CUDA 13 PyTorch wheel first.

## What "build" means here

Most day-to-day usage does not require making a distributable package.

For normal development, we only need:

```powershell
python -m pip install -e ".[windows]"
python -m vocal_scriber --debug
```

That is enough to:

- install dependencies
- make the package importable
- run the app from the package entrypoint

When people say "build" in a packaging sense, they usually mean generating wheel or source distribution artifacts for publishing or distribution. That is separate from normal local use.

## Why this setup is better

Using `pyproject.toml` gives us:

- one main place for package metadata
- cleaner platform-specific extras
- a more standard Python project layout
- easier editable installs for development
- a clearer PR/release story than a flat root with multiple app requirements files

## Practical command summary

### Windows

```powershell
. .\scripts\setup-windows.ps1
python -m vocal_scriber --debug
```

### macOS

```bash
source scripts/setup-macos.sh
python -m vocal_scriber --debug
```

### Diarization

```bash
python -m pip install -r tools/diarization/requirements.txt
python tools/diarization/diarize.py audio.wav
```
