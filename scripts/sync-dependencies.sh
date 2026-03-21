#!/bin/bash
# Sync dependencies.yaml between main package and installer
#
# This script ensures that the dependencies.yaml file in the installer package
# stays in sync with the main package's dependencies.yaml file.
#
# The main file (voice_mode/dependencies.yaml) is the source of truth.
# The installer file (installer/voicemode_install/dependencies.yaml) is a copy.
#
# This script is automatically run by 'make build-installer' to ensure
# the installer always has the latest dependency definitions.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

MAIN_DEPS="$PROJECT_ROOT/voice_mode/dependencies.yaml"
INSTALLER_DEPS="$PROJECT_ROOT/installer/voicemode_install/dependencies.yaml"

if [ ! -f "$MAIN_DEPS" ]; then
    echo "❌ Main dependencies.yaml not found at: $MAIN_DEPS"
    exit 1
fi

# Copy main to installer
echo "📋 Syncing dependencies.yaml from main package to installer..."
cp "$MAIN_DEPS" "$INSTALLER_DEPS"

echo "✅ Dependencies synchronized!"
echo "   Source: voice_mode/dependencies.yaml"
echo "   Target: installer/voicemode_install/dependencies.yaml"

# Check if files are identical
if diff -q "$MAIN_DEPS" "$INSTALLER_DEPS" > /dev/null; then
    echo "✅ Files are identical"
else
    echo "⚠️  Warning: Files differ after copy (this shouldn't happen)"
    exit 1
fi