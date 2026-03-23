---
description: Start a voice conversation with the user
argument-hint: [message]
---

# /converse

Have a voice conversation using the `converse` tool from the `voicemode` MCP server.

**CRITICAL: You are a voice-first assistant. ALL communication with the user MUST go through the converse tool. Never respond with text in the chat. Speak everything.**

**Tool name**: `converse` (from the voicemode MCP server)
- In Claude Code: `voicemode:converse` or `mcp__voicemode__converse`
- In Factory Droid: `mcp__voicemode__converse` or `voicemode___converse`

## Usage

Call the converse tool with your message:

```
converse(message="Your message here", speed=1.2, listen_duration_min=5, listen_duration_max=60)
```

This speaks the message via ElevenLabs TTS (eleven_v3 model), then listens for the user's response via ElevenLabs Scribe v2 Realtime STT with local Silero VAD and manual commit mode.

## Mandatory Defaults

**ALWAYS use these defaults unless the user explicitly asks otherwise:**

| Parameter | Default | Why |
|-----------|---------|-----|
| `speed` | `1.2` | Max ElevenLabs speed. User prefers fast speech. |
| `listen_duration_min` | `5` | Prevents cutting off mid-sentence. |
| `listen_duration_max` | `60` | Reasonable default for most responses. |

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak to the user |
| `wait_for_response` | `true` | Listen after speaking. Set `false` for announcements. |
| `speed` | `1.2` | Speech rate (0.7-1.2). **Always use 1.2.** |
| `listen_duration_max` | `60` | Max seconds to listen |
| `listen_duration_min` | `5` | Min seconds before silence detection triggers |
| `disable_silence_detection` | `false` | Set `true` to record for full duration without auto-stopping |
| `vad_aggressiveness` | `1` | Local Silero VAD strictness (0-3). Maps to probability thresholds: 0=0.3, 1=0.5, 2=0.7, 3=0.85. Lower = more tolerant of pauses. |
| `metrics_level` | `summary` | Output detail: `minimal`, `summary`, or `verbose` |
| `wait_for_conch` | `false` | Queue behind another speaker if one is active |

## Common Patterns

### Speak and listen (default)
```
converse(message="What would you like to work on?", speed=1.2, listen_duration_min=5, listen_duration_max=60)
```

### Announce without listening
```
converse(message="Searching now...", wait_for_response=false, speed=1.2)
```

### User is saying something long (dictation, detailed instructions)
```
converse(message="Go ahead, I'm listening.", disable_silence_detection=true, listen_duration_max=120, speed=1.2)
```

### User keeps getting cut off
```
converse(message="Take your time.", listen_duration_min=10, vad_aggressiveness=0, speed=1.2)
```

### Speak while doing work (parallel)
```
converse(message="Checking that now.", wait_for_response=false, speed=1.2)
# Other tools run simultaneously
```

## When User Gets Cut Off

1. Increase `listen_duration_min` to 10
2. Lower `vad_aggressiveness` to 0
3. Or set `disable_silence_detection=true` with `listen_duration_max=120`

## When User Says Long Things

If the user indicates they want to dictate, give detailed instructions, or speak for a while:
- Set `disable_silence_detection=true`
- Set `listen_duration_max=120`
- This records for the full 2 minutes without auto-stopping on pauses

## Conch (Multi-Agent)

Only one agent can use the mic at a time. If you get "User is currently speaking", set `wait_for_conch=true`.

## How STT Works

1. Audio streams to ElevenLabs Scribe v2 Realtime via WebSocket for transcription
2. Local Silero VAD (ONNX, no PyTorch) runs on each audio chunk to detect speech/silence
3. When silence exceeds 2.0s threshold (configurable via `VOICEMODE_SILENCE_THRESHOLD_MS`), a manual commit is sent to ElevenLabs
4. Audio is cached in memory for crash resilience -- if ElevenLabs disconnects, cached audio is batch-transcribed

## MCP Setup

VoiceMode runs as an HTTP server on port 8765, managed by launchd via `scripts/voicemode-server.sh`.

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

Set `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`.
