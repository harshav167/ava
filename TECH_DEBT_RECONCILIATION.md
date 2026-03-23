# Tech Debt Reconciliation

## Purpose

This file consolidates the current technical debt, regressions, production-readiness gaps, and architectural cleanup work identified across the VoiceMode customization effort.

It is based on:
- the full customization/session history,
- `VOICEMODE_CUSTOMIZATION.md`,
- current repo state,
- the change range from `a0c0357d1e1d` to current HEAD,
- local FastMCP, ElevenLabs SDK, examples, mcporter, and Osaurus research,
- CodeRabbit review outputs.

The intent is to provide a single stabilization document before any further feature work.

---

## Project Goal

The actual goal is not “voice support” in the abstract.

The goal is a **Jarvis-like, blind-usable, voice-only AI system** where:
- the user does not need to read terminal output,
- the assistant always speaks back,
- the assistant never silently fails,
- user speech is never lost,
- interruptions, retries, and long-form speaking work reliably,
- multiple clients can talk to one persistent local HTTP MCP server.

That means the standard for quality is not “the tool works most of the time.”
The standard is:
- no silent TTS success,
- no dropped recordings,
- no random server death,
- no flaky VAD behavior,
- no manual operational hacks required to recover.

---

## Executive Summary

## What is done

- Repo was migrated from the upstream VoiceMode shape into `ava` / local customized VoiceMode.
- ElevenLabs replaced Whisper/Kokoro/OpenAI as the primary path.
- HTTP remote server mode was introduced on `http://127.0.0.1:8765/mcp`.
- Claude and Factory plugin structures were added.
- FastMCP was upgraded to `3.1.1`.
- A substantial amount of legacy provider code was deleted.
- Tests were added for ElevenLabs-specific paths.
- VAD research, Osaurus research, always-on research, and live steering research were documented.

## What is not done

- The system is **not yet production-ready**.
- There are still reliability issues in TTS, STT, launch/restart behavior, and release validation.
- FastMCP advanced features are still only partially adopted.
- The “speech is never lost” requirement is not fully guaranteed in all failure modes.
- The current VAD story is still split and conceptually inconsistent.

---

## High-Level Change Review Since `a0c0357d1e1d`

The codebase changed heavily after `a0c0357d1e1d`.

Broad categories of changes:
- ElevenLabs-only conversion
- provider abstraction cleanup
- HTTP remote server setup
- launchd/server management additions
- FastMCP v3 migration
- extensive docs and plugin/command/skill work
- test suite additions
- VAD/Silero experimentation
- repeated hotfixing for crashes, restart behavior, and TTS/STT failures

Net effect:
- The codebase is much closer to the intended architecture.
- But the repo also shows signs of **high-churn iterative patching under production pressure**, which created inconsistencies between implementation, docs, tests, and operational assumptions.

---

## Current Reality vs Intended Reality

## Intended reality

- one persistent local server,
- all clients connect over HTTP,
- stable TTS/STT pipeline,
- no lost user speech,
- robust handling for long speech and long replies,
- blind-safe operation,
- consistent client behavior.

## Current reality

- the architecture is mostly pointed in that direction,
- but the server still appears brittle under stress,
- restart behavior is still operationally awkward,
- TTS and STT error semantics are still not fully trustworthy,
- tests do not yet prove production safety,
- some recent fixes are still patch-like rather than final-form design.

---

## Core Technical Debt Areas

## 1. TTS Reliability Debt

### Current state

The TTS path has been revised several times:
- raw PCM conversion hack,
- SDK `stream()` use,
- `convert() + play()`,
- thread offloading,
- chunking,
- ffplay/sounddevice changes.

### Debt

- TTS implementation has changed shape repeatedly, which is a code smell.
- Some paths have historically reported success while producing no audible result.
- Long-message behavior has caused hangs or server death.
- The correct final playback strategy is still not fully locked down as an intentionally designed subsystem.

### Why this matters

For a blind/voice-only user, silent TTS failure is one of the worst possible failures.

### Required reconciliation

- define one canonical playback pipeline,
- define explicit success criteria for “message spoken successfully,”
- fail hard if no chunk was audibly played,
- add real timeout and cleanup semantics,
- add tests for long-form TTS and partial chunk failure,
- verify no child-process or audio-backend crash can kill the server.

---

## 2. STT Reliability Debt

### Current state

The repo has:
- realtime STT,
- retry behavior,
- batch fallback,
- cached-audio concepts,
- manual commit / previous-text logic.

### Debt

- the “speech is NEVER lost” guarantee is not fully true in all paths,
- some failure modes can degrade into `no_speech` instead of triggering proper recovery,
- some failures depend on subtle runtime behavior rather than a formal state machine,
- realtime and fallback semantics still feel stitched together.

### Why this matters

If a user speaks for minutes and the system drops the result, trust is destroyed.

### Required reconciliation

- formalize STT session states: connecting, ready, recording, committing, recovering, fallback, complete, failed,
- guarantee that all mic/send/commit failures preserve audio,
- guarantee batch fallback from cached audio for every recoverable failure,
- log exactly which failure path occurred,
- add end-to-end tests for speech preservation.

---

## 3. VAD Debt

### Current state

There are effectively multiple VAD stories in the repo/conversation history:
- local WebRTC VAD legacy,
- local Silero VAD work,
- ElevenLabs server-side VAD in realtime mode,
- manual tuning via thresholds/aggressiveness,
- user desire to replicate Osaurus behavior.

