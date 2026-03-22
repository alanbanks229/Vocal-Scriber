# Windows CUDA 13 Setup for Vocal-Scriber

Vocal-Scriber's Windows runtime uses `openai-whisper` on top of PyTorch. The supported GPU path is the CUDA 13 PyTorch runtime installed by the Windows setup script.

## Recommended Install Path

Use the repo setup script from PowerShell:

```powershell
. .\scripts\setup-windows.ps1
```

That script:

1. creates or reuses `.venv`
2. activates it
3. installs a CUDA 13-ready PyTorch wheel
4. installs the editable package with the Windows extra

## Verify PyTorch Sees Your GPU

From the activated venv:

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.version.cuda)"
```

Expected result:

- `True`
- a CUDA version string compatible with your installed PyTorch build

## Run Vocal-Scriber

```powershell
python -m vocal_scriber --debug
```

Behavior:

- if CUDA is available, the Windows runtime tries GPU first
- if CUDA init fails, it falls back to CPU automatically
- transcription still works when GPU is unavailable

## If GPU Is Still Not Available

Check these in order:

1. `nvidia-smi` works in a new terminal.
2. Your NVIDIA driver is current enough for your installed CUDA stack.
3. You restarted the shell after installing CUDA or driver updates.
4. The venv was rebuilt or the setup script was rerun after major CUDA/PyTorch changes.
5. PyTorch still reports GPU visibility with:

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.device_count())"
```

If PyTorch cannot see the GPU, Vocal-Scriber intentionally continues on CPU rather than failing during startup.

## Important Note

Do not try to "fix" the Windows runtime by dropping random CUDA DLLs into the repo. The supported path here is the PyTorch CUDA 13 runtime installed through the Windows setup script.
