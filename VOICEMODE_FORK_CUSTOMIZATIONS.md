# VoiceMode fork customizations and upstream sync assessment

## 1. Executive summary

- **Compared fork:** `harshav167/ava` `main` at `949ebe9a09c42c57b3cbb1979a0c8280727993cc`.
- **Compared upstream:** `https://github.com/mbailey/voicemode` default branch `master` at `6afff773266229b27a89960ccb4dfe0a03837b5e`. Upstream has no `refs/heads/main` at comparison time, so this document uses `upstream/master` as upstream current mainline.
- **Git ancestry status:** no graph merge-base exists between this fork and upstream. The fork appears to have been created by deleting upstream `.git` and reinitializing history; @VOICEMODE_CUSTOMIZATION.md records that process.
- **Direct ahead/behind:** `101` local-only commits / `1723` upstream-only commits by graph, but this is **not semantically useful** because histories are unrelated.
- **Likely upstream base:** `7e0b0faaf91d80f2a9b0730c487fd25e967dfe09` (`2026-03-20`, `Merge branch 'cora/fix-star-notification-multiline-bio'`) is the best inferred base. The fork root `58ec79c7413584772a9bea8e71e62a02b9af9bf4` was committed the next day and differs from that upstream tree by 77 files, mostly initial ElevenLabs/plugin customization. Exact base cannot be proven from Git history alone.
- **Current tree divergence:** `upstream/master..HEAD` changes `361` files: `164` added in the fork, `83` deleted from the fork, `114` modified, with `38,742` insertions and `22,427` deletions.
- **Sync risk:** **high**. The fork replaces upstream's provider model, runtime defaults, plugin metadata, distribution shape, Connect code, tests, and parts of the MCP/server lifecycle. Upstream has since added clone/mlx-audio, provider-aware STT model selection, tmux auto-focus, `sayas`, and other changes in the same files the fork rewrote.
- **Recommendation:** do **not** wholesale merge or rebase upstream into `main`. Treat the fork as a policy fork and sync upstream via a staged, topic-by-topic patch/cherry-pick workflow. Preserve fork-owned decisions first: ElevenLabs-only default, no local-provider fallback unless explicitly reintroduced, no plugin hooks/beeps, HTTP server on `127.0.0.1:8765/mcp`, voice-first `/converse` behavior, and `wait_for_conch=true` default.

## 2. Comparison baseline

| Item | Value |
|---|---|
| Local repository | `harshav167/ava` at `/home/ava` |
| Local ref/SHA | `main` / `949ebe9a09c42c57b3cbb1979a0c8280727993cc` |
| Upstream repository | `https://github.com/mbailey/voicemode` |
| Upstream ref/SHA | `upstream/master` / `6afff773266229b27a89960ccb4dfe0a03837b5e` |
| Upstream `main` | Not present; upstream default is `master` |
| Direct merge-base | None; histories are unrelated |
| Fork root commit | `58ec79c7413584772a9bea8e71e62a02b9af9bf4` (`Initial commit: VoiceMode (ava) with ElevenLabs integration`) |
| Likely upstream base | `7e0b0faaf91d80f2a9b0730c487fd25e967dfe09`, inferred from timestamp/tree similarity, not graph ancestry |
| Direct graph ahead/behind | `101` ahead / `1723` behind, invalid as a normal fork metric because no merge-base |
| Inferred-base upstream delta | `92` upstream commits after `7e0b0fa` |
| Inferred-base fork delta | `101` local commits from reinitialized root to current HEAD |
| Current tree diff | `361` files, `38,742` insertions, `22,427` deletions versus `upstream/master` |

Methodology used: added/fetched an `upstream` remote, discovered upstream default branch, checked shallow state, unshallowed local history, attempted `merge-base`/`fork-point`, compared direct and inferred-base commit logs, generated `diff --name-status`, `diff --stat`, `diff --shortstat`, inspected representative files by functional area, and reviewed upstream-only commits after the inferred base.

## 3. Fork-specific features/customizations

