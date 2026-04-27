---
name: voicemode
description: |
  Voice interaction for Claude Code. Provides natural voice conversations using ElevenLabs TTS and STT.
  Use when users mention voice mode, speak, talk, converse, voice status, or voice troubleshooting.
  ElevenLabs-only: eleven_v3 TTS model, Scribe v2 Realtime STT with local Silero VAD.
---

# VoiceMode for Claude Code

Natural voice conversations with Claude Code using ElevenLabs text-to-speech (TTS) and speech-to-text (STT).

## The Jarvis Goal

VoiceMode aims to create a Jarvis-like voice assistant experience. The AI speaks to you and listens, like a real conversation. Use `converse` for ALL communication -- never respond with text in the chat.

## Setup

### 1. Configure MCP Server

VoiceMode runs as an HTTP server on port 8765. Add to your Claude Code MCP settings (`~/.claude/settings.json`):

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

### 2. Configure ElevenLabs

Set your ElevenLabs API key:

```bash
# In ~/.voicemode/voicemode.env
ELEVENLABS_API_KEY=your-key-here
```

ElevenLabs provides:
- **TTS**: `eleven_v3` model with Donna voice (cloned)
- **STT**: Scribe v2 Realtime (streaming WebSocket with manual commit mode)

## Usage

Use the `converse` MCP tool. **Always use these defaults:**

```python
# Speak and listen for response
converse(message="Hello! What would you like to work on?", listen_duration_min=5, listen_duration_max=300, timeout=300, wait_for_conch=true)

# Speak without waiting (narration while working)
converse(message="Searching the codebase now...", wait_for_response=false, speed=1.2)

# User wants to say something long
converse(message="Go ahead, I'm listening.", disable_silence_detection=true, listen_duration_max=120, speed=1.2)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak |
| `wait_for_response` | true | Listen after speaking |
| `speed` | server default `1.2` | Only pass when changing speed during a session |
| `listen_duration_min` | `5` | Don't cut off mid-sentence |
| `listen_duration_max` | `300` | Default maximum listen window |
| `timeout` | `300` | Must be >= `listen_duration_max` |
| `vad_aggressiveness` | `1` | VAD strictness (0-3). Lower = more tolerant of pauses. |
| `disable_silence_detection` | `false` | Set `true` to record for full duration |
| `metrics_level` | `summary` | Output detail: `minimal`, `summary`, or `verbose` |
| `wait_for_conch` | `true` | Queue behind another speaker if one is active |

## Best Practices

1. **Voice-primary communication** -- substantive responses go through `converse`; if voice fails, stop and restore MCP instead of continuing chat-only
2. **Trust server defaults** -- speed defaults to 1.2; pass optional parameters only when changing behavior
3. **Narrate without waiting rarely** -- Use `wait_for_response=false` only for short acknowledgements before work
4. **One question at a time** -- Don't bundle multiple questions
5. **Parallel calls** -- Combine `converse(msg, wait_for_response=false)` with other tools in one turn for zero dead air
6. **Long input** -- Set `disable_silence_detection=true` and `listen_duration_max=120` when user needs to speak at length

## Parallel Tool Calls (Zero Dead Air)

When performing actions during a voice conversation, use parallel tool calls to eliminate dead air:

```python
# FAST: One turn -- voice and action fire simultaneously
converse("Checking that now.", wait_for_response=false, speed=1.2)
bash("git status")

# Then speak the results
converse("Here's what I found: ...", wait_for_response=true, speed=1.2)
```

## Configuration

Config file: `~/.voicemode/voicemode.env`

### ElevenLabs Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ELEVENLABS_API_KEY` | (none) | API key -- required |
| `VOICEMODE_ELEVENLABS_TTS_MODEL` | `eleven_v3` | TTS model |
| `VOICEMODE_ELEVENLABS_TTS_VOICE` | `k4hP4cQadSZQc0Oar2Ld` | Voice ID (Donna) |
| `VOICEMODE_ELEVENLABS_STT_MODEL` | `scribe_v2_realtime` | STT model |
| `VOICEMODE_ELEVENLABS_REALTIME_STT` | `true` | Use realtime streaming STT |
| `VOICEMODE_SILENCE_THRESHOLD_MS` | `2000` | Silence threshold in ms (2.0s default) |

## Architecture

- **Server**: Single HTTP MCP server on `http://127.0.0.1:8765/mcp`
- **Auto-start**: Managed by launchd (macOS) via `scripts/voicemode-server.sh`
- **TTS**: ElevenLabs eleven_v3 with `convert()` + `play()` via ffplay
- **STT**: ElevenLabs Scribe v2 Realtime (WebSocket streaming) with manual commit mode
- **VAD**: Local Silero VAD (ONNX, no PyTorch) for silence detection -- sends manual commit when silence exceeds 2.0s threshold
- **Audio caching**: Recordings cached in memory for crash resilience -- if ElevenLabs disconnects mid-stream, cached audio is batch-transcribed
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

## Related Skills

- **[VoiceMode Connect](../voicemode-connect/SKILL.md)** -- Remote voice via mobile/web clients
