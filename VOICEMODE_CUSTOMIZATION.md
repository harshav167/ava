# VoiceMode Customization Log

Complete record of all decisions, changes, and conversations from the initial fork through v1 completion.

## Origin

- **Source repo**: VoiceMode by Mike Bailey (voice-mode on PyPI)
- **Forked to**: https://github.com/harshav167/ava
- **Date**: 2026-03-21 (Sydney time)
- **Purpose**: Customize VoiceMode to use ElevenLabs exclusively for both TTS and STT, removing all Whisper/Kokoro/OpenAI dependencies. Set up as both a Claude Code plugin and Factory Droid plugin.

## Step-by-Step History

### 1. Initial Setup

**Action**: Deleted `.git` from the upstream VoiceMode repo, created fresh repo `harshav167/ava`, pushed all code.

```bash
rm -rf .git
git init && git add -A && git commit -m "Initial commit"
gh repo create harshav167/ava --public --source=. --push
```

### 2. ElevenLabs Skills Loaded

Loaded two Claude Code skills for reference:
- `/speech-to-text` — ElevenLabs Scribe v2 / Scribe v2 Realtime documentation
- `/text-to-speech` — ElevenLabs TTS models, streaming, voice settings

### 3. Codebase Analysis

Analyzed the existing VoiceMode architecture:

**Original flow**:
```
Mic → record_audio_with_silence_detection() → numpy array
  → prepare_audio_for_stt() → compressed file (mp3/wav)
  → simple_stt_failover() → AsyncOpenAI.audio.transcriptions.create()
  → text

Text → simple_tts_failover() → AsyncOpenAI.audio.speech.create()
  → audio bytes → NonBlockingAudioPlayer → speaker
```

**Key files identified**:
- `voice_mode/config.py` — env vars, provider URLs, defaults
- `voice_mode/provider_discovery.py` — multi-provider detection (Kokoro on :8880, Whisper on :2022, OpenAI)
- `voice_mode/providers.py` — voice selection, client creation
- `voice_mode/simple_failover.py` — TTS/STT failover chain
- `voice_mode/core.py` — OpenAI client setup, TTS playback
- `voice_mode/tools/converse.py` — main MCP tool, recording, VAD

### 4. ElevenLabs Integration (First Attempt — BROKEN)

**What was done**:
- Added `elevenlabs>=1.0.0` to `pyproject.toml`
- Created `voice_mode/elevenlabs_client.py` — TTS streaming + batch STT wrapper
- Created `voice_mode/elevenlabs_realtime_stt.py` — WebSocket realtime STT
- Added ElevenLabs config vars to `config.py`
- Modified `provider_discovery.py` to detect `"elevenlabs"` provider type
- Modified `simple_failover.py` to add ElevenLabs TTS/STT branches
- Modified `tools/converse.py` to integrate realtime STT path

**User preferences collected**:
- API Key: stored in `~/.voicemode/voicemode.env`
- Voice ID: `k4hP4cQadSZQc0Oar2Ld` (Donna — a cloned voice)
- TTS Model: `eleven_flash_v2_5` initially
- STT Model: `scribe_v2_realtime`
- Strategy: ElevenLabs replaces Whisper/Kokoro as default

### 5. First TTS Test — WAR SOUNDS

**Problem**: Audio sounded like a warzone / walkie-talkie from Afghanistan.

**Root cause**: I was doing hacky PCM conversion. Used `output_format="pcm_24000"`, received raw signed 16-bit PCM, tried to convert with `np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0` and play through `NonBlockingAudioPlayer`. This was fundamentally wrong.

**User feedback**: "Why are you doing hacks regarding int16 and float32? I've never seen any of this code in any of my projects using ElevenLabs. If the existing project is doing whatever you're saying, it means it's from the old code where you need to remove it and use the proper ElevenLabs way of doing it."

**Lesson**: Never hack around the SDK. Use the SDK's built-in playback functions.

### 6. Context7 SDK Research

Used Context7 to look up the actual ElevenLabs Python SDK documentation. Found:

```python
from elevenlabs.client import ElevenLabs
from elevenlabs import stream

client = ElevenLabs(api_key="...")
audio_stream = client.text_to_speech.stream(
    text="Hello",
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model_id="eleven_multilingual_v2"
)
stream(audio_stream)  # Built-in playback via mpv
```

The SDK has a built-in `stream()` function that pipes audio to `mpv`. No PCM conversion, no numpy, no float32. Just `stream(audio_stream)`.

### 7. Second TTS Attempt — Used SDK stream()

**What was done**: Replaced all the PCM hack code with:
```python
from elevenlabs import stream as elevenlabs_play
audio_stream = el_client.text_to_speech.stream(text=text, voice_id=el_voice, model_id=model)
elevenlabs_play(audio_stream)
```