### ElevenLabs-only TTS/STT provider policy

The fork's main customization is a provider-policy inversion from upstream's OpenAI-compatible/local-provider architecture to an ElevenLabs-centered voice stack.

- Added ElevenLabs adapters and direct provider boundary:
  - @voice_mode/elevenlabs_client.py
  - @voice_mode/elevenlabs_tts_stt.py
  - @voice_mode/elevenlabs_realtime_stt.py
  - @voice_mode/voice_provider.py
  - @voice_mode/voice_transcriber.py
- @voice_mode/provider_discovery.py is reduced to an ElevenLabs-oriented registry with `elevenlabs://tts` and `elevenlabs://stt` endpoint handling, instead of upstream's broader OpenAI/Kokoro/Whisper/mlx-audio detection.
- @voice_mode/runtime_context.py and @voice_mode/config.py default TTS to ElevenLabs `eleven_v3`, default voice ID `k4hP4cQadSZQc0Oar2Ld`, default STT to `scribe_v2_realtime`, and expose ElevenLabs voice tuning settings.
- @pyproject.toml adds `elevenlabs`, `onnxruntime`, `soundfile`, and Darwin `pyobjc-framework-Quartz`; it removes upstream's `openai` dependency and LiveKit/CoreML optional dependency groups.
- Upstream's current `@voice_mode/simple_failover.py`, `@voice_mode/streaming.py`, `@voice_mode/openai_error_parser.py`, local service installers, and clone/mlx-audio provider files are absent from the fork.
- The fork keeps some compatibility stubs and aliases (`WHISPER_*`, `KOKORO_*`, `WHISPER_LANGUAGE`) so old imports do not crash, but they are not intended as active providers.

Sync concern: very high. Upstream's recent VM-1100/VM-1106 work adds provider-aware STT model selection and mlx-audio local-provider detection in the exact files the fork simplified.

### Realtime Scribe v2 STT, Silero VAD, stop policy, fallback/recovery

- @voice_mode/elevenlabs_realtime_stt.py implements ElevenLabs Scribe v2 Realtime over WebSocket using manual commit mode. It waits for `SESSION_STARTED` before mic streaming, sends base64 PCM chunks, sets language to English unless explicitly configured, uses `previous_text` on the first chunk, and sends periodic commits for long recordings.
- @voice_mode/silero_vad.py adds an ONNX Runtime Silero VAD wrapper and a shared `StopPolicy` object. Realtime thresholds are mapped by VAD aggressiveness (`0 -> 4s`, `1 -> 3s`, `2 -> 2s`, `3 -> 1s`) while local recording keeps a probability-threshold mapping.
- @voice_mode/voice_transcriber.py centralizes realtime retry, local recording fallback, no-speech normalization, and STT result normalization.
- Audio cache/recovery behavior is in @voice_mode/elevenlabs_realtime_stt.py: raw/WAV cache files under `~/.voicemode/cache/last_recording.*`, batch `scribe_v2` fallback when realtime fails or appears truncated, and metadata showing fallback reason.
- The fork added @voice_mode/artifacts.py for STT upload/archive handling and uses compressed remote uploads while keeping saved WAVs when configured.

Sync concern: high. The current implementation is fork-specific and not upstream's provider model. Existing docs such as @TECH_DEBT_RECONCILIATION.md also admit recovery is not yet a formal state machine, so future syncs should not assume the "speech is never lost" behavior is complete in all failure paths.

### Converse/session behavior, conch, defaults, voice-first docs

