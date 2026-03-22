# FastMCP Feature Audit — VoiceMode vs Available Features

## Status Key
- **NOT IMPLEMENTED** — Feature exists in FastMCP, not used in VoiceMode
- **PARTIALLY IMPLEMENTED** — Some usage but not following best practices
- **IMPLEMENTED** — Fully used and working

---

## 1. FileSystem Provider
**Status: NOT IMPLEMENTED**

FastMCP has `FileSystemProvider` that auto-discovers `@tool`, `@resource`, `@prompt` decorated functions from a directory. VoiceMode currently uses manual imports via `tools/__init__.py` which auto-imports all `.py` files in the tools directory — similar concept but not using the FastMCP provider.

**Action**: Migrate to `FileSystemProvider` with `reload=True` for development. This would give us hot-reload on tool changes without restarting the server.

**Priority**: HIGH — solves the auto-reload problem we've been fighting with uvicorn.

---

## 2. Background Tasks
**Status: NOT IMPLEMENTED**

FastMCP has `task=True` decorator for long-running operations with progress tracking. The converse tool is exactly this — TTS generation + recording + STT can take 30-120 seconds. Currently it blocks the HTTP request the entire time.

**Action**: Add `task=True` to the converse tool. This would let clients get an immediate task ID, then poll for progress/results. The user would hear TTS immediately while the STT happens in the background.

**Priority**: HIGH — would prevent the HTTP timeouts we've been hitting.

---

## 3. Composing Servers (mount)
**Status: NOT IMPLEMENTED**

FastMCP supports mounting multiple servers together with namespacing. VoiceMode has everything in one server. Could split into: voice server, DJ server, connect server.

**Action**: Consider splitting voice_mode/server.py into separate mounted servers for voice, DJ, and connect.

**Priority**: LOW — works fine as monolith for now.

---

## 4. User Elicitation
**Status: NOT IMPLEMENTED**

FastMCP has `ctx.elicit()` for requesting structured input from users during tool execution. VoiceMode does this via voice (converse tool with wait_for_response), but could also use elicitation for non-voice interactions (e.g., config setup, service selection).

**Action**: Add elicitation to the service management tool for confirming destructive actions.

**Priority**: MEDIUM — nice for interactive setup flows.

---

## 5. Lifespans (Composable)
**Status: PARTIALLY IMPLEMENTED**

VoiceMode uses `@asynccontextmanager` for its lifespan in server.py. FastMCP 3.0 has composable `@lifespan` decorator with `|` operator for combining multiple lifespans.

Currently the lifespan handles FFmpeg checks and logging setup. Should also handle ElevenLabs client initialization and cleanup.

**Action**: Migrate to FastMCP `@lifespan` decorator, add ElevenLabs client initialization.

**Priority**: MEDIUM — current approach works but isn't composable.

---

## 6. Client Logging (ctx.debug/info/warning/error)
**Status: NOT IMPLEMENTED**

FastMCP provides `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()` for sending log messages to the MCP client. VoiceMode uses Python's `logging` module which only logs server-side. The client never sees these logs.

**Action**: Add `Context` parameter to converse tool and other tools. Use `ctx.info()` for status updates that the client should see (e.g., "Connecting to ElevenLabs...", "Recording started", "Transcribing...").

**Priority**: HIGH — would give users visibility into what's happening during voice calls.

---

## 7. Pagination
**Status: NOT IMPLEMENTED**

FastMCP supports `list_page_size` for paginating large tool/resource/prompt lists. VoiceMode has ~20 components, so pagination isn't critical, but it's good practice.

**Action**: Not needed right now. Consider if component count grows.

**Priority**: LOW

---

## 8. Progress Reporting
**Status: NOT IMPLEMENTED**

FastMCP has `ctx.report_progress(progress, total)` for updating clients on long-running operations. The converse tool is a perfect candidate — could report progress during TTS generation, recording, and STT.

**Action**: Add progress reporting to converse tool:
- 0%: Starting TTS
- 25%: TTS complete, playing audio
- 50%: Audio played, starting recording
- 75%: Recording complete, transcribing
- 100%: Transcription complete