**Result**: Audio worked but voice was inconsistent. Different voice every call.

### 8. Voice Inconsistency Investigation

**Problem**: Voice sounded different every time the converse tool was called.

**Investigation**:
- Confirmed voice ID `k4hP4cQadSZQc0Oar2Ld` maps to "Donna" (cloned voice)
- Tested all three models with Donna:
  - `eleven_flash_v2_5` — sounded different from the real Donna
  - `eleven_multilingual_v2` — sounded OK
  - `eleven_v3` — sounded best, closest to the original cloned voice

**User decision**: "Use V3. V3 is the default. Don't fuck around with anything else."

### 9. eleven_v3 + stream() — WAR SOUNDS AGAIN

**Problem**: `eleven_v3` model caused distorted audio when using `stream()`.

**Root cause discovered by reading SDK source** (`elevenlabs-python/src/elevenlabs/play.py`):
- `stream()` function (line 69) pipes chunks to `mpv --no-cache`
- `play()` function (line 13) collects ALL bytes first, then plays via `ffplay`
- ElevenLabs docs: "WebSockets are unavailable for `eleven_v3`"
- The `stream()` function's chunk-by-chunk piping doesn't work reliably with v3

**Fix**: Switch from `stream()` to `convert()` + `play()`:
```python
from elevenlabs.play import play as elevenlabs_play
audio_iterator = el_client.text_to_speech.convert(
    text=text, voice_id=el_voice, model_id="eleven_v3",
    output_format="mp3_44100_128",
    voice_settings=VoiceSettings(speed=1.2),
)
elevenlabs_play(audio_iterator)
```

**Additional import fix**: `from elevenlabs import play` imports the MODULE, not the function. Must use `from elevenlabs.play import play`.

### 10. Speed Parameter

**ElevenLabs speed range**: 0.7 to 1.2 (NOT 0.25-4.0 like OpenAI)
- First attempt: speed=1.5 → API error "expected 0.7-1.2"
- Set default to 1.2 (max allowed)
- User: "One point two is pretty good"

### 11. Hooks Removal

**Problem**: VoiceMode had "soundfont" hooks that played beeping tones on every tool call (PreToolUse, PostToolUse, Notification, Stop, PreCompact). User described it as "Morse code" / "I was doing like Morse code."

**Fix**:
- Emptied `hooks` array in `.claude-plugin/plugin.json`
- Cleared `.claude/settings.json` to `{"hooks": {}}`

**User preference**: No hooks, no beeping, no soundfonts. Only converse mode.

### 12. Provider Cleanup — ElevenLabs Only

**User demand**: "Remove OpenAI, Kokoro and Whisper. There should be zero failover. I will always have ElevenLabs working."

**Changes made**:
- `provider_discovery.py` — simplified to only detect "elevenlabs", `is_local_provider()` always returns False
- `simple_failover.py` — removed all loop/failover logic, direct ElevenLabs calls only
- `config.py` — removed local Kokoro/Whisper URLs from defaults, OpenAI only included if key present
- `providers.py` — all voice routing returns ElevenLabs
- Renamed `simple_failover.py` → `elevenlabs_tts_stt.py` (no failover concept)

### 13. OpenAI API Key Fallback

**Problem**: When ElevenLabs TTS failed, it fell through to OpenAI which had no API key, causing `"The api_key client option must be set"` error.

**Fix**: Only include OpenAI in URL lists when `OPENAI_API_KEY` is set. When `ELEVENLABS_API_KEY` is set, URL lists are `["elevenlabs://tts"]` and `["elevenlabs://stt"]` only.

### 14. Factory Droid Plugin Setup

**Cloned reference repos**:
```bash
git clone https://github.com/Factory-AI/factory.git ~/Developer/factory
git clone https://github.com/Factory-AI/factory-plugins.git ~/Developer/factory-plugins
```

**Studied working Factory plugin structure** (droid-evolved, security-engineer, core):
```
plugin-root/
├── .factory-plugin/plugin.json    ← manifest
├── commands/                       ← slash commands
│   └── converse.md
├── skills/                         ← auto-triggered skills
│   └── voicemode/SKILL.md
└── mcp.json                        ← MCP server config
```

**Key learning**: Factory plugins need `skills/` and `commands/` at the REPO ROOT, not nested inside `.factory/`. Initially put them in `.factory/skills/` which didn't work.

**Created**:
- `.factory-plugin/plugin.json` — plugin manifest
- `skills/voicemode/SKILL.md` — Factory voice skill
- `skills/voicemode-connect/SKILL.md` — Factory remote voice skill
- `commands/converse.md` — `/converse` slash command
- `commands/status.md` — `/status` slash command
- `mcp.json` — Factory MCP config (uvx with git URL)