- @voice_mode/tools/converse.py now presents the MCP tool as an ElevenLabs voice conversation tool. It validates ElevenLabs speed range `0.7-1.2`, defaults long listen/timeout values to `300s`, defaults `listen_duration_min=5s`, and defaults `wait_for_conch=true`.
- `task=True` is explicitly disabled for FastMCP background tasks because the fork hit client connection failures with task/Docket behavior.
- @voice_mode/converse_session.py creates a deeper session boundary for speak/listen turns, TTS timing, STT timing, event logging, audio feedback, and final result formatting.
- @voice_mode/conch.py is retained/modified for single-speaker coordination through a lock file, stale-lock detection, and queued waiting.
- The fork added `converse-cowork` docs for MCP clients with hard 60-second tool timeouts: speak first (`wait_for_response=false`), then listen separately with `skip_tts=true`.
- Voice-first behavior is documented across @commands/converse.md, @commands/converse-cowork.md, @skills/voicemode/SKILL.md, @AGENTS_PROPOSAL.md, and @VOICEMODE_CUSTOMIZATION.md.

Sync concern: high. Upstream later added tmux auto-focus after conch acquisition and its own cancellation fix. The fork has separate cancellation/disconnect watcher behavior, so these should be ported manually rather than blindly merged.

### HTTP server, launchd lifecycle, FastMCP v3

- The fork moved plugin/client setup toward a persistent local HTTP MCP endpoint: `http://127.0.0.1:8765/mcp` in @mcp.json and @.mcp.json.
- @scripts/voicemode-server.sh is fork-only and manages a macOS launchd service with `uv run --directory <repo> voicemode serve`, health checks, logs, port cleanup, `ThrottleInterval`, `ExitTimeOut`, `PYTHONUNBUFFERED`, and file descriptor limits.
- @pyproject.toml pins/moves to `fastmcp[tasks]>=3.0.0`, while upstream current remains on `fastmcp>=2.3.2,<3`.
- @voice_mode/server.py uses a runtime context object and a Connect-aware lifespan; @voice_mode/cli.py runs `mcp.http_app(...)` with Streamable HTTP in stateless mode and access/auth middleware.

Sync concern: high. Upstream changes around FastMCP 2.x, stdio-first assumptions, or tool registration can conflict with the fork's FastMCP v3/HTTP-first assumptions.

### Plugin/distribution assets for Claude, Cursor, Factory, commands, skills, metadata

- Fork-specific plugin manifests:
  - @.claude-plugin/plugin.json
  - @.cursor-plugin/plugin.json
  - @.factory-plugin/plugin.json
- Fork-specific host/project configs:
  - @mcp.json
  - @.mcp.json
  - @.cursor/mcp.json
  - @.factory/mcp.json
  - @server.json
- Fork-specific command and skill surfaces:
  - @commands/converse.md
  - @commands/converse-cowork.md
  - @commands/voicemode-status.md
  - @skills/voicemode/SKILL.md
  - @skills/voicemode-dj/SKILL.md
  - @skills/voicemode-connect/SKILL.md
  - @skills/restart/SKILL.md
  - @skills/verify/SKILL.md
- @.github/workflows/bump-plugin-version.yml is fork-only and automatically bumps plugin/server metadata patch versions when plugin files, commands, skills, or MCP configs change.
- Plugin manifests are currently at `10.0.1`, while package code @voice_mode/__version__.py remains `8.5.1`. Upstream current is package `8.6.1` and Claude plugin `8.6.1p0`.
- The fork intentionally clears plugin `hooks` in @.claude-plugin/plugin.json. Upstream current keeps soundfont hook entries in the Claude plugin.

Sync concern: high. Metadata is both functionally important and stale in places: @server.json still advertises OpenAI/Whisper/local-provider environment variables, @.claude-plugin/marketplace.json still points homepage to upstream, and plugin/package version streams have diverged.

### DJ/background music, audio ducking, sound fonts/hooks

- Core DJ/mpv support appears largely inherited from upstream and is mostly identical in current tree; @voice_mode/dj/controller.py, player/model/chapter surfaces are not major fork deltas.
- Fork-specific changes include:
  - @voice_mode/audio_ducker.py: macOS media-key based pausing/resuming of Spotify/Apple Music during TTS/STT.
  - @skills/voicemode-dj/SKILL.md: agent-facing DJ usage guidance.
  - minor @voice_mode/dj/library.py and @voice_mode/dj/mfp.py changes.
