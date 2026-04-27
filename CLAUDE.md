# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

VoiceMode (ava) — a voice-first AI assistant MCP server. Python 3.10+, FastMCP v3, ElevenLabs TTS/STT.

## Build & Test

Package manager is `uv`. **Never use `python`/`python3`/`pip` directly — always `uv run`.**

```bash
make build              # Build voice-mode + installer packages
make test               # Unit tests (pytest)
make test-all           # Unit + integration
make test-parallel      # Parallel via pytest-xdist
make coverage           # Coverage report
uv run pytest tests/test_foo.py::test_bar -v   # Single test
uv run python -c "from voice_mode.server import mcp"  # Import check
ruff format <file>      # Format a file
make docs-serve         # Local docs (MkDocs)
```

## Server Development Workflow

The MCP server runs on `http://127.0.0.1:8765/mcp`, managed by launchd.

```bash
./scripts/voicemode-server.sh setup    # First time: create launchd plist + start
./scripts/voicemode-server.sh restart  # Restart after code changes
./scripts/voicemode-server.sh status   # Check if running
./scripts/voicemode-server.sh logs     # Tail logs
```

**After code changes, ALWAYS restart the server** — the running process does not pick up changes automatically.

**Gotcha**: launchd throttles rapid restarts. If `status` shows "Loaded but not listening", wait 10s or kill the port directly: `lsof -ti :8765 | xargs kill`, then `./scripts/voicemode-server.sh start`.

## Voice Interaction (MCP Tools)

When using VoiceMode's MCP tools:

- **Always use `converse`** for voice communication (never output text to chat)
- **Speed 1.2**: Always set `speed=1.2` (max ElevenLabs allows)
- **Don't cut off the user**: `listen_duration_min=5` minimum
- **Parallel execution**: `wait_for_response=false` + other tools in same turn for zero dead air
- **One speaker at a time**: `wait_for_conch=true` if another agent is speaking

Default converse call:
```
converse(message="...", speed=1.2, listen_duration_min=5, listen_duration_max=60, wait_for_response=true)
```

## Architecture

- **Server**: FastMCP v3 HTTP server on port 8765
- **TTS**: ElevenLabs eleven_v3 (Donna voice) via `convert()` + `play()` with ffplay
- **STT**: ElevenLabs Scribe v2 Realtime (WebSocket, manual commit mode)
- **VAD**: Silero VAD (ONNX, no PyTorch) for silence detection
- **Audio**: sounddevice + simpleaudio for mic/speaker
- **Vendored**: `fastmcp/` (forked FastMCP), `elevenlabs-python/` (forked ElevenLabs SDK)
- **Server mgmt**: launchd via `scripts/voicemode-server.sh`

## Environment

- `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`
- `UV_PUBLISH_TOKEN` for PyPI publishing (`make publish`)

## Git Workflow

Push directly to main. No PR conventions.
