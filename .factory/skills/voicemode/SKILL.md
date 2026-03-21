---
name: voicemode
description: |
  Voice interaction for Droid. Provides natural voice conversations using speech-to-text and text-to-speech.
  Use when users mention voice mode, speak, talk, converse, voice status, or voice troubleshooting.
  Supports ElevenLabs (default), Whisper, Kokoro, and OpenAI providers.
---

# VoiceMode for Factory Droid

Natural voice conversations with Droid using speech-to-text (STT) and text-to-speech (TTS).

## Setup

### 1. Install VoiceMode

```bash
uvx voice-mode-install --yes
```

### 2. Configure MCP Server

Add to your Droid MCP configuration (`~/.factory/mcp.json` or project `.factory/mcp.json`):

```json
{
  "mcpServers": {
    "voicemode": {
      "command": "uvx",
      "args": ["voice-mode"],
      "env": {
        "ELEVENLABS_API_KEY": "your-elevenlabs-api-key"
      }
    }
  }
}
```

### 3. Configure ElevenLabs (Recommended)

Set your ElevenLabs API key for high-quality TTS and STT:

```bash
# In ~/.voicemode/voicemode.env
ELEVENLABS_API_KEY=your-key-here
```

When set, ElevenLabs becomes the default provider with:
- **TTS**: `eleven_flash_v2_5` (~75ms latency)
- **STT**: Scribe v2 Realtime (streaming, ~150ms latency)
- **Fallback**: Whisper/Kokoro (local) or OpenAI (cloud)

## Usage

Use the `converse` MCP tool:

```python
# Speak and listen for response
voicemode:converse("Hello! What would you like to work on?")

# Speak without waiting (narration while working)
voicemode:converse("Searching the codebase now...", wait_for_response=False)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak |
| `wait_for_response` | true | Listen after speaking |
| `voice` | auto | TTS voice |

## Best Practices

1. **Narrate without waiting** - Use `wait_for_response=False` when announcing actions
2. **One question at a time** - Don't bundle multiple questions
3. **Parallel calls** - Combine `converse(msg, wait_for_response=False)` with other tools in one turn for zero dead air
4. **Let VoiceMode auto-select** - Don't hardcode providers unless user has preference

## Service Management

```bash
voicemode service status            # All services
voicemode service start whisper     # Start Whisper STT
voicemode service start kokoro      # Start Kokoro TTS
voicemode service logs whisper      # View logs
```

| Service | Port | Purpose |
|---------|------|---------|
| whisper | 2022 | Local speech-to-text |
| kokoro | 8880 | Local text-to-speech |
| voicemode | 8765 | HTTP/SSE server |

## Configuration

```bash
voicemode config list                           # Show all settings
voicemode config set VOICEMODE_TTS_VOICE nova   # Set default voice
voicemode config edit                           # Edit config file
```

Config file: `~/.voicemode/voicemode.env`

### ElevenLabs Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ELEVENLABS_API_KEY` | (none) | API key - enables ElevenLabs as primary provider |
| `VOICEMODE_ELEVENLABS_TTS_MODEL` | `eleven_flash_v2_5` | TTS model |
| `VOICEMODE_ELEVENLABS_TTS_VOICE` | `k4hP4cQadSZQc0Oar2Ld` | Voice ID |
| `VOICEMODE_ELEVENLABS_STT_MODEL` | `scribe_v2_realtime` | STT model |
| `VOICEMODE_ELEVENLABS_REALTIME_STT` | `true` | Use realtime streaming STT |

## DJ Mode

Background music during voice sessions:

```bash
voicemode dj play /path/to/music.mp3  # Play a file or URL
voicemode dj status                    # What's playing
voicemode dj stop                      # Stop playback
```
