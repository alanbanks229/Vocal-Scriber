# Vocal-Scriber

**Usage Examples:**

```bash
# Default (base model)
python3 vocal-scriber.py

# Use small model for better accuracy
python3 vocal-scriber.py --model small

# Use large model for best accuracy
python3 vocal-scriber.py --model large-v3
```
  
**Push-to-talk voice input for Claude Code CLI (and any terminal).**

Press F9, speak, press F9 again — your words instantly appear in Claude Code's CLI prompt. Uses local Whisper transcription, no cloud API required.

![Demo](assets/demo.gif)

---

## What This Does

- **Voice-to-text for terminals**: Speak long, detailed prompts instead of typing them
- **Optimized for Claude Code CLI**: Works perfectly with full-screen VS Code
- **Local & Private**: Whisper runs on your Mac, no data sent anywhere
- **Fast transcription**: 1-2 seconds on M-series Macs
- **Manual start**: Start when needed, stop when done (not a background service)

---

## Quick Install

### On Your First Machine

```bash
cd vocal-scriber-main
./scripts/setup.sh
```

This installs Python dependencies and sets up the virtual environment.

### On Additional Machines

1. **Create distribution package:**
   ```bash
   ./scripts/create_distribution.sh
   ```
   This creates `vocal-scriber-v1.0.zip` on your Desktop

2. **Copy to new machine and install:**
   ```bash
   unzip vocal-scriber-v1.0.zip
   cd vocal-scriber-v1.0
   ./scripts/setup.sh
   ```

3. **Grant permissions on new machine:**
   - **System Settings → Privacy & Security → Accessibility**
   - Add Terminal/VS Code, toggle ON
   - Microphone permission will prompt on first run

---

## Usage

### Starting Vocal-Scriber

**Terminal 1 - Start Vocal-Scriber:**
```bash
cd vocal-scriber-main
./scripts/start_local.sh
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

## Model Selection

Default model is `base` (~150MB), which is fast but has some whitespace/punctuation issues.

### Recommended: Use `small` Model

```bash
./scripts/start_local.sh --model small
```

**Why upgrade from `base` to `small`:**
- ✅ Much better punctuation and spacing
- ✅ Fewer transcription errors
- ✅ Still fast (~1-2s on M-series Macs)
- ✅ Only 500MB download (one-time)

### Model Comparison

| Model | Size | Speed (M4 Pro) | Accuracy | Use Case |
|-------|------|----------------|----------|----------|
| `tiny` | 75MB | 0.5s | Basic | Testing only |
| `base` | 150MB | 0.8s | Decent | Default, but has issues |
| **`small`** | 500MB | 1.5s | **Good** | **Recommended** |
| `medium` | 1.5GB | 2.5s | Great | High accuracy |
| `large-v3` | 3GB | 4s | Best | Maximum quality |

**Your M4 Pro can easily handle `small` or `medium`.**

---

## File Structure

```
vocal-scriber-main/
├── README.md              # This file
├── INSTALL.md             # Setup guide for new machines
├── LICENSE                # MIT license
├── requirements.txt       # Python dependencies
├── vocal-scriber.py           # Main script (voice → text → paste)
├── scripts/
│   ├── setup.sh                  # Install dependencies
│   ├── start_local.sh            # Start Vocal-Scriber
│   └── create_distribution.sh    # Package for other machines
├── assets/
│   └── demo.gif          # README demo
└── venv/                 # Python virtual environment (created by setup.sh)
```

**Note:** `venv/` is excluded from distribution zips (gets recreated on each machine).

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
- **Upgrade to `small` model** (fixes 90% of issues):
  ```bash
  ./scripts/start_local.sh --model small
  ```

### Text pastes to wrong window
- **Click into Claude Code CLI** before pressing F9
- Vocal-Scriber pastes to the currently focused window
- This is by design (avoids Space switching in full-screen mode)

### Slow transcription
- You're likely using `base` model
- Upgrade to `small` (still fast, better quality)
- Or downgrade to `tiny` if speed is critical

### Permission errors
- **System Settings → Privacy & Security → Accessibility**
- Add your Terminal app and VS Code
- Restart Vocal-Scriber after granting permissions

### "No module named..." errors
- Make sure virtual environment is activated:
  ```bash
  source venv/bin/activate
  ```
- Or just use `./scripts/start_local.sh` (activates automatically)

---

## Requirements

- **macOS** (tested on M1/M2/M3/M4 Macs)
- **Python 3.9+** (usually pre-installed on macOS)
- **2GB disk space** (for Whisper models)
- **Microphone access**
- **Accessibility permissions** (for keyboard input)

---

## Advanced Options

### Enable debug mode
```bash
./scripts/start_local.sh --debug
```
Shows detailed output (window detection, clipboard, paste commands)

### Use different hotkey
```bash
./scripts/start_local.sh --hotkey f8
```

### Change language
```bash
./scripts/start_local.sh --language es  # Spanish
```

### Adjust paste delay
```bash
./scripts/start_local.sh --paste-delay 0.5
```

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

### Creating a Package

On your current machine:
```bash
./scripts/create_distribution.sh
```

This creates `vocal-scriber-v1.0.zip` on your Desktop (without venv, ~2MB).

### Installing on New Machine

```bash
# 1. Copy zip to new machine
# 2. Extract
unzip vocal-scriber-v1.0.zip
cd vocal-scriber-v1.0

# 3. Run setup
./scripts/setup.sh

# 4. Grant permissions
# System Settings → Privacy & Security → Accessibility → Add Terminal/VS Code

# 5. Start using it
./scripts/start_local.sh
```

**First run downloads the Whisper model** (~150MB for `base`, ~500MB for `small`).

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Tips for Best Results

1. **Use `small` model** for better transcription quality
2. **Click into CLI** before pressing F9 (doesn't auto-focus by design)
3. **Speak naturally** - don't over-articulate or rush
4. **Pause before F9** - gives the 0.3s buffer time to capture your last word
5. **Start Vocal-Scriber once** per coding session, leave it running

---

## Questions?

- See `INSTALL.md` for detailed setup instructions
- Use `--debug` flag to troubleshoot issues