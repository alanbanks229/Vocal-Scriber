#!/bin/bash

# Vocal-Scriber Setup Script
# Automates complete installation on macOS

set -e  # Exit on error

echo "======================================"
echo "  Vocal-Scriber Setup for macOS"
echo "======================================"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Functions for colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo "ℹ️  $1"
}

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "This script is designed for macOS only"
    exit 1
fi

print_success "Running on macOS"

# Step 1: Check/Install Homebrew
echo ""
echo "Step 1: Checking Homebrew..."
if command -v brew &> /dev/null; then
    print_success "Homebrew is installed"
    BREW_VERSION=$(brew --version | head -n1)
    print_info "$BREW_VERSION"
else
    print_warning "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Add Homebrew to PATH for Apple Silicon
    if [[ $(uname -m) == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi

    if command -v brew &> /dev/null; then
        print_success "Homebrew installed successfully"
    else
        print_error "Homebrew installation failed"
        exit 1
    fi
fi

# Step 2: Install PortAudio
echo ""
echo "Step 2: Installing PortAudio..."
if brew list portaudio &> /dev/null; then
    print_success "PortAudio already installed"
else
    print_info "Installing portaudio via Homebrew..."
    brew install portaudio
    print_success "PortAudio installed"
fi

# Step 3: Check Python
echo ""
echo "Step 3: Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    print_success "Python is installed: $PYTHON_VERSION"

    # Check version is 3.8+
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

    if [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -ge 8 ]]; then
        print_success "Python version is compatible (3.8+)"
    else
        print_error "Python 3.8+ required, found Python $PYTHON_MAJOR.$PYTHON_MINOR"
        exit 1
    fi
else
    print_error "Python 3 not found. Please install Python 3.8 or later."
    exit 1
fi

# Step 4: Create Virtual Environment
echo ""
echo "Step 4: Setting up virtual environment..."
cd "$BASE_DIR"

if [ -d "venv" ]; then
    print_warning "Virtual environment already exists"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Removing existing virtual environment..."
        rm -rf venv
        python3 -m venv venv
        print_success "Virtual environment recreated"
    else
        print_info "Using existing virtual environment"
    fi
else
    print_info "Creating virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Step 5: Activate Virtual Environment and Install Dependencies
echo ""
echo "Step 5: Installing Python dependencies..."
source "$BASE_DIR/venv/bin/activate"

if [ ! -f "$BASE_DIR/requirements.txt" ]; then
    print_error "requirements.txt not found in $BASE_DIR"
    exit 1
fi

print_info "Upgrading pip..."
pip install --upgrade pip --quiet

print_info "Installing dependencies (this may take a few minutes)..."
if pip install -r "$BASE_DIR/requirements.txt" --quiet; then
    print_success "Dependencies installed successfully"
else
    print_error "Failed to install dependencies"
    echo ""
    echo "If you're behind a corporate proxy, see: PROXY_WORKAROUND.md"
    exit 1
fi

# Step 6: Pre-download Whisper Model
echo ""
echo "Step 6: Pre-downloading Whisper 'base' model..."
print_info "This downloads ~145MB (one-time setup)"

"$BASE_DIR/venv/bin/python3" << 'EOF'
import sys
try:
    from faster_whisper import WhisperModel
    print("Downloading base model...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    print("✅ Model downloaded and cached")
except Exception as e:
    print(f"❌ Failed to download model: {e}")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    print_success "Whisper model ready"
else
    print_error "Model download failed"
    exit 1
fi

# Step 7: Security Scan (Optional)
echo ""
echo "Step 7: Security scan (optional)..."
print_warning "pip-audit may not work in corporate environments with SSL inspection"
print_info "Would you like to attempt a security vulnerability scan? (y/N): "
read -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Installing pip-audit..."
    if ! pip install pip-audit > /dev/null 2>&1; then
        print_warning "Failed to install pip-audit, skipping scan"
    else
        print_info "Scanning dependencies for vulnerabilities..."
        echo ""

        # Set the correct Python location for pip-audit to use the venv
        export PIPAPI_PYTHON_LOCATION="$BASE_DIR/venv/bin/python3"

        if pip-audit 2>&1; then
            print_success "No known vulnerabilities found"
        else
            echo ""
            print_warning "Security scan failed (likely SSL/proxy issues in corporate environment)"
            print_info "This doesn't affect Vocal-Scriber functionality"
            print_info "To manually scan later (when off VPN): source venv/bin/activate && pip-audit"
        fi
    fi
else
    print_info "Skipping security scan (recommended for corporate networks)"
fi

# Step 8: Check Permissions
echo ""
echo "Step 8: Checking macOS permissions..."
print_warning "Vocal-Scriber requires Accessibility and Microphone permissions"
echo ""
echo "To grant Accessibility permissions:"
echo "  1. Open System Settings"
echo "  2. Go to Privacy & Security → Accessibility"
echo "  3. Add your Terminal app (Terminal or iTerm2)"
echo "  4. Toggle the switch ON"
echo ""
echo "Microphone permissions will be requested when you first run Vocal-Scriber."
echo ""
read -p "Press Enter once you've granted Accessibility permissions..."

# Test permissions
echo ""
print_info "Testing permissions..."
"$BASE_DIR/venv/bin/python3" << 'EOF'
try:
    from pynput import keyboard
    print("✅ Keyboard monitoring available")
except Exception as e:
    print(f"⚠️  Keyboard monitoring may not work: {e}")

try:
    import sounddevice as sd
    devices = sd.query_devices()
    print(f"✅ Found {len([d for d in devices if d['max_input_channels'] > 0])} microphone(s)")
except Exception as e:
    print(f"⚠️  Microphone access may not work: {e}")
EOF

# Step 9: Setup complete!
echo ""
echo "Step 9: Setup complete!"
echo ""
print_success "Vocal-Scriber is ready to use!"
echo ""
echo "Quick Start:"
echo "  1. Activate virtual environment:"
echo "     source $BASE_DIR/venv/bin/activate"
echo ""
echo "  2. Run Vocal-Scriber:"
echo "     python3 $BASE_DIR/vocal-scriber.py"
echo ""
echo "  3. Press F9 to record, speak, release F9"
echo ""
echo "Convenience scripts:"
echo "  - Start in local mode: $SCRIPT_DIR/start_local.sh"
echo ""
echo ""
echo "For detailed usage, see: $BASE_DIR/README.md"
echo ""
print_success "Setup complete! 🎉"