### 15. Claude Code Plugin Setup

**Structure** (already existed, updated):
```
.claude-plugin/plugin.json          ← manifest (hooks removed, mcp added)
.claude/commands/converse.md        ← /converse command
.claude/commands/install.md         ← /install command
.claude/commands/status.md          ← /status command
.claude/skills/voicemode/SKILL.md   ← voice skill
.mcp.json                           ← MCP config
```

**Changes to plugin.json**:
- Removed all 11 hook references
- Added `"mcp": "./.mcp.json"` for MCP auto-detection
- Updated author to Harsha

### 16. MCP Config — uvx with git URL

**For plugin distribution** (both Claude and Factory):
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

**The `--refresh` flag**: Forces uvx to re-fetch from git on every start, busting the cache. Without it, uvx caches the installed version and code changes don't take effect.

**For local development**: `uv run voicemode` (runs from local checkout)

### 17. Converse Tool Description Update

**Problem**: The MCP tool description still referenced OpenAI, Kokoro, chimes, and incorrect parameter ranges. Droid saw `tts_provider ("openai"|"kokoro")` and got confused.

**Fix**: Rewrote the entire docstring in `tools/converse.py` to describe ElevenLabs-only behavior, correct speed range (0.7-1.2), correct VAD defaults, and removed all chime references.

### 18. Converse Command — Tool Name Fix

**Problem**: Command said `voicemode:converse` but Droid uses `mcp__voicemode__converse` format. AI couldn't find the tool.

**Fix**: Command now lists all tool name formats:
- Claude Code: `voicemode:converse` or `mcp__voicemode__converse`
- Factory Droid: `mcp__voicemode__converse` or `voicemode___converse`

### 19. Silence Detection / VAD Issues

**Problem**: User kept getting cut off mid-sentence. Default VAD was too aggressive.

**Changes to defaults in config.py**:
| Setting | Before | After | Reason |
|---------|--------|-------|--------|
| `VAD_AGGRESSIVENESS` | 3 | 1 | Less strict, tolerates pauses |
| `SILENCE_THRESHOLD_MS` | 1000 | 2000 | 2 seconds of silence before stop |
| `MIN_RECORDING_DURATION` | 0.5 | 3.0 | Don't cut off immediately |

**User feedback**: "Halfway when I'm speaking, it cut off" and "you need to run an interactive shell and figure out how to finalize the VAD... it's not working bro, it's fucked"

**Outstanding issue**: VAD still cuts off the user. Need interactive calibration tool (v2).

### 20. Realtime STT Rewrite

**Problem**: Original realtime STT module used wrong SDK patterns (class instantiation instead of dict, wrong event data access).

**Fix**: Read the actual SDK source at `elevenlabs-python/src/elevenlabs/realtime/`:
- `scribe.py` — `connect()` takes a dict (TypedDict), not keyword args
- `connection.py` — Event callbacks receive raw `data` dict, use `data.get("text")`
- Audio sent as `{"audio_base_64": base64_chunk}` via `connection.send()`
- `CommitStrategy.VAD` for server-side silence detection

Rewrote `elevenlabs_realtime_stt.py` from scratch using these patterns.

### 21. Embedded Git Repos

**Problem**: Cloned `elevenlabs-python/` and `examples/` into the repo for reference. They were committed as git submodules which broke `uvx` installs.

**Fix**: `git rm --cached` both directories, added to `.gitignore`.

### 22. STT Service Connection Failed

**Problem**: After long recording sessions, STT returns `"STT service connection failed"` and the user's entire speech is lost.

**User feedback**: "If there's an error, STT service died, my entire five minutes of speaking is lost. That is one of the biggest pain points. I should never have a situation where the server fails and I have to speak again."

**Proposed fix (v2)**: Write audio to a cache file during recording. If STT fails, retry from the cached file. Only delete the cache after successful transcription.

## Current Configuration (v1 Final)

### ElevenLabs Settings
| Setting | Value |
|---------|-------|
| API Key | In `~/.voicemode/voicemode.env` |
| Voice ID | `k4hP4cQadSZQc0Oar2Ld` (Donna, cloned) |
| TTS Model | `eleven_v3` (best for cloned voices) |
| TTS Output Format | `mp3_44100_128` |
| TTS Playback | `convert()` + `play()` via ffplay |
| TTS Speed | 1.2x (max ElevenLabs allows) |
| STT Model | `scribe_v2_realtime` |
| STT Mode | Realtime WebSocket streaming with server-side VAD |
| STT Batch Fallback | `scribe_v2` via `speech_to_text.convert()` |

### VAD / Recording Settings
| Setting | Value |
|---------|-------|
| VAD Aggressiveness | 1 (tolerant of pauses) |
| Silence Threshold | 2000ms |
| Min Recording Duration | 3.0s |
| Max Recording Duration | 120s |

