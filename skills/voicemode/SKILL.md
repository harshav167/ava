---
name: voicemode
description: |
  Voice interaction for Droid. Provides natural voice conversations using ElevenLabs TTS and STT.
  Use when users mention voice mode, speak, talk, converse, voice status, or voice troubleshooting.
  ElevenLabs-only: eleven_v3 TTS model, Scribe v2 Realtime STT.
---

# VoiceMode for Factory Droid

Natural voice conversations with Droid using ElevenLabs text-to-speech (TTS) and speech-to-text (STT).

## The Jarvis Goal

VoiceMode aims to create a Jarvis-like voice assistant experience. The AI speaks to you and listens, like a real conversation. Use `converse` for ALL communication — never respond with text in the chat.

## Setup

### 1. Configure MCP Server

VoiceMode runs as an HTTP server on port 8765. Add to your Droid MCP configuration (`~/.factory/mcp.json` or project `.factory/mcp.json`):

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
- **STT**: Scribe v2 Realtime (streaming WebSocket with server-side VAD)

## Usage

Use the `converse` MCP tool. **Always use these defaults:**

```python
# Speak and listen for response
converse(message="Hello! What would you like to work on?", speed=1.2, listen_duration_min=5, listen_duration_max=60)

# Speak without waiting (narration while working)
converse(message="Searching the codebase now...", wait_for_response=false, speed=1.2)

# User wants to say something long
converse(message="Go ahead, I'm listening.", disable_silence_detection=true, listen_duration_max=120, speed=1.2)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak |
| `wait_for_response` | true | Listen after speaking |
| `speed` | `1.2` | **Always use 1.2** (max ElevenLabs speed) |
| `listen_duration_min` | `5` | Don't cut off mid-sentence |
| `listen_duration_max` | `60` | Reasonable default |

## Best Practices

1. **Voice-only communication** — ALL responses go through `converse`, never text
2. **Speed 1.2 always** — Max ElevenLabs speed, user prefers fast speech
3. **Narrate without waiting** — Use `wait_for_response=false` when announcing actions
4. **One question at a time** — Don't bundle multiple questions
5. **Parallel calls** — Combine `converse(msg, wait_for_response=false)` with other tools in one turn for zero dead air
6. **Long input** — Set `disable_silence_detection=true` and `listen_duration_max=120` when user needs to speak at length

## Configuration

Config file: `~/.voicemode/voicemode.env`

### ElevenLabs Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ELEVENLABS_API_KEY` | (none) | API key — required |
| `VOICEMODE_ELEVENLABS_TTS_MODEL` | `eleven_v3` | TTS model |
| `VOICEMODE_ELEVENLABS_TTS_VOICE` | `k4hP4cQadSZQc0Oar2Ld` | Voice ID (Donna) |
| `VOICEMODE_ELEVENLABS_STT_MODEL` | `scribe_v2_realtime` | STT model |
| `VOICEMODE_ELEVENLABS_REALTIME_STT` | `true` | Use realtime streaming STT |

## Architecture

- **Server**: Single HTTP MCP server on `http://127.0.0.1:8765/mcp`
- **Auto-start**: Managed by launchd (macOS)
- **TTS**: ElevenLabs eleven_v3 with `convert()` + `play()` via ffplay
- **STT**: ElevenLabs Scribe v2 Realtime (WebSocket streaming) with batch fallback
- **Audio I/O**: Direct mic/speaker access on the host machine
