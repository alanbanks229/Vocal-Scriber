# Vocal-Scriber

**Push-to-talk voice input for Claude Code CLI (and any terminal).**

Press F9, speak, press F9 again — your words instantly appear in Claude Code's CLI prompt. Uses local Whisper transcription, no cloud API required.

---

## What This Does

- **Voice-to-text for terminals**: Speak long, detailed prompts instead of typing them
- **Optimized for Claude Code CLI**: Works perfectly with full-screen VS Code
- **Local & Private**: Whisper runs on your Mac, no data sent anywhere
- **Fast transcription**: 1-2 seconds on M-series Macs
- **Manual start**: Start when needed, stop when done (not a background service)

---

## Quick Start

### Installation

**1. Clone or download this repository**

**2. Install Python dependencies:**
```bash
cd vocal-scriber
pip install -r requirements.txt
```

**3. Grant permissions (macOS):**
- **System Settings → Privacy & Security → Accessibility**
- Add Terminal/VS Code, toggle ON
- Microphone permission will prompt on first run

**First run downloads Whisper model** (~500MB for `small` model, one-time download).

### Usage

**Terminal 1 - Start Vocal-Scriber:**
```bash
cd vocal-scriber
python vocal-scriber.py
```

*Leave this running in the background*

**Terminal 2 - Start Claude Code:**
```bash
claude-code
```

### Recording Voice Input

1. **Click into Claude Code CLI prompt** (important!)
2. **Press F9** → hear a beep (recording started)
3. **Speak your prompt naturally**
4. **Press F9** → hear another beep (transcribing...)
5. **Text appears** in Claude Code CLI

### When Done

Press `Ctrl+C` in Terminal 1 to stop Vocal-Scriber.

**No background service = no wasted resources when you're not using it.**

---

## Command-Line Options

### Basic Usage

```bash
# Default: local Whisper with 'small' model
python vocal-scriber.py

# Use different model size
python vocal-scriber.py --model base
python vocal-scriber.py --model medium

# Add custom vocabulary for better recognition
python vocal-scriber.py --vocab "Kubernetes,Docker,Claude,Anthropic"

# Debug mode
python vocal-scriber.py --debug

# Select microphone device interactively
python vocal-scriber.py --device

# Adjust speech detection sensitivity
python vocal-scriber.py --threshold 0.003
```

### API Mode (Optional)

Use a remote Whisper API instead of local transcription:

```bash
python vocal-scriber.py --api http://localhost:8002/transcribe
python vocal-scriber.py --api http://localhost:8002/transcribe --api-model whisper-1
```

---

## Model Selection

Default model is **`small`** (~500MB), which provides good accuracy and speed.

### Model Comparison

| Model | Size | Speed (M4 Pro) | Accuracy | Use Case |
|-------|------|----------------|----------|----------|
| `tiny` | 75MB | 0.5s | Basic | Testing only |
| `base` | 150MB | 0.8s | Decent | Faster, lower accuracy |
| **`small`** | 500MB | 1.5s | **Good** | **Default - Recommended** |
| `medium` | 1.5GB | 2.5s | Great | High accuracy |
| `large-v3` | 3GB | 4s | Best | Maximum quality |

**Examples:**

```bash
# Faster transcription, lower accuracy
python vocal-scriber.py --model base

# Higher accuracy, slightly slower
python vocal-scriber.py --model medium
```

---

## File Structure

```
vocal-scriber/
├── README.md                      # This file
├── LICENSE                        # MIT license
├── .gitignore                     # Git ignore patterns
├── .env.example                   # Environment config reference
├── requirements.txt               # Python dependencies (main script)
├── requirements-diarization.txt   # Python dependencies (speaker diarization)
├── vocal-scriber.py               # Main script (push-to-talk voice → text)
├── diarize.py                     # Speaker diarization (file processing)
└── venv/                          # Python virtual environment (created by pip)
```

---

## How It Works

```
[F9 Press] → Start Recording
           ↓
[You Speak]
           ↓
[F9 Press] → Stop Recording → Transcribe with Whisper
           ↓
Paste to Currently Focused Window (Claude Code CLI)
```

**Key Design Decisions:**

