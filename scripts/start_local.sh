#!/bin/bash

# Start Vocal-Scriber in Local Mode
# Uses local Whisper transcription (no API server)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Check if virtual environment exists
if [ ! -d "$BASE_DIR/venv" ]; then
    echo "❌ Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Activate virtual environment
source "$BASE_DIR/venv/bin/activate"

# Check if vocal-scriber.py exists
if [ ! -f "$BASE_DIR/vocal-scriber.py" ]; then
    echo "❌ vocal-scriber.py not found"
    exit 1
fi

echo "Starting Vocal-Scriber in Local Mode..."
echo "Model: base (default)"
echo "Press F9 to start recording"
echo "Press Ctrl+C to stop"
echo ""

# Run Vocal-Scriber
cd "$BASE_DIR"
python3 vocal-scriber.py "$@"
