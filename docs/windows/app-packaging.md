# Windows App Packaging

This repo now supports a non-developer Windows distribution path for `Vocal-Scriber`.

The recommended packaging stack is:

- `PyInstaller` in `onedir` mode for the app bundle
- `Inno Setup` for the installer
- a tray-based Windows launcher with no terminal window

## What the packaged app does

The packaged Windows build:

- launches from a normal Windows shortcut
- shows a microphone picker on first launch when needed
- shows a small startup window on every launch so the user can see startup progress
- downloads the Whisper model on first launch if needed
- requires an `OK` acknowledgement before `F9` becomes active
- installs per-user under `%LOCALAPPDATA%\Programs\Vocal-Scriber`
- stores config, logs, and model cache in the user profile
- sits in the system tray so `F9` works while it runs in the background

## Build Steps

1. Set up the repo for Windows development:

```powershell
. .\scripts\setup-windows.ps1
```

2. Build the packaged app:

```powershell
.\scripts\build-windows-app.ps1
```

For faster debug iteration, build only the app bundle and skip the installer step:

```powershell
.\scripts\build-windows-app.ps1 -BundleOnly
```

If you are rebuilding after a previous run left files locked:

```powershell
taskkill /IM "Vocal-Scriber.exe" /F 2>$null
taskkill /IM "python.exe" /F 2>$null
taskkill /IM "pythonw.exe" /F 2>$null
Start-Sleep -Seconds 2
Remove-Item -Recurse -Force .\dist\Vocal-Scriber -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\dist\installer -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\build\vocal_scriber_app -ErrorAction SilentlyContinue
.\scripts\build-windows-app.ps1
```

The build script will use `iscc` from `PATH` when available, and it also checks the standard Inno Setup 6 install folders automatically.

## Build Outputs

The build script generates:

- `dist\Vocal-Scriber\`
  - the packaged app bundle from `PyInstaller`
- `dist\installer\`
  - the Windows installer when the Inno Setup compiler (`iscc`) is available

## Packaging Assets

Relevant files:

- `packaging/windows/app_launcher.py`
- `packaging/windows/generate_assets.py`
- `packaging/windows/vocal_scriber_app.spec`
- `packaging/windows/VocalScriber.iss`

The icon and version files are generated under `build\windows-app\assets\`.

## Runtime Paths

The packaged Windows app stores user data under:

- `%APPDATA%\VocalScriber\settings.json`
- `%LOCALAPPDATA%\VocalScriber\logs\`
- `%LOCALAPPDATA%\VocalScriber\models\`

## Notes

- End users do not need Python or the CUDA Toolkit installed.
- GPU use still depends on PyTorch being able to use the installed NVIDIA driver.
- If GPU is unavailable, the packaged app falls back to CPU automatically.
