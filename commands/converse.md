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
- In Claude Desktop: `converse` (under voicemode MCP server)

## Usage

Call the converse tool with your message. Use these MANDATORY defaults:

```
converse(message="Your message here", speed=1.2, listen_duration_min=5, listen_duration_max=300, timeout=300)
```

## CRITICAL — Timeout Must Match Listen Duration

Both `listen_duration_max` and `timeout` are in **SECONDS**. The `timeout` controls when the MCP call itself times out. If `timeout` is less than `listen_duration_max`, the call will time out while the user is still speaking.

**RULE: timeout MUST always be >= listen_duration_max. Default both to 300 (5 minutes).**

Bad (will timeout while user speaks):
```
converse(message="...", listen_duration_max=300, timeout=60)  // WRONG — times out at 60s
```

Good:
```
converse(message="...", listen_duration_max=300, timeout=300)  // Correct — both 5 min
```

## Why listen_duration_min Exists

`listen_duration_min` prevents the VAD from cutting off the user too early. Even if the VAD detects silence, it won't stop recording until this minimum has passed. This protects against:
- The user taking a breath before speaking
- Background noise being misinterpreted as silence
- The user pausing to think before responding

**Default: 5 seconds.** Increase to 10+ if the user reports getting cut off.

## Mandatory Defaults

**ALWAYS use these defaults unless the user explicitly asks otherwise:**

| Parameter | Default | Unit | Why |
|-----------|---------|------|-----|
| `speed` | `1.2` | — | Max ElevenLabs speed. User prefers fast speech. |
| `listen_duration_min` | `5` | seconds | Prevents cutting off mid-sentence. |
| `listen_duration_max` | `300` | seconds | 5 minutes. Enough for most responses. |
| `timeout` | `300` | seconds | MUST match listen_duration_max. |

## Parameters

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `message` | required | — | Text to speak to the user |
| `wait_for_response` | `true` | — | Listen after speaking. Set `false` for announcements. |
| `speed` | `1.2` | — | Speech rate (0.7-1.2). **Always use 1.2.** |
| `listen_duration_max` | `300` | seconds | Max time to listen (5 min default) |
| `listen_duration_min` | `5` | seconds | Min time before silence detection triggers |
| `timeout` | `300` | seconds | MCP call timeout. **MUST be >= listen_duration_max** |
| `disable_silence_detection` | `false` | — | Set `true` to record for full duration without auto-stopping |
| `vad_aggressiveness` | `1` | 0-3 | Silence detection strictness. Lower = more tolerant of pauses. |
| `metrics_level` | `summary` | — | Output detail: `minimal`, `summary`, or `verbose` |
| `wait_for_conch` | `false` | — | Queue behind another speaker if one is active |

## Common Patterns

### Speak and listen (default)
```
converse(message="What would you like to work on?", speed=1.2)
```

### Announce without listening
```
converse(message="Searching now...", wait_for_response=false, speed=1.2)
```

### Long instructions expected
```
converse(message="Go ahead, I'm listening.", disable_silence_detection=true, listen_duration_max=300, timeout=300, speed=1.2)
```

### User keeps getting cut off
```
converse(message="Take your time.", listen_duration_min=10, vad_aggressiveness=0, speed=1.2)
```

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
