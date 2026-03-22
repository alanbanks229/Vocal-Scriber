# Vocal-Scriber

Push-to-talk voice typing for terminals and coding workflows.

Press `F9`, speak, press `F9` again, and your transcription is pasted into the currently focused app.

## Platform Support

| Platform | Local backend | Default visualization |
| --- | --- | --- |
| macOS | `faster-whisper` | Menu bar waveform |
| Windows | `openai-whisper` + PyTorch | Audio-only |
| Linux | Not supported currently | - |

## Quick Start

### macOS

```bash
source scripts/setup-macos.sh
python -m vocal_scriber --debug
```

### Windows PowerShell

```powershell
. .\scripts\setup-windows.ps1
python -m vocal_scriber --debug
```

The setup scripts create `.venv`, activate it, and install the package in editable mode with the correct platform extra. The Windows script also installs the CUDA 13 PyTorch build first.

## Main Command

```bash
python -m vocal_scriber
```

Examples:

```bash
python -m vocal_scriber --debug
python -m vocal_scriber --model base
python -m vocal_scriber --vocab "Claude,Anthropic,Docker,Kubernetes"
python -m vocal_scriber --gui
python -m vocal_scriber --no-gui
python -m vocal_scriber --api http://localhost:8002/transcribe
```

## Recording Flow

1. Focus the app you want to paste into.
2. Press `F9` to start recording.
3. Speak naturally.
4. Press `F9` again to stop and transcribe.
5. Vocal-Scriber pastes the text into the focused app.

Press `Ctrl+C` in the Vocal-Scriber terminal to stop the app.

## Platform Notes

### macOS

- Uses `faster-whisper`
- Menu bar waveform is the default visualization
- `--gui` switches to the floating waveform window

### Windows

- Uses `openai-whisper` on top of PyTorch
- Prefers GPU automatically when `torch.cuda.is_available()` is true
- Falls back to CPU automatically if CUDA is unavailable or runtime init fails
- Collapses duplicate host-API microphone entries into a cleaner logical device list

### Windows CUDA 13

Windows local GPU transcription is designed around PyTorch rather than CTranslate2.

If you want to verify GPU visibility inside the activated venv:

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.version.cuda)"
```

More detail is in [docs/windows/cuda.md](docs/windows/cuda.md).

## Troubleshooting

### `No module named ...`

Activate the local virtual environment and rerun the platform setup script.

### Windows loads on CPU instead of GPU

The app will still work. Check:

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.version.cuda)"
```

If CUDA is not visible to PyTorch, review [docs/windows/cuda.md](docs/windows/cuda.md).

### Microphone list looks wrong on Windows

Vocal-Scriber groups Windows backend duplicates into one entry per logical microphone. If one device entry still misbehaves, choose a different physical microphone or let the app use the default device.

### Menu bar icon missing on macOS

Reinstall the package with the macOS extra:

```bash
python -m pip install -e ".[macos]"
```

## Speaker Diarization

Speaker diarization is a separate Apple-Silicon-only tool under [`tools/diarization/`](tools/diarization/README.md).

```bash
python tools/diarization/diarize.py audio.wav
```

Install its dependencies separately:

```bash
python -m pip install -r tools/diarization/requirements.txt
```

## Repository Layout

```text
src/vocal_scriber/          # Main package
scripts/                    # Platform setup helpers
docs/windows/               # Windows runtime notes
docs/internal/              # Internal engineering notes
tools/diarization/          # Separate macOS-only diarization workflow
```

## Environment Configuration

Optional environment variables are documented in `.env.example`. They are currently used by the diarization tool, not the main push-to-talk app.

## License

MIT. See [LICENSE](LICENSE).