**Priority**: HIGH — would give clients visibility into the voice pipeline.

---

## 9. Storage Backends
**Status: NOT IMPLEMENTED**

FastMCP has pluggable storage backends (memory, file, Redis) for caching and OAuth state. VoiceMode doesn't use any caching or state persistence beyond config files.

**Action**: Could use file storage for caching TTS audio (avoid re-generating the same message). Could also cache STT results for retry on failure.

**Priority**: MEDIUM — the STT caching would solve the "lost speech" problem.

---

## 10. OpenTelemetry
**Status: NOT IMPLEMENTED**

FastMCP has native OpenTelemetry instrumentation for distributed tracing. Every tool call, resource read, and prompt render creates spans automatically.

**Action**: Enable by installing `opentelemetry-distro` and running with `opentelemetry-instrument`. Zero code changes needed — FastMCP handles it.

**Priority**: LOW — useful for debugging but not critical.

---

## 11. Testing (FastMCP Client)
**Status: NOT IMPLEMENTED (for new code)**

FastMCP provides a `Client` class for testing servers directly without network overhead. VoiceMode has tests but they mock everything. Could test ElevenLabs integration paths using FastMCP Client.

**Action**: Add integration tests using `Client(mcp)` pattern for the voice pipeline.

**Priority**: MEDIUM

---

## 12. Prompts (Modern API)
**Status: PARTIALLY IMPLEMENTED**

VoiceMode has prompts in `voice_mode/prompts/` using `@mcp.prompt()`. But they don't use FastMCP 3.0 features like `Message`, `PromptResult`, metadata, or argument types.

**Action**: Update prompts to use `Message` and `PromptResult` for richer responses.

**Priority**: LOW

---

## 13. MCP Context (ctx)
**Status: NOT IMPLEMENTED**

None of VoiceMode's tools accept a `Context` parameter. This means they can't:
- Log to clients
- Report progress
- Access session state
- Read other resources
- Elicit user input
- Access request metadata

**Action**: Add `ctx: Context` to converse tool and service tool as first step.

**Priority**: CRITICAL — this is the foundation for features 6, 8, 4.

---

## 14. Prompts as Tools
**Status: NOT IMPLEMENTED**

FastMCP can expose prompts as tools for clients that don't support the prompt protocol. Since Factory Droid may not fully support prompts, this transform could make our prompts accessible.

**Action**: Add `PromptsAsTools` transform.

**Priority**: LOW

---

## 15. Skills Provider
**Status: NOT IMPLEMENTED**

FastMCP has `SkillsDirectoryProvider` that exposes skill directories (like `.claude/skills/`) as MCP resources. VoiceMode has skills in `.claude/skills/` and `.factory/skills/` but they're only read by the plugin system, not exposed as MCP resources.

**Action**: Add `SkillsDirectoryProvider` to expose our skills via MCP. Could enable cross-tool skill sharing.

**Priority**: LOW

---

## Implementation Priority Order

### Phase 1 (Critical — Unblocks Everything)
1. **Add Context to tools** — foundation for logging, progress, elicitation
2. **Client Logging** — `ctx.info()` for user-visible status updates
3. **Progress Reporting** — `ctx.report_progress()` in converse tool

### Phase 2 (High — Production Quality)
4. **Background Tasks** — `task=True` on converse to prevent HTTP timeouts
5. **FileSystem Provider** — auto-reload on code changes
6. **Storage Backend** — file cache for STT resilience (never lose speech)

### Phase 3 (Medium — Polish)
7. **Composable Lifespans** — proper startup/shutdown with ElevenLabs client
8. **User Elicitation** — interactive setup flows
9. **Testing with FastMCP Client** — integration tests

### Phase 4 (Low — Nice to Have)
10. **OpenTelemetry** — distributed tracing
11. **Skills Provider** — cross-tool skill sharing
12. **Prompts as Tools** — Droid compatibility
13. **Pagination** — if component count grows
14. **Composing Servers** — if codebase grows large
15. **Modern Prompt API** — Message/PromptResult