1. **No window refocusing by default** - Pastes to whatever window is focused when you press F9
   - This avoids macOS full-screen Space switching issues
   - Just click into Claude Code CLI before pressing F9

2. **0.3s audio buffer** - Captures the end of your speech after you press F9
   - Prevents cutting off your last word

3. **Manual start, not a service** - Only uses resources when you need it
   - ~1-2GB RAM while running
   - Zero resources when stopped

---

## Troubleshooting

### Audio cuts off last word
- The 0.3s buffer should capture it
- Try speaking slightly slower at the end
- Or pause briefly before pressing F9

### Extra whitespace in transcription
- Default `small` model should handle this well
- Try adding vocabulary context: `--vocab "common,terms,you,use"`
- Or upgrade to `medium` model for better accuracy

### Text pastes to wrong window
- **Click into Claude Code CLI** before pressing F9
- Vocal-Scriber pastes to the currently focused window
- This is by design (avoids Space switching in full-screen mode)

### Slow transcription
- You may be using `medium` or `large-v3` model
- Switch to `small` for faster results: `python vocal-scriber.py --model small`
- Or use `base` for maximum speed (lower accuracy)

### Permission errors
- **System Settings → Privacy & Security → Accessibility**
- Add your Terminal app and VS Code
- Restart Vocal-Scriber after granting permissions

### "No module named..." errors
- Make sure you installed dependencies: `pip install -r requirements.txt`
- If using a virtual environment, activate it first: `source venv/bin/activate`

### Microphone not working
- Use `--device` flag to select your microphone interactively:
  ```bash
  python vocal-scriber.py --device
  ```
- Grant microphone permission when prompted

---

## Requirements

- **macOS** (tested on M1/M2/M3/M4 Macs)
- **Python 3.9+** (usually pre-installed on macOS)
- **2GB disk space** (for Whisper models)
- **Microphone access**
- **Accessibility permissions** (for keyboard input)

---

## Advanced Features

### Custom Vocabulary

Help Whisper recognize technical terms or names:

```bash
python vocal-scriber.py --vocab "Kubernetes,Docker,MLX,Anthropic,Claude"
```

This improves accuracy for domain-specific terminology.

### Adjust Speech Detection Threshold

Control sensitivity for detecting speech:

```bash
# More sensitive (picks up quieter speech)
python vocal-scriber.py --threshold 0.002

# Less sensitive (ignores background noise)
python vocal-scriber.py --threshold 0.01
```

Default is `0.005`.

### Debug Mode

See detailed output (window detection, clipboard, paste commands):

```bash
python vocal-scriber.py --debug
```

---

## Speaker Diarization (Apple Silicon Only)

**Identify different speakers in audio recordings using MLX-optimized AI.**

This is a separate feature from push-to-talk voice input. Use `diarize.py` to process pre-recorded audio files with speaker identification.

### What is Speaker Diarization?

Speaker diarization identifies "who spoke when" in audio recordings:
- Meeting transcriptions with speaker labels
- Interview transcripts with speaker identification
- Multi-speaker recordings with timestamps

### Requirements

- **Apple Silicon Mac** (M1/M2/M3/M4)
- **~10GB disk space** (for VibeVoice-ASR model)
- **ffmpeg** (for M4A/MP3 audio decoding)
- **Additional dependencies** (separate from main vocal-scriber)

### Installation

**1. Install ffmpeg (required for M4A/MP3 files):**
```bash
brew install ffmpeg
```

**2. Install Python dependencies:**
```bash
pip install -r requirements-diarization.txt
```

**3. (Optional) Configure HuggingFace token for faster downloads:**
```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your HuggingFace token
# Get token at: https://huggingface.co/settings/tokens
```

This enables faster model downloads on first run. Without it, downloads still work but may be slower.

**First run downloads ~9GB model** (one-time, stored in HuggingFace cache at `~/.cache/huggingface/`).

**Note:** WAV files work without ffmpeg, but M4A/MP3/FLAC require it for audio decoding.

### Usage

**Basic diarization:**
```bash
python diarize.py meeting.wav
```

Output:
```
[0.0-5.2] Speaker 0: Hello everyone, let's begin the meeting.
[5.5-9.8] Speaker 1: Thanks for joining today.
[10.2-15.0] Speaker 0: Let's start with the agenda.
```

