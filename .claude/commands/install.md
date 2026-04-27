---
name: install
description: Install VoiceMode, FFmpeg, and configure the local HTTP MCP server
allowed-tools: Bash(uvx:*), Bash(voicemode:*), Bash(brew:*), Bash(uname:*), Bash(which:*)
---

# /voicemode:install

Install VoiceMode and the dependencies needed for ElevenLabs-backed voice conversations.

## Quick Install (Non-Interactive)

For a fast install:

```bash
uvx voice-mode-install --yes
```

## What Gets Installed

| Component | Size | Purpose |
|-----------|------|---------|
| FFmpeg | ~50MB | Audio processing (via Homebrew) |
| VoiceMode CLI | ~10MB | Command-line tools and server management |
| ElevenLabs API key | — | TTS/STT provider access |

## Implementation

1. **Check architecture:** `uname -m` (arm64 = Apple Silicon, recommended for local services)

2. **Check what's already installed:**
   ```bash
   which voicemode  # VoiceMode CLI
   which ffmpeg     # Audio processing
   ```

3. **Install missing components:**
   ```bash
   # Full install (installs ffmpeg, voicemode, and checks dependencies)
   uvx voice-mode-install --yes
   ```

4. **Configure ElevenLabs:**
   ```bash
   # In ~/.voicemode/voicemode.env
   ELEVENLABS_API_KEY=your-key-here
   ```

5. **Verify the local HTTP MCP server is running:**
   ```bash
   ./scripts/voicemode-server.sh status
   ```

6. **Reconnect MCP server:**
   After installation, the VoiceMode MCP server needs to reconnect:
   - Run `/mcp` and select voicemode, then click "Reconnect", OR
   - Restart Claude Code

## Prerequisites

This install process assumes:
- **UV** - Python package manager (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Homebrew** - macOS package manager (install: `brew.sh`)

The VoiceMode installer will install Homebrew if missing on macOS.

For complete documentation, load the `voicemode` skill.
