# AGENTS.md Proposal — Voice-First AI Instruction Set

## Problem

When an AI coding assistant (Claude Code, Factory Droid, Osaurus, or any MCP client) has access to the VoiceMode MCP server, it doesn't automatically know to use voice as its primary communication channel. The AI defaults to text output unless explicitly told otherwise — every single time.

We need a standardized instruction set that, when placed in CLAUDE.md / AGENTS.md / system prompt, makes the AI:
1. **Speak** all responses through the `converse` tool
2. **Listen** for the user's spoken response
3. **Never** output text to the chat
4. **Handle** voice-specific edge cases (silence detection, long input, parallel execution)

## The Jarvis Goal

The end goal is a Jarvis-like experience:
- User speaks → AI listens, processes, speaks back → loop
- No text, no terminal, no typing
- Works across Claude Code, Factory Droid, Osaurus, and any future MCP client
- Eventually: always-on wake word detection ("Hey Jarvis" → conversation starts)

## Proposed AGENTS.md / CLAUDE.md Instruction Set

The following should be placed in the project's `CLAUDE.md` (or `AGENTS.md` symlinked to it):

```markdown
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

\```
converse(
  message="Your message here",
  speed=1.2,                    # Max ElevenLabs speed
  listen_duration_min=5,        # Don't cut off mid-sentence
  listen_duration_max=60,       # Reasonable default
  wait_for_response=true        # Listen after speaking
)
\```

### For long user input:
\```
converse(
  message="Go ahead, I'm listening.",
  disable_silence_detection=true,
  listen_duration_max=120,
  speed=1.2
)
\```

### For announcements (no listening):
\```
converse(
  message="Working on that now.",
  wait_for_response=false,
  speed=1.2
)
\```

## HTTP Server Setup

VoiceMode runs as a single HTTP server on port 8765. All clients connect to the same endpoint.

### MCP Configuration

\```json
{
  "mcpServers": {
    "voicemode": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
\```

### Architecture

- **Server**: Single HTTP MCP server on `http://127.0.0.1:8765/mcp`
- **Auto-start**: Managed by launchd (macOS) — starts on login
- **TTS**: ElevenLabs eleven_v3 model with Donna voice
- **STT**: ElevenLabs Scribe v2 Realtime (WebSocket streaming with server-side VAD)
- **Audio I/O**: Direct mic/speaker access on the host machine
- **No external dependencies**: No Whisper, Kokoro, or OpenAI required

### Environment

Set `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`.

## Key Principles

1. **Voice-only communication**: The AI should NEVER respond with text. Always use `converse`.
2. **Speed 1.2**: Always set speed to 1.2 (max ElevenLabs allows).
3. **Don't cut off the user**: Use `listen_duration_min=5` minimum.
4. **Parallel execution**: Use `wait_for_response=false` + other tools in the same turn for zero dead air.
5. **One speaker at a time**: Use `wait_for_conch=true` if another agent is speaking.
```

## How This Works Across Clients

### Claude Code
- Place in `CLAUDE.md` at repo root (or symlink `AGENTS.md` → `CLAUDE.md`)
- Claude Code reads `CLAUDE.md` on every session start
- The instruction set is always in context

### Factory Droid
- Place in `.factory/AGENTS.md` or project root `AGENTS.md`
- Droid reads it on session start
- Same instruction set applies

### Osaurus
- Osaurus reads `AGENTS.md` from the project root
- Combined with Osaurus's native VAD (Silero), the AI gets:
  - Always-on wake word detection (from Osaurus)
  - Voice conversation via MCP (from VoiceMode)
  - The best of both worlds

### Any MCP Client
- The instruction set is in the CLAUDE.md/AGENTS.md which is standard
- The MCP server provides the voice tools
- Any client that reads project instructions + supports MCP gets voice

## Lessons Learned from This Session

### What Works
- `speed=1.2` — max ElevenLabs allows, user prefers fast speech
- `listen_duration_min=5` — prevents premature cutoff
- `disable_silence_detection=true` for long dictation
- `wait_for_response=false` + parallel tools for zero dead air
- Short TTS messages (under 2000 chars) — long ones need chunking
- Explicit "voice-only" instruction — without it, AI defaults to text

### What Doesn't Work
- `VAD aggressiveness 3` — too aggressive, cuts off mid-sentence
- `listen_duration_min=2` — too short, user gets cut off
- Auto-detect language — misidentifies accented English as other languages
- `stream()` function with eleven_v3 — use `convert()` + `play()` instead
- Synchronous `play()` in async context — blocks event loop, crashes server
- Long TTS without chunking — hangs the ElevenLabs API
- Repeat phrase detection — false positives from background audio

### What Needs Testing
- VAD aggressiveness 0 vs 1 — which is better for natural conversation
- Silence threshold 1.5s vs 2.0s — faster response vs fewer false stops
- ElevenLabs Conversational AI — duplex WebSocket with barge-in support
- Silero VAD integration — ML-based VAD vs WebRTC VAD

## Future: Always-On Wake Word Detection

The ideal Jarvis experience requires:

1. **Always-on listener** — a daemon that captures mic audio 24/7
2. **Wake word detection** — Silero VAD + ASR to detect "Hey Jarvis" or custom phrase
3. **Auto-trigger** — when wake word detected, automatically start a Claude Code converse session
4. **Seamless handoff** — from always-on listener to active conversation and back

This could be implemented as:
- A standalone Python daemon using Silero VAD (same as Osaurus uses)
- When wake word detected, run `claude --message "/converse"` via CLI
- Or use a Claude Code hook that runs on SessionStart to auto-activate voice mode
- Or integrate directly into the VoiceMode MCP server as a background service

Research is ongoing — see the always-on VAD research agent output.

## Testing the Instruction Set

To verify the instruction set works:

1. Start VoiceMode server: `voicemode serve`
2. Open Claude Code in a project with this AGENTS.md
3. Type anything — the AI should immediately use `converse` to speak
4. The AI should never output text to the chat
5. The AI should use the correct defaults (speed=1.2, etc.)

Test via mcporter:
```bash
MCPORTER_CALL_TIMEOUT=300000 mcporter call http://127.0.0.1:8765/mcp --allow-http converse message:"Hello" wait_for_response:true speed:1.2 listen_duration_min:5 listen_duration_max:60
```