**With vocabulary context (improves accuracy):**
```bash
python diarize.py audio.wav --context "Claude, Anthropic, MLX, Kubernetes, Docker"
```

**Save to file (text format):**
```bash
python diarize.py meeting.mp3 --output transcript.txt
```

**Save to file (JSON format):**
```bash
python diarize.py audio.wav --output result.json
```

**Show progress during processing:**
```bash
python diarize.py meeting.wav --verbose
```

**Debug memory and performance:**
```bash
python diarize.py audio.m4a --debug --verbose
```

**Override max_tokens for very long audio:**
```bash
python diarize.py long_meeting.wav --max-tokens 16384
```

### Supported Audio Formats

- WAV
- MP3
- M4A
- FLAC

### Performance

On Apple Silicon (M1/M2/M3/M4):
- **~4-6x realtime** (10 minutes of audio processes in ~2 minutes)
- **Auto-optimized memory usage** - max_tokens calculated based on audio duration
- Uses Metal GPU acceleration
- Much faster than PyTorch-based alternatives (~10x speedup)
- Use `--debug` flag to see actual memory usage and timing statistics

### Limitations

- **Apple Silicon only** - Requires arm64 architecture
- **Not for real-time** - Processes pre-recorded files only
- **Large model** - VibeVoice-ASR is ~9GB (one-time download)
- **Separate from push-to-talk** - Use `vocal-scriber.py` for F9 hotkey transcription

### Why a Separate Script?

`diarize.py` is separate from `vocal-scriber.py` because:
1. Different use case (file processing vs real-time push-to-talk)
2. Different dependencies (MLX vs faster-whisper)
3. Larger model size (~9GB vs ~500MB)
4. Optional feature (not everyone needs speaker identification)

---

## Why Not Run as a Service?

Vocal-Scriber is designed to **start manually** when you need voice input, not run 24/7.

**Running as a background service would:**
- ❌ Use 1-2GB RAM constantly (even when you're not coding)
- ❌ Keep Whisper model loaded 24/7
- ❌ More complex to set up on new machines
- ✅ Only save 3-5 seconds of startup time

**Manual start is perfect:**
- ✅ Start it when you launch Claude Code
- ✅ Stop it when you're done (Ctrl+C)
- ✅ Zero resource usage when not in use
- ✅ Simple to manage

---

## Distribution to Other Machines

### Method 1: Clone Repository

**On new machine:**
```bash
# Clone or copy the repository
cd vocal-scriber

# Install dependencies
pip install -r requirements.txt

# Grant permissions (macOS)
# System Settings → Privacy & Security → Accessibility → Add Terminal/VS Code

# Start using it
python vocal-scriber.py
```

**First run downloads the Whisper model** (~500MB for `small`, ~150MB for `base`).

### Method 2: Create Zip Package

**On your current machine:**
```bash
# Create a zip excluding venv and cache files
zip -r vocal-scriber.zip . -x "*.pyc" -x "*__pycache__*" -x "venv/*" -x ".git/*" -x ".claude/*" -x "*.log" -x "test*"
```

**On new machine:**
```bash
# Extract
unzip vocal-scriber.zip
cd vocal-scriber

# Install dependencies
pip install -r requirements.txt

# Grant permissions (macOS)
# System Settings → Privacy & Security → Accessibility → Add Terminal/VS Code

# Start using it
python vocal-scriber.py
```

---

## Environment Configuration

The `.env.example` file documents optional environment variables:

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your configuration
# Currently supports:
# - HF_TOKEN: HuggingFace token for faster model downloads (diarization only)
```

The `.env` file is ignored by git (safe for tokens/secrets).

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Tips for Best Results

1. **Use default `small` model** for best balance of speed and accuracy
2. **Click into CLI** before pressing F9 (doesn't auto-focus by design)
3. **Speak naturally** - don't over-articulate or rush
4. **Pause before F9** - gives the 0.3s buffer time to capture your last word
5. **Add custom vocabulary** for technical terms: `--vocab "Docker,Kubernetes,Claude"`
6. **Start Vocal-Scriber once** per coding session, leave it running
