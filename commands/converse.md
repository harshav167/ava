---
description: Start a voice conversation with the user
argument-hint: [message]
---

# /converse

Have a voice conversation with the user using the `voicemode:converse` MCP tool.

## How It Works

The converse tool speaks a message via ElevenLabs TTS, then listens for the user's response via microphone and transcribes it with ElevenLabs Scribe v2.

## Default Behavior

```python
voicemode:converse("Your message here")
```

This speaks the message, then listens for up to 120 seconds. Silence detection (VAD) automatically stops recording after 1 second of quiet.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | required | Text to speak to the user |
| `wait_for_response` | `true` | Whether to listen after speaking. Set `false` for announcements/narration. |
| `listen_duration_max` | `120` | Maximum seconds to listen before stopping |
| `listen_duration_min` | `2.0` | Minimum seconds before silence detection can trigger. Increase if user gets cut off. |
| `disable_silence_detection` | `false` | Set `true` to record for the full `listen_duration_max` without auto-stopping. |
| `vad_aggressiveness` | `3` | Voice Activity Detection strictness (0-3). 3 = most strict (stops quickly on silence). Lower values = more tolerant of pauses. |
| `wait_for_conch` | `false` | If another agent is already speaking, `false` returns immediately. `true` waits until the other agent finishes, then speaks. |

## Common Patterns

### Speak and listen (default)
```python
voicemode:converse("What would you like to work on?")
```

### Announce without listening (narration)
```python
voicemode:converse("Searching the codebase now...", wait_for_response=false)
```

### Long response expected (user gives detailed instructions)
```python
voicemode:converse("Go ahead, I'm listening.", listen_duration_max=120, listen_duration_min=5, disable_silence_detection=true)
```

### User keeps getting cut off (increase min duration)
```python
voicemode:converse("Take your time.", listen_duration_min=10, vad_aggressiveness=1)
```

### Parallel: speak while doing work
```python
# These run simultaneously - no dead air
voicemode:converse("Checking that now.", wait_for_response=false)
bash("git status")
```

### Queue behind another speaker
```python
voicemode:converse("My turn to speak.", wait_for_conch=true)
```

## Silence Detection

By default, the tool uses WebRTC VAD (Voice Activity Detection) to automatically stop recording when the user stops speaking.

- **VAD aggressiveness 3** (default): Stops after ~1 second of silence. Good for quick responses.
- **VAD aggressiveness 0**: Very tolerant of pauses. Good for users who think while speaking.
- **disable_silence_detection=true**: Records for the full `listen_duration_max`. Use when the user needs to give long instructions.

## When the User Gets Cut Off

If the user reports being cut off mid-sentence:
1. Increase `listen_duration_min` to 5-10 seconds
2. Lower `vad_aggressiveness` to 1 or 2
3. Or set `disable_silence_detection=true` with a reasonable `listen_duration_max`

## Conch (Multi-Agent)

Only one agent can use the microphone at a time. The "conch" is a lock that prevents overlapping conversations.

- If you get "User is currently speaking with converse", set `wait_for_conch=true` to queue.
- Don't spam retries - either wait for conch or move on.

## MCP Setup

If MCP is not connected, ensure it's configured:

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

And `ELEVENLABS_API_KEY` is set in `~/.voicemode/voicemode.env`.