- The fork removed default soundfont MP3 assets from @voice_mode/data/soundfonts/default while leaving directory/package placeholders and hook receiver code.
- Plugin hooks are intentionally empty in @.claude-plugin/plugin.json, matching the "no beeps/no soundfonts" preference recorded in @VOICEMODE_CUSTOMIZATION.md.

Sync concern: medium. Upstream's soundfont/hook work and default MP3 assets conflict with the fork preference. DJ core bug fixes are safer than hook/plugin changes.

### Connect/auth/session and remote voice modules

- The fork retains a modular local Connect implementation under @voice_mode/connect/ plus @voice_mode/connect_registry.py and @voice_mode/tools/connect_status.py.
- @voice_mode/auth.py implements OAuth PKCE and credential storage for `voicemode.dev`.
- @voice_mode/connect/session.py adds a service boundary for Connect status/presence output.
- Upstream current removed the legacy Connect package, Connect hook scripts, and connect-status tests after VM-958 while retaining/restoring Connect auth CLI pieces.

Sync concern: very high. The fork and upstream have opposite directions here: the fork retains/refactors local Connect filesystem/WebSocket behavior; upstream removed much of it. A partial merge would likely leave broken imports, stale hooks, or duplicated auth/status behavior.

### Tests and coverage implications

- Fork changed the test surface substantially: against the likely base it has `127` added, `59` deleted, and `119` modified files; current fork-vs-upstream has `25` fork-only test files, `38` upstream-only missing test files, and `32` modified test files.
- Fork-added tests cover mocked ElevenLabs TTS/STT, realtime STT, TTS stability/error handling, voice provider/transcriber boundaries, converse session/critical path, audio artifacts/resources, and older Connect behavior.
- Fork removed or changed tests that assumed upstream provider failover, local Whisper/Kokoro services, old speed ranges, old tool sets, and old FastMCP internals.
- @.github/workflows/test.yml now sets `ELEVENLABS_API_KEY`, ignores manual and DJ tests, stops on first failure, and no longer emits coverage in the same way upstream did.
- Upstream-only tests now cover clone profiles, `sayas`, mlx-audio install, provider-aware STT config/model selection, auto-focus tmux pane, and upstream selective tool loading expectations.

Sync concern: high. Test failures after upstream sync are likely to be real policy conflicts, not just stale assertions. Provider, plugin, Connect, and clone/mlx tests need explicit adoption/rejection decisions.

## 4. Files changed relative to upstream

Status is relative to `upstream/master..HEAD`: `added` means present in the fork but absent upstream current; `deleted` means present upstream current but missing in the fork; `modified` means both trees have the path but contents diverge.