### User Preferences (Harsha)
- Speed: 1.2x always
- Voice: Donna (cloned voice, voice ID k4hP4cQadSZQc0Oar2Ld)
- Model: eleven_v3 only
- Communication: through /converse only, not chat text
- No hooks, no soundfonts, no beeping
- No OpenAI, no Whisper, no Kokoro — ElevenLabs only
- Direct and fast, fix issues immediately, don't ask unnecessary questions
- Read SDK docs (Context7) before implementing anything
- Test locally before deploying to MCP

## v2 Roadmap

1. **HTTP remote server mode** — `voicemode serve` on port 8765, all clients connect over HTTP instead of each spawning uvx
2. **Fix VAD / silence detection** — interactive calibration tool to tune parameters for user's mic/environment
3. **Audio cache for STT resilience** — write recording to cache file, retry STT on failure, never lose user's speech
4. **ElevenLabs Conversational AI** — real-time duplex WebSocket for barge-in (interrupting AI mid-sentence). Research completed:
   - Claude is natively supported as LLM (no custom server needed)
   - Single WebSocket handles ASR + LLM + TTS + turn-taking
   - Barge-in works via proprietary turn-taking model
   - Python SDK: `Conversation` class with `DefaultAudioInterface`
   - Will be a new tool `realtime-converse`, separate from existing `converse`
5. **Realtime STT optimization** — currently enabled but may have edge cases with connection drops

## File Changes Summary

### New Files Created
- `voice_mode/elevenlabs_client.py` — ElevenLabs SDK wrapper for batch STT
- `voice_mode/elevenlabs_tts_stt.py` — ElevenLabs TTS (convert+play) and STT (batch fallback)
- `voice_mode/elevenlabs_realtime_stt.py` — Realtime WebSocket STT with server-side VAD
- `.factory-plugin/plugin.json` — Factory Droid plugin manifest
- `skills/voicemode/SKILL.md` — Factory voice skill
- `skills/voicemode-connect/SKILL.md` — Factory remote voice skill
- `commands/converse.md` — Factory /converse command
- `commands/status.md` — Factory /status command
- `mcp.json` — Factory MCP config

### Files Modified
- `pyproject.toml` — added `elevenlabs>=1.0.0`
- `voice_mode/config.py` — ElevenLabs config vars, removed OpenAI/Kokoro/Whisper from defaults, VAD tuning
- `voice_mode/provider_discovery.py` — ElevenLabs-only provider detection
- `voice_mode/providers.py` — all voice routing returns ElevenLabs
- `voice_mode/tools/converse.py` — realtime STT integration, updated tool description
- `voice_mode/core.py` — updated import paths
- `.claude-plugin/plugin.json` — removed hooks, added MCP reference
- `.claude/settings.json` — cleared hooks
- `.claude/commands/converse.md` — full parameter documentation
- `.mcp.json` — uvx with git URL + --refresh flag
- `.gitignore` — added elevenlabs-python/ and examples/

### Files Deleted/Renamed
- `voice_mode/simple_failover.py` → renamed to `voice_mode/elevenlabs_tts_stt.py`

## Git Commits (chronological)

1. Initial commit: VoiceMode (ava) with ElevenLabs integration
2. Update MCP configs to use uvx with git+https://github.com/harshav167/ava.git
3. Remove OpenAI from fallback chain when no OPENAI_API_KEY is set
4. Fix DJDucker import - it's in tools/converse.py not config.py
5. Use ElevenLabs SDK built-in stream() for TTS playback
6. Remove all hooks from plugin, add MCP reference to plugin.json
7. Linter auto-fixes (ElevenLabs-only cleanup of config, provider_discovery, simple_failover)
8. ElevenLabs-only: remove local Kokoro/Whisper/OpenAI from default URLs
9. Fix Factory Droid plugin structure - skills/ at repo root
10. Add Factory Droid slash commands (converse, status)
11. Add commands/ at repo root for Factory Droid plugin discovery
12. Fix voice consistency + add mcp.json for Factory Droid
13. Rename simple_failover.py to elevenlabs_tts_stt.py
14. Add --refresh flag to uvx MCP configs
15. Tune defaults: VAD aggressiveness 1, silence 2s, min recording 3s, TTS speed 1.5x
16. Switch default TTS model to eleven_v3 for best cloned voice quality
17. Document converse command with all parameters, patterns
18. Fix TTS: use convert()+play() instead of stream() for eleven_v3 compatibility
19. Rewrite realtime STT using actual SDK patterns
20. Remove embedded git repos from tracking
21. Update converse tool description for ElevenLabs-only
22. Fix converse command: document actual tool names for both Claude and Droid
