# Always-On Voice Detection Research ("Jarvis Mode")

## Summary

**Recommended approach**: Standalone Python daemon with Silero VAD + Claude Code CLI bridge.

Claude Code hooks/skills CANNOT run continuously or submit prompts. The CLI (`claude -p`) CAN be invoked programmatically from any external process. This is the only viable path.

## Why Hooks Don't Work

- Hooks are reactive (respond to events), not proactive (initiate events)
- No UserPromptInject or SendMessage capability exists
- Hooks can inject additionalContext and block/allow actions, but cannot submit prompts
- The /loop skill has 1-minute minimum interval — useless for real-time audio

## Architecture

```
Always Running (launchd daemon)

[Microphone] --> [VAD Daemon (Python)]
                     |
                     | sounddevice captures audio
                     | Silero VAD detects speech (local, free, ~5ms)
                     | Short audio clip sent to ElevenLabs Scribe
                     | Checks transcription for wake word
                     |
                Wake word detected ("Hey Jarvis")
                     |
                     v
          [claude -p "/converse" --permission-mode auto]
                     |
                     | Claude Code starts, calls VoiceMode converse tool
                     | TTS speaks, STT listens, conversation loop
                     |
                Session ends
                     |
                     v
          [VAD Daemon resumes listening]
```

## Wake Word Detection Strategy (Cost-Optimized)

1. Silero VAD detects voice activity (free, local, ~5ms per chunk)
2. Only when speech detected, capture 2-3 seconds of audio
3. Run local keyword detector (Porcupine by Picovoice) OR send short clip to ElevenLabs Scribe
4. Check transcription for wake phrases
5. On match, invoke claude -p with /converse

## Osaurus VAD Reference

Osaurus uses Silero VAD via FluidAudio (ML-based, not WebRTC signal processing):
- VAD threshold: 0.55-0.85 probability (vs WebRTC binary yes/no)
- Silence to end: 0.3-0.8 seconds (vs our 2.0s)
- Chunk size: 256ms (vs WebRTC 30ms)
- Always-on singleton with wake word detection
- Auto-restart on failure (5 attempts)
- Debounce (3s cooldown between detections)

## Next Steps

1. Implement voice_mode/jarvis_daemon.py with Silero VAD
2. Create launchd plist for always-on operation
3. Test with Claude Code CLI integration
4. Add to VoiceMode as voicemode jarvis start/stop CLI command
