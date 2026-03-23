# AGENTS.md

## What Is This

This is **VoiceMode (ava)** — a voice-first AI assistant MCP server. The goal is to create a **Jarvis-like experience** where the AI speaks to you naturally. All communication happens through voice, not text.

VoiceMode provides MCP tools that enable any AI coding assistant (Claude Code, Factory Droid, or any MCP-compatible client) to have natural voice conversations with the user.

## The Jarvis Goal

VoiceMode aims to be the voice layer for AI assistants — like Jarvis from Iron Man. The AI should:
- **Speak** all responses through the `converse` tool (never output text to chat)
- **Listen** for the user's spoken response
- **Converse naturally** — like a real conversation, not a command interface
- Handle long pauses, interruptions, and natural speech patterns gracefully

## MCP Tools

| Tool | Description |
|------|-------------|
| `converse` | Primary tool. Speak a message via TTS, optionally listen for user's spoken response via STT. |
| `connect_status` | Check connection status and who's online. Set presence to "available" or "away". |
| `service` | Manage VoiceMode services (status, start, stop, restart, enable, disable, logs). |

## Recommended Converse Defaults

**ALWAYS use these defaults unless the user explicitly asks otherwise:**

```
converse(
  message="Your message here",
  speed=1.2,                    # Max ElevenLabs speed
  listen_duration_min=5,        # Don't cut off mid-sentence
  listen_duration_max=60,       # Reasonable default
  wait_for_response=true        # Listen after speaking
)
```

### For long user input:
```
converse(
  message="Go ahead, I'm listening.",
  disable_silence_detection=true,
  listen_duration_max=120,
  speed=1.2
)
```

### For announcements (no listening):
```
converse(
  message="Working on that now.",
  wait_for_response=false,
  speed=1.2
)
```

## HTTP Server Setup

VoiceMode runs as a single HTTP server on port 8765. All clients connect to the same endpoint.

### MCP Configuration

```json
{
  "mcpServers": {
    "voicemode": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

### Architecture

- **Server**: Single HTTP MCP server on `http://127.0.0.1:8765/mcp`
- **Auto-start**: Managed by launchd (macOS) via `scripts/voicemode-server.sh`
- **TTS**: ElevenLabs eleven_v3 model with Donna voice, using `convert()` + `play()` via ffplay
- **STT**: ElevenLabs Scribe v2 Realtime (WebSocket streaming with manual commit mode)
- **VAD**: Local Silero VAD (ONNX, no PyTorch) for silence detection — sends manual commit when silence exceeds 2.0s threshold
- **Audio caching**: Recordings cached in memory for crash resilience — if ElevenLabs disconnects mid-stream, cached audio is batch-transcribed
- **Audio I/O**: Direct mic/speaker access on the host machine

### Server Management

```bash
# Via script (manages launchd plist)
scripts/voicemode-server.sh setup    # Create launchd plist + start
scripts/voicemode-server.sh start    # Start server
scripts/voicemode-server.sh stop     # Stop server
scripts/voicemode-server.sh restart  # Restart server
scripts/voicemode-server.sh status   # Check status
scripts/voicemode-server.sh logs     # Tail server logs
```

### Environment

Set `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`.

## Key Principles

1. **Voice-only communication**: The AI should NEVER respond with text. Always use `converse`.
2. **Speed 1.2**: Always set speed to 1.2 (max ElevenLabs allows).
3. **Don't cut off the user**: Use `listen_duration_min=5` minimum.
4. **Parallel execution**: Use `wait_for_response=false` + other tools in the same turn for zero dead air.
5. **One speaker at a time**: Use `wait_for_conch=true` if another agent is speaking.