### Debt

- system behavior is not conceptually unified,
- user-facing expectations and actual active VAD path can differ,
- some improvements were applied to the wrong path relative to the current runtime path,
- the repo still lacks an authoritative document saying which VAD is actually used in each operating mode.

### Why this matters

This is one of the user’s primary non-negotiables: **do not cut me off**.

### Required reconciliation

- define exact VAD strategy per mode:
  - realtime mode,
  - local record + batch mode,
  - future always-on / wake-word mode,
- benchmark current behavior against Osaurus,
- standardize thresholds and defaults,
- add a calibration tool or calibration flow,
- document the active path clearly in commands/skills/docs.

---

## 4. Server Lifecycle / Ops Debt

### Current state

Server management has moved toward launchd and a script-based lifecycle.

### Debt

- launchd behavior and manual restarts have drifted,
- there have been restart loops, stale processes, and timing issues,
- service tooling and operational docs are not fully aligned,
- some restarts/recovery logic have relied on ad hoc process handling.

### Why this matters

For a persistent local voice server, lifecycle management is part of the product.

### Required reconciliation

- define one official runtime path,
- define one official restart path,
- ensure launchd and CLI health/status are consistent,
- prevent dual/manual/stale server collisions,
- add smoke tests for start, restart, and reconnect.

---

## 5. FastMCP Adoption Debt

### Current state

FastMCP is upgraded, but only the basics are truly in use.

### Implemented

- FastMCP server
- HTTP app / transport
- tools/resources/prompts
- some `Context` progress and info reporting

### Partial / missing

- background task strategy is not finalized,
- deeper lifecycle/service composition is weak,
- richer metadata and server composition patterns are missing,
- auth/session/stateless production features are largely unused,
- some FastMCP capabilities were researched but not integrated.

### Required reconciliation

- decide which FastMCP production features are actually worth adopting,
- implement only the ones that improve resilience or maintainability,
- avoid feature-chasing for its own sake.

---

## 6. Test Suite Debt

### Current state

The repo now has a real ElevenLabs-focused test suite, which is good.

### Debt

- some tests are stale relative to implementation,
- some tests still reflect removed provider assumptions,
- tests have not fully proven server stability under real operational conditions,
- release confidence is still weaker than the docs/claims imply.

### Why this matters

Production readiness cannot be asserted off mocked happy-path tests alone.

### Required reconciliation

- remove stale tests,
- align mocks with real implementation modules,
- add smoke tests for serve/restart/converse,
- add regression tests for long TTS, repeated calls, cached audio fallback, and failure recovery.

---

## 7. Documentation Drift Debt

### Current state

There is a lot of documentation, which is good.

### Debt

- some docs may overstate guarantees,
- some docs reflect intentions that current code still does not fully satisfy,
- operational and architectural truth is spread across many files.

### Required reconciliation

- keep `VOICEMODE_CUSTOMIZATION.md` as historical log,
- create one source-of-truth operational architecture doc,
- create one source-of-truth reliability contract doc,
- avoid claiming guarantees that are not enforced in code.

---

## What FastMCP Features Are Actually Implemented

## Implemented

- FastMCP 3.x core server
- HTTP transport
- tools/resources/prompts registration
- limited `Context` usage

## Partially implemented

- context/progress instrumentation
- lifecycle handling
- background-task experimentation

## Not meaningfully implemented yet

- deeper provider/composition patterns,
- production auth/session model,
- richer metadata-driven resource/prompt design,
- a stable long-running task model for `converse`.

So the answer is:

**No — the full set of FastMCP production/server features is not implemented.**
The repo is upgraded, but not fully reconciled to FastMCP best practices.

---

## What Is Implemented vs Not Implemented Around Live Steering / Always-On

## Implemented

- research only,
- documents for always-on VAD and live steering,
- partial exploration of Osaurus VAD ideas.

## Not implemented

- live steering in Osaurus,
- always-on wake word daemon,
- automatic foreground/interrupt control,
- 24/7 passive listening mode.

---

## Priority Order to Stabilize

## P0 — Must fix before calling this production-ready

1. TTS success semantics and crash-proof playback
2. STT guaranteed audio preservation on all recoverable failures
3. Unified VAD truth and no-cutoff tuning for the actual runtime path
4. Server lifecycle stability and one true operational path
5. Release gate tests that match reality

## P1 — Next after stability

1. FastMCP architectural cleanup
2. Context/progress consistency across tools
3. Documentation reconciliation and guarantee cleanup
4. Better client interoperability across Claude / Droid / Osaurus / mcporter

## P2 — Feature work after stabilization

1. always-on wake word
2. live steering / interruption
3. richer FastMCP capabilities
4. conversational/Jarvis UX enhancements

---

## Non-Negotiables Captured From User Intent

These are the actual requirements the system must be judged against:

- never silently fail,
- never lose long speech if STT errors,
- never require the user to read the screen,
- never rely on flaky transport/process hacks,
- never cut the user off mid-thought,
- always speak back consistently,
- be robust enough for blind-first interaction.

Any future implementation should be checked against these before merge.

---

## Suggested Next Reconciliation Pass

One focused stabilization pass should produce:

1. a formal TTS playback subsystem,
2. a formal STT recovery state machine,
3. one documented VAD strategy per mode,
4. one documented server lifecycle path,
5. one reliable release test suite.

Only after that should more major features be added.
