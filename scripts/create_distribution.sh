#!/bin/bash

# create_distribution.sh packages your project into a zip file that you can easily move to other computers or share with other people.                                                                                                                               
#   What it does:                                                                                                                                  
#   - Takes all your code files (vocal-scriber.py, scripts, requirements.txt, etc.)                                                                
#   - Leaves out the heavy stuff (the venv folder with all the Python libraries)                                                                   
#   - Creates a small, clean zip file on your Desktop
#   - The zip is only ~50KB instead of hundreds of MB

#   Why would you use it?
#   Scenario: You want to use Vocal-Scriber on your work laptop AND your personal Mac.

#   1. On your first computer: Run ./scripts/create_distribution.sh
#   2. Result: A zip file appears on your Desktop
#   3. Copy that zip to your other computer (USB drive, cloud, whatever)
#   4. On the new computer: Unzip it, run ./scripts/setup.sh
#   5. Done! The setup script downloads fresh Python libraries for that machine

#   Bottom line: It's a "share with other machines" button. Makes it easy to deploy Vocal-Scriber without carrying around hundreds of megabytes of
#   Python libraries.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_NAME="vocal-scriber-v1.0"

echo "Creating Vocal-Scriber distribution package..."
echo ""

# Go to parent directory of project
cd "$(dirname "$PROJECT_DIR")"

# Create temp directory with clean copy
echo "📦 Preparing files..."
rm -rf "/tmp/$DIST_NAME"
mkdir -p "/tmp/$DIST_NAME"

# Copy essential files only (no venv, no cache)
rsync -av --exclude='venv' \
          --exclude='.claude' \
          --exclude='__pycache__' \
          --exclude='*.pyc' \
          --exclude='.DS_Store' \
          --exclude='*.log' \
          "$PROJECT_DIR/" "/tmp/$DIST_NAME/"

# Create the zip
echo ""
echo "📦 Creating zip archive..."
cd /tmp
zip -r "$DIST_NAME.zip" "$DIST_NAME" -q

# Move to Desktop for easy access
DESKTOP="$HOME/Desktop"
if [ -d "$DESKTOP" ]; then
    mv "$DIST_NAME.zip" "$DESKTOP/"
    echo ""
    echo "✅ Distribution created: $DESKTOP/$DIST_NAME.zip"
    echo ""
    echo "Size: $(du -h "$DESKTOP/$DIST_NAME.zip" | cut -f1)"
    echo ""
    echo "📋 To use on another machine:"
    echo "   1. Copy zip to new machine"
    echo "   2. unzip $DIST_NAME.zip"
    echo "   3. cd $DIST_NAME"
    echo "   4. ./scripts/setup.sh"
    echo "   5. ./scripts/start_local.sh"
else
    mv "$DIST_NAME.zip" "$PROJECT_DIR/"
    echo ""
    echo "✅ Distribution created: $PROJECT_DIR/$DIST_NAME.zip"
fi

# Cleanup
rm -rf "/tmp/$DIST_NAME"

echo ""
echo "🎉 Ready to distribute!"
