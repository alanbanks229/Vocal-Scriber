# Diarization Tool

`tools/diarization/diarize.py` is a separate Apple-Silicon-only workflow for speaker diarization on pre-recorded audio files.

It is not part of the main push-to-talk app.

## Requirements

- Apple Silicon macOS (`arm64`)
- Python 3.11+
- `ffmpeg` for formats like MP3, M4A, and FLAC

## Install

```bash
python -m pip install -r tools/diarization/requirements.txt
```

## Run

```bash
python tools/diarization/diarize.py audio.wav
python tools/diarization/diarize.py meeting.mp3 --context "Claude, Anthropic, Docker"
```

The script reads optional repo-root `.env` values such as `HF_TOKEN` and `DIARIZE_MODEL`.
