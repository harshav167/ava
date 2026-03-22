---
description: Start a voice conversation with the user
argument-hint: [message]
---

# /converse

Have a voice conversation using the `converse` tool from the `voicemode` MCP server.

**Tool name**: `converse` (from the voicemode MCP server)
- In Claude Code: `voicemode:converse` or `mcp__voicemode__converse`
- In Factory Droid: `mcp__voicemode__converse` or `voicemode___converse`

## Usage

Call the converse tool with your message:

```
converse(message="Your message here")
```

This speaks the message via ElevenLabs TTS, then listens for the user's response and transcribes it with ElevenLabs Scribe v2 Realtime.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak to the user |
| `wait_for_response` | `true` | Listen after speaking. Set `false` for announcements. |
| `speed` | `1.2` | Speech rate (0.7-1.2). 1.2 is the fastest ElevenLabs allows. |
| `listen_duration_max` | `120` | Max seconds to listen |
| `listen_duration_min` | `3.0` | Min seconds before silence detection triggers |
| `disable_silence_detection` | `false` | Set `true` to record for full duration without auto-stopping |
| `vad_aggressiveness` | `1` | VAD strictness (0-3). Lower = more tolerant of pauses. |
| `metrics_level` | `summary` | Output detail: `minimal`, `summary`, or `verbose` |
| `wait_for_conch` | `false` | Queue behind another speaker if one is active |

## Common Patterns

### Speak and listen (default)
```
converse(message="What would you like to work on?")
```

### Announce without listening
```
converse(message="Searching now...", wait_for_response=false)
```

### Long instructions expected
```
converse(message="Go ahead, I'm listening.", listen_duration_min=5, disable_silence_detection=true)
```

### User keeps getting cut off
```
converse(message="Take your time.", listen_duration_min=10, vad_aggressiveness=0)
```

### Speak while doing work (parallel)
```
converse(message="Checking that now.", wait_for_response=false)
# Other tools run simultaneously
```

## When User Gets Cut Off

1. Increase `listen_duration_min` to 5-10
2. Lower `vad_aggressiveness` to 0
3. Or set `disable_silence_detection=true` with a reasonable `listen_duration_max`

## Conch (Multi-Agent)

Only one agent can use the mic at a time. If you get "User is currently speaking", set `wait_for_conch=true`.

## MCP Setup

```json
{
  "mcpServers": {
    "voicemode": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/harshav167/ava.git", "voicemode"]
    }
  }
}
```

Set `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`.