| Area | Key files | Status relative to upstream | Purpose | Sync concern |
|---|---|---|---|---|
| ElevenLabs provider stack | @voice_mode/elevenlabs_client.py, @voice_mode/elevenlabs_tts_stt.py, @voice_mode/elevenlabs_realtime_stt.py, @voice_mode/voice_provider.py, @voice_mode/voice_transcriber.py, @voice_mode/silero_vad.py | Added | ElevenLabs TTS/STT, realtime Scribe v2, Silero VAD, provider adapter, listening boundary | Very high; replaces upstream provider model |
| Upstream provider/local services absent from fork | @voice_mode/simple_failover.py, @voice_mode/streaming.py, @voice_mode/openai_error_parser.py, @voice_mode/tools/whisper/, @voice_mode/tools/kokoro/, @voice_mode/tools/mlx_audio/, @voice_mode/tools/clone/, @voice_mode/voice_profiles.py | Deleted | Upstream OpenAI-compatible failover, streaming playback, Whisper/Kokoro/mlx-audio/clone tooling | Very high; reintroducing these violates or changes ElevenLabs-only policy unless RFC-approved |
| Provider/runtime config | @voice_mode/config.py, @voice_mode/runtime_context.py, @voice_mode/provider_discovery.py, @voice_mode/providers.py, @pyproject.toml, @uv.lock | Modified/added/deleted mix | Runtime settings, provider endpoint selection, package deps, FastMCP v3, ElevenLabs defaults | Very high; same files changed heavily upstream for clone/mlx/STT model selection |
| Converse/session/orchestration | @voice_mode/tools/converse.py, @voice_mode/converse_session.py, @voice_mode/conch.py, @voice_mode/artifacts.py, @voice_mode/tts_orchestrator.py | Modified/added | Voice-first MCP tool, conch waiting, cancellation, TTS/STT orchestration, audio artifacts | Very high; upstream also changed converse for tmux focus/cancellation/provider features |
| HTTP/server lifecycle | @voice_mode/server.py, @voice_mode/serve_middleware.py, @voice_mode/cli.py, @scripts/voicemode-server.sh, @.mcp.json, @mcp.json | Modified/added | Persistent Streamable HTTP MCP server, launchd manager, middleware, local endpoint configs | High; upstream remains stdio/package oriented in several paths |
| Plugin/distribution | @.claude-plugin/plugin.json, @.claude-plugin/marketplace.json, @.cursor-plugin/plugin.json, @.factory-plugin/plugin.json, @server.json, @.github/workflows/bump-plugin-version.yml | Modified/added | Claude/Cursor/Factory plugin distribution, server registry metadata, automatic plugin version bump | High; versions, hooks, provider metadata, and repository URLs diverge |
| Commands/skills | @commands/, @skills/, @.claude/commands/, @.cursor/commands/, @.factory/ | Added/modified | Voice-first slash commands and agent skills for host integrations | Medium/high; docs encode fork policy and can be overwritten by upstream plugin docs |
| Connect/auth/session | @voice_mode/connect/, @voice_mode/connect_registry.py, @voice_mode/tools/connect_status.py, @voice_mode/auth.py, @voice_mode/data/hooks/check-notifications.* | Added/modified relative to upstream current | Local Connect WebSocket/presence/session behavior and legacy hook support | Very high; upstream current deleted most legacy Connect local modules/hooks |
| DJ/soundfonts/hooks | @voice_mode/audio_ducker.py, @skills/voicemode-dj/SKILL.md, @voice_mode/data/soundfonts/default/**, @voice_mode/tools/sound_fonts/, @voice_mode/dj/library.py, @voice_mode/dj/mfp.py | Added/deleted/modified | Media-app ducking, DJ docs, no-default-beep asset policy, small DJ tweaks | Medium; preserve no-hooks/no-beeps unless explicitly changed |
| Docs/research/agent assets | @VOICEMODE_CUSTOMIZATION.md, @TECH_DEBT_RECONCILIATION.md, @AGENTS_PROPOSAL.md, @ALWAYS_ON_VAD_RESEARCH.md, @LIVE_STEERING_RESEARCH.md, @FASTMCP_FEATURE_AUDIT.md, @.agents/ | Added | Decision logs, tech debt, research, external skills | Low/medium; useful fork knowledge, but noisy for upstream merges |
| Upstream docs missing locally | @llms.txt, @docs/guides/voice-cloning.md, upstream `.claude/skills/converse/SKILL.md` | Deleted relative to upstream | Upstream LLM summary and clone/converse docs | Medium; can be cherry-picked only if content matches fork policy |
| Tests/CI | @tests/test_elevenlabs_*.py, @tests/test_voice_provider.py, @tests/test_voice_transcriber.py, @tests/test_converse_session.py, @tests/test_clone_*.py, @tests/test_mlx_audio_install.py, @.github/workflows/test.yml | Added/deleted/modified mix | Fork ElevenLabs tests; upstream clone/mlx/provider tests missing; CI changed | High; test suite encodes architecture decisions |
| Generated/stray files | @=1.0.0, @2026-03-23-140633-command-messagespeech-to-textcommand-message.txt | Added | Appears accidental/generated, not product surface | Low for sync but should be cleaned up |

## 5. Upstream changes not yet in this fork

Because histories are unrelated, this list uses the inferred base `7e0b0fa..upstream/master` and current tree comparison.

| Upstream area | Representative upstream commits/files | Missing/partial in fork | Notes |
|---|---|---|---|
| Voice cloning / `sayas` | `3aaf395`, `97421f7`, `bd259b0`, `54b4e30`, `89028bd`, @voice_mode/voice_profiles.py, @voice_mode/tools/clone/, @voice_mode/data/completions/sayas.bash | Missing | Adds `sayas` CLI, clone profile CRUD, directory-based voice profiles, streaming clone TTS. Incompatible with strict ElevenLabs-only unless accepted as optional clone-provider work. |
| mlx-audio service productization | `a287f0e`, `f9e97d4`, `c95ff06`, `003055c`, `c1a10a1`, `659b75b`, `45a370b`, @voice_mode/tools/mlx_audio/, @voice_mode/data/patches/mlx_audio_server.patch, @voice_mode/templates/launchd/com.voicemode.mlx-audio.plist | Missing | Apple-Silicon mlx-audio installer/service and patch pipeline. High conflict with fork's removed local providers. |
| Clone defaults/config docs | `5efcad6`, `a25d670`, `a4c82d6`, @docs/guides/voice-cloning.md | Missing | Adds `VOICEMODE_CLONE_BASE_URL`, `VOICEMODE_CLONE_MODEL`, quant docs/defaults. Fork runtime defaults do not include these. |
| Provider-aware STT model selection | `9a70d81` through `caa4bf3`, @voice_mode/config.py, @voice_mode/providers.py, @voice_mode/provider_discovery.py, @tests/test_stt_config.py, @tests/test_stt_failover_wire_model.py | Missing/incompatible | Upstream resolves STT model per endpoint and treats mlx-audio as local. Fork hardcodes Scribe v2/Scribe realtime through ElevenLabs. |
| Opus/streaming playback fixes | `3faeadb`, `46dce9a`, `6ec1872`, `eee7f5c`, @voice_mode/streaming.py | Missing | Fork deleted upstream streaming playback and uses ElevenLabs `convert()` + `ffplay` chunks. Only relevant if streaming returns. |
| tmux auto-focus after conch | `72fbb9c`, `fc8e11f`, `7405b42`, `1f8329c`, `7a39d67`, `353261f`, @tests/test_auto_focus_pane.py | Missing | Could be useful but must be adapted to fork's @voice_mode/tools/converse.py and conch/session boundary. |
| Converse cancellation upstream fix | `db5d324` | Partially present through fork-specific cancellation/disconnect watcher | Same failure class, different implementation. Compare behavior before porting. |
| Connect cleanup/removal | `0ef60e8`, `88df00c`, `e017d6b`, `ecb678f`, @voice_mode/connect/ deleted upstream | Opposite direction | Fork retains Connect modules and hooks; upstream removed legacy local filesystem/inbox code and stale hook refs. Requires product decision. |
| Channel server removal/docs | `7228d28` through `33c6296` | Mostly not applicable | Upstream bundled then removed channel server. Fork already has different Connect/plugin direction. |
| LLM/docs additions | `5ca7829`, `57bfe78`, `9f4f571`, @llms.txt, upstream `.claude/skills/converse/SKILL.md` | Missing | Low-risk if rewritten to match ElevenLabs/HTTP/no-hooks fork policy. |
| Upstream tests | @tests/test_clone_cli.py, @tests/test_clone_profiles.py, @tests/test_mlx_audio_install.py, @tests/test_voice_profiles.py, @tests/test_sayas_cli.py, @tests/test_provider_discovery.py | Missing | Only port tests for features intentionally adopted. |
| Version/release metadata | `27e7313`, `d04d09c`, @voice_mode/__version__.py, upstream plugin/server metadata | Missing/stale | Fork package still says `8.5.1`; plugins/server say `10.0.1`; upstream package is `8.6.1`. |

Areas that are effectively identical or low-change: core DJ playback/controller modules are mostly the same; @voice_mode/templates/launchd/com.voicemode.serve.plist is unchanged; many static pronunciation/docs resources are not central to the fork delta.

## 6. Sync feasibility and conflict map

### High-conflict areas

| Conflict area | Why it conflicts | Default resolution policy |
|---|---|---|
| Git history | No merge-base; normal merge/rebase semantics are unavailable/misleading | Do not merge into `main` directly; use throwaway integration branches or curated cherry-picks |
| Provider architecture | Fork is ElevenLabs-only; upstream current is OpenAI-compatible plus Whisper/Kokoro/mlx-audio/clone | Fork wins unless a specific RFC accepts an optional provider |
| @voice_mode/config.py / @voice_mode/runtime_context.py | Fork rewrote env loading/defaults; upstream added clone/STT model vars | Preserve fork defaults; port individual config vars only when adopting their feature |
| @voice_mode/provider_discovery.py / @voice_mode/providers.py | Fork has ElevenLabs-only registry; upstream has provider detection/model routing | Fork wins for default paths; avoid reintroducing fallback silently |
| @voice_mode/tools/converse.py / @voice_mode/converse_session.py | Both sides changed cancellation, conch, metrics, provider calls, focus behavior | Manual three-way review; preserve fork voice-first and `wait_for_conch=true` behavior |
| @voice_mode/cli.py | Upstream added clone/`sayas`/mlx service surfaces; fork removed or hid local-provider surfaces and added HTTP/Connect differences | Port CLI commands only for adopted features; avoid orphan commands |
| Connect modules/hooks | Fork retains local Connect modules; upstream removed them | Decide one Connect direction before syncing this area |
| Plugin manifests/server metadata | Fork has Claude/Cursor/Factory plugin version `10.0.1`, no hooks, HTTP configs; upstream has Claude plugin hooks and package-tied versions | Fork plugin policy wins; clean stale metadata separately |
| Tests | Test suites encode different provider/product assumptions | Keep fork-specific tests; port upstream tests only with adopted code |
| Packaging/dependencies | FastMCP v3/ElevenLabs/onnxruntime vs upstream FastMCP 2/OpenAI/local providers | Fork dependency policy wins until deliberate migration |

### Safer-to-sync areas

- Documentation fixes that do not mention provider defaults, local services, or plugin hooks.
- Isolated bug fixes in auth, changelog/release notes, utility formatting, or docs resources after checking imports against the fork.
- DJ core fixes in files not locally modified, especially @voice_mode/dj/controller.py, @voice_mode/dj/player.py, @voice_mode/dj/models.py, and @voice_mode/dj/chapters.py.
- Upstream tmux auto-focus can be considered a contained feature, but only if manually adapted to the fork's conch/session flow.
- `llms.txt` can be imported only after rewriting provider, install, and plugin claims to match this fork.

### Stale docs/metadata/provider references to reconcile

- @server.json still advertises `OPENAI_API_KEY`, `VOICEMODE_PREFER_LOCAL`, and `VOICEMODE_WHISPER_MODEL` despite the fork's ElevenLabs-only policy.
- @server.json and @.claude-plugin/marketplace.json still point repository/homepage fields at upstream in places; decide whether that is intentional for lineage or should point at `harshav167/ava`.
- @voice_mode/__version__.py is `8.5.1` while plugin manifests and @server.json are `10.0.1`; upstream current is `8.6.1`.
- @voice_mode/converse_session.py writes saved-transcription metadata with `"stt_model": "whisper-1"`.
- @voice_mode/cli_commands/status.py still reports `"stt_model": "whisper-1"` in at least one status path.
- @voice_mode/runtime_context.py default config comments still mention OpenAI and old VAD defaults (`VAD_AGGRESSIVENESS=3`, `SILENCE_THRESHOLD_MS=1000`, `MIN_RECORDING_DURATION=0.5`) that do not match active fork defaults.
- @voice_mode/config.py comments and aliases still mention OpenAI/Kokoro/Whisper in several compatibility paths.
- @README.md, @CHANGELOG.md, and plugin docs should be checked for mixed upstream/fork claims before any upstream sync is released.

## 7. Recommended upstream sync workflow

1. **Treat this as a policy fork, not a normal GitHub fork.** The lack of merge-base makes merge/rebase risky and noisy. Do upstream sync work in a separate integration branch or temporary worktree, never directly on `main`.
2. **Record fork-owned invariants before syncing:** ElevenLabs default/provider policy, HTTP MCP endpoint, no plugin hooks/beeps, `wait_for_conch=true`, long listen defaults, FastMCP v3 assumptions, launchd server workflow, and current Connect direction.
3. **Use curated cherry-picks or manual ports instead of wholesale merging.** Start from topical upstream ranges after the inferred base `7e0b0fa`, and port one feature/fix family at a time.
4. **Prioritize low-conflict upstream fixes first:** docs that can be rewritten to fork policy, isolated auth/release-note fixes, DJ core fixes, and possibly tmux auto-focus after manual adaptation.
5. **Treat provider/clone/mlx changes as RFCs, not routine sync.** Upstream clone/mlx-audio work is substantial and would reverse part of the fork's ElevenLabs-only stance unless introduced as optional, disabled-by-default functionality.
6. **Conflict-resolution policy:**
   - Provider architecture: fork wins unless an explicit decision says otherwise. Do not silently restore OpenAI/Kokoro/Whisper/mlx failover.
   - Docs/plugin metadata: fork's HTTP/no-hooks/ElevenLabs wording wins. Remove stale upstream local-provider metadata during resolution.
   - Tests: keep tests that assert fork behavior; port upstream tests only for adopted upstream features; delete/replace tests whose assumptions are intentionally rejected.
   - Connect: choose either fork legacy Connect or upstream removal before resolving files. Avoid mixed Connect state.
7. **Consider a one-time history normalization separately.** If long-term upstream tracking matters, create a new branch based on the inferred upstream base and replay the fork as a patch stack. This is higher effort but would make future `merge-base`/ahead/behind meaningful. Until then, maintain a curated patch stack and note cherry-picked upstream SHAs in commit messages.

## 8. Follow-up cleanup/RFC candidates

- **Version/metadata cleanup:** align @voice_mode/__version__.py, plugin manifests, @server.json, and installer metadata, or document intentionally separate package/plugin version streams.
- **Provider reference cleanup:** remove or clearly mark stale OpenAI/Whisper/Kokoro/provider-local references in @server.json, @voice_mode/runtime_context.py, @voice_mode/config.py, @voice_mode/converse_session.py, docs, and status output.
- **Clone/mlx RFC:** decide whether upstream clone voices/`sayas`/mlx-audio should be rejected, ported as optional non-default features, or moved to a separate extension.
- **Connect direction RFC:** decide whether to keep the fork's local Connect modules/hooks or follow upstream's removal/refactor. Then delete stale code/tests/docs from the losing direction.
- **TTS playback stabilization:** formalize one TTS playback subsystem around ElevenLabs v3 chunking, `ffplay` process ownership, cancellation, timeout semantics, and audible-success criteria.
- **STT recovery state machine:** turn realtime/cache/batch fallback into explicit states with deterministic recovery behavior and logs.
- **VAD truth document:** document which VAD path is active for realtime and local fallback, and make runtime defaults match docs/templates.
- **Plugin policy cleanup:** ensure Claude/Cursor/Factory manifests, commands, skills, and marketplace/server metadata all agree on no hooks/no beeps, HTTP endpoint, ElevenLabs requirements, and repository ownership.
- **Test suite reconciliation:** remove stale provider tests, add coverage for the fork's critical ElevenLabs/VAD/conch/HTTP paths, and decide whether coverage reporting should be restored in CI metadata.
- **Remove accidental/generated files:** review @=1.0.0 and @2026-03-23-140633-command-messagespeech-to-textcommand-message.txt; they look like local/generated artifacts rather than maintainable source.
- **History marker:** if maintainers accept `7e0b0fa` as the likely base, record that in repository metadata or release notes so future upstream sync work has a stable baseline despite the missing graph merge-base.
