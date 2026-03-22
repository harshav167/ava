# Live Steering / Voice Interruption Research

> Research into implementing voice-triggered interruption of AI generation in Osaurus.
> The goal: say a wake word (e.g., "Donna") during generation to pause/stop/redirect the agent mid-output.

---

## 1. Current Osaurus Architecture

### 1.1 Generation Pipeline (Chat Mode)

**Entry point:** `ChatSession.send(_ text:)` in `ChatView.swift` (line 855)

The generation flow is:

1. User text is appended as a `ChatTurn(role: .user)`
2. A new `runId` (UUID) is created; `beginRun()` stores it as `activeRunId`
3. A `Task` is spawned and stored as `currentTask`
4. Inside the Task:
   - `isStreaming = true` is set
   - `ServerController.signalGenerationStart()` is called
   - A `ChatEngine.streamChat(request:)` call returns an `AsyncThrowingStream<String, Error>`
   - The stream is consumed in a `for try await delta in stream` loop (line 1056)
   - Deltas are fed to a `StreamingDeltaProcessor` for UI rendering
   - Tool calls are detected, executed, and looped (up to `maxToolAttempts`)
5. On completion or cancellation, `finalizeRun()` -> `completeRunCleanup()` runs

**Key state variables:**
- `ChatSession.isStreaming: Bool` -- published, drives UI
- `ChatSession.currentTask: Task<Void, Never>?` -- the running generation Task
- `ChatSession.activeRunId: UUID?` -- guards against stale runs

**File:** `/Users/harsha/Developer/voicemode/osaurus/Packages/OsaurusCore/Views/Chat/ChatView.swift`

### 1.2 Stop Button Mechanism

**UI:** `FloatingInputCard.swift` (line 1793) shows a `StopButton` when `isStreaming == true`.

**Stop action:** The `onStop` closure calls `session.stop()` (line 1411 in ChatView.swift).

**`ChatSession.stop()` implementation** (line 373):
```swift
func stop() {
    let task = currentTask
    task?.cancel()                    // 1. Cancel the Swift Task
    if let runId = activeRunId {
        finalizeRun(runId: runId, persistConversationArtifacts: false)  // 2. Clean up
    } else {
        completeRunCleanup()
    }
}
```

**`completeRunCleanup()`** (line 668):
```swift
private func completeRunCleanup() {
    currentTask = nil
    isStreaming = false
    ServerController.signalGenerationEnd()
    trimTrailingEmptyAssistantTurn()
    consolidateAssistantTurns()
    save()
}
```

**Cancellation propagation:** The `ChatEngine.wrapStreamWithLogging()` checks `Task.isCancelled` on every delta (line 161) and the `continuation.onTermination` handler cancels the producer task (line 241-252). So `task?.cancel()` cleanly terminates the stream.

**Summary:** Stopping generation is straightforward: cancel the Task, clean up state. It is already a single function call: `session.stop()`.

### 1.3 VAD Service (Wake Word Detection)

**File:** `/Users/harsha/Developer/voicemode/osaurus/Packages/OsaurusCore/Services/Voice/VADService.swift`

The VAD service:
- Runs **always-on** background listening via `SpeechService.startStreamingTranscription()`
- Observes `SpeechService.$currentTranscription` and `$confirmedTranscription`
- Passes accumulated text to `AgentNameDetector.detect(in:)`
- On detection, posts `Notification.Name.vadAgentDetected`
- Has a 3-second cooldown between detections

**Wake word detection** (`AgentNameDetector.swift`):
- Matches agent names with fuzzy Levenshtein distance matching
- Supports custom wake phrases
- Supports "hey/hi/hello/ok/yo" + agent name patterns
- Confidence scoring (0.7+ threshold)

**Critical lifecycle during chat:**
- When wake word detected: VAD calls `pause()` (stops transcription but keeps audio engine alive)
- AppDelegate receives `.vadAgentDetected`, opens/focuses chat window
- After chat window closes: `.chatViewClosed` notification triggers `VADService.resumeAfterChat()`

**Current limitation:** VAD is **paused** once chat opens and stays paused during the entire chat session (including generation). It only resumes after the chat view closes.

### 1.4 Continuous Voice Mode

**File:** `FloatingInputCard.swift` (line 362-377)

When `isContinuousVoiceMode` is true:
```swift
.onChange(of: isStreaming) { wasStreaming, nowStreaming in
    if wasStreaming && !nowStreaming && isContinuousVoiceMode {
        // AI finished responding, restart voice input
        startVoiceInput()
    }
}
```

This waits for streaming to **finish** before restarting voice input. It does NOT listen during generation.

### 1.5 Work Mode Interrupt (Existing Pattern)

**File:** `/Users/harsha/Developer/voicemode/osaurus/Packages/OsaurusCore/Services/WorkEngine.swift`

Work mode already has a full interrupt mechanism:
- `WorkEngine.interrupt()` -- sets `interruptRequested = true`
- `WorkEngine.redirect(message:)` -- interrupts + injects a new user message + resumes
- The execution loop checks `shouldInterrupt()` between tool calls
- On interrupt, the session is preserved and can be resumed

This is the closest analogue to "live steering" but it operates at the **tool execution boundary** (between tool calls in an agentic loop), not mid-stream token generation.

---

## 2. What "Live Steering" Requires

### 2.1 The Desired Flow

1. User says wake word ("Donna") while AI is generating
2. AI generation stops immediately
3. Voice input activates (user speaks new instruction)
4. New instruction is injected into the conversation
5. AI generates a new response incorporating the redirect

### 2.2 Technical Requirements

| Requirement | Difficulty | Notes |
|---|---|---|
| Detect wake word during generation | Medium | VAD is currently paused during chat. Need to keep it active. |
| Stop generation on detection | Easy | `session.stop()` already works perfectly. |
| Transition to voice input | Easy | `startVoiceInput()` already exists in FloatingInputCard. |
| Inject new user message after voice | Easy | `session.send(text)` handles this. |
| Avoid audio conflicts (TTS + STT) | Hard | If TTS is playing through VoiceMode MCP while STT is listening, feedback loops and conflicts arise. |

---

## 3. Proposed Implementation

### 3.1 Option A: VAD-During-Generation (Recommended)

**Concept:** Keep VAD listening (or a lightweight variant) active even during AI generation. On wake word detection, stop generation and switch to voice input.

**Changes required:**

#### A1. New Notification: `.vadInterruptDetected`

Add a new notification in VADService.swift (alongside existing ones at line 15-21):
```swift
public static let vadInterruptDetected = Notification.Name("vadInterruptDetected")
```

This is distinct from `.vadAgentDetected` because it carries different semantics (interrupt current generation vs. open new chat).

#### A2. VADService: Add "background monitoring" mode

Currently, VADService has two states regarding chat: fully active (listening, detecting) or paused. We need a third: "monitoring during generation."

**New method in VADService:**
```swift
/// Enter monitoring-during-generation mode.
/// Keeps listening for wake word but posts .vadInterruptDetected instead of .vadAgentDetected.
public func monitorDuringGeneration() async throws { ... }
```

This would:
1. Start (or continue) streaming transcription
2. On wake word detection, post `.vadInterruptDetected` instead of `.vadAgentDetected`
3. NOT pause itself -- just post the notification

**File:** `VADService.swift`

#### A3. ChatView / FloatingInputCard: Handle interrupt notification

In `FloatingInputCard.swift`, add a receiver:
```swift
.onReceive(NotificationCenter.default.publisher(for: .vadInterruptDetected)) { notification in
    guard isStreaming else { return }
    guard let targetWindowId = notification.object as? UUID, targetWindowId == windowId else { return }

    // 1. Stop generation
    onStop()

    // 2. Activate voice input
    isContinuousVoiceMode = true
    startVoiceInput()
}
```

**File:** `FloatingInputCard.swift`

#### A4. ChatSession: Observe VAD state to start/stop monitoring

When `isStreaming` transitions to true:
- If VAD mode is enabled, start `monitorDuringGeneration()`

When `isStreaming` transitions to false:
- If VAD was monitoring, stop monitoring

This could be done in `ChatView.swift` or `FloatingInputCard.swift` via `.onChange(of: isStreaming)`.

**Files:** `FloatingInputCard.swift` or `ChatView.swift`

#### A5. Audio Conflict Handling

If VoiceMode MCP is playing TTS audio while VAD is listening, the microphone could pick up the TTS output. Solutions:
1. Use `SpeechService.keepAudioEngineAlive = true` (already used by VAD)
2. Apply a higher VAD energy threshold during monitoring mode (ignore low-level audio)
3. If VoiceMode TTS is active, temporarily boost the detection cooldown or confidence threshold

**Complexity assessment: MEDIUM**

### 3.2 Option B: Hotkey-Based Interrupt (Simpler)

**Concept:** Register a global hotkey that, when pressed during generation, stops generation and activates voice input. No always-on listening needed.

**Changes required:**

1. Register a global hotkey in `HotKeyManager` (e.g., Cmd+Shift+V or a custom shortcut)
2. On hotkey press during `isStreaming`:
   - Call `session.stop()`
   - Activate voice input overlay
3. Optionally combine with the existing VAD detection system

**Complexity assessment: EASY**

This is simpler but loses the "hands-free" Jarvis experience.

### 3.3 Option C: Full Duplex (Hardest, Best UX)

**Concept:** Keep microphone always-on during generation. Detect not just wake words but also natural speech. If user starts talking (with or without wake word), pause generation.

This is essentially what the WorkEngine's interrupt system does but at the streaming level:
1. Speech activity (not just wake word) during generation triggers a pause
2. User's speech is transcribed
3. Transcribed text is injected as a "redirect" message (like `WorkEngine.redirect()`)

**Changes required:**
- All of Option A, plus:
- VAD energy-based speech detection (not just wake word) during generation
- A "debounce" to avoid false positives from ambient noise or TTS playback
- A new `ChatSession.redirect(message:)` method similar to `WorkEngine.redirect()`

**Complexity assessment: HARD**

---

## 4. Claude Code's `/btw` Pattern

### 4.1 How it works

Claude Code's `/btw` command allows the user to inject a message while the agent is generating. Internally:

1. The user types `/btw <message>` in the input field
2. Claude Code's frontend sends this as a "user interrupt" signal
3. The current generation is cancelled
4. The `/btw` message is appended to the conversation as a user turn
5. A new generation cycle starts with the updated context

This is essentially: **stop + append user message + regenerate**.

### 4.2 Replicating in Osaurus

Osaurus can replicate this directly:

```swift
// In ChatSession:
func interjectMessage(_ text: String) {
    stop()                                    // Cancel current generation
    trimTrailingEmptyAssistantTurn()          // Clean up incomplete response
    send(text)                                // Send new message, triggering new generation
}
```

For voice interruption, the flow would be:
1. Wake word detected -> `session.stop()`
2. Voice input activated -> user speaks
3. Voice transcription completed -> `session.send(transcribedText)`

This is functionally identical to `/btw` but triggered by voice.

---

## 5. MCP-Level Cancellation

### 5.1 Current State

The MCP protocol (as of 2025) supports a `notifications/cancelled` message that a client can send to cancel an in-progress tool call. However:

1. **Osaurus as MCP client:** Osaurus calls VoiceMode's `converse` tool via MCP. To cancel a running `converse` call, Osaurus would need to send `notifications/cancelled` to the VoiceMode MCP server.

2. **Osaurus's MCP handler** (`MCPHTTPHandler` and related files): There is no existing `notifications/cancelled` handler in the Osaurus codebase (confirmed by grep). The HTTP-based MCP transport in Osaurus does not currently support cancellation signals.

3. **VoiceMode MCP server:** The VoiceMode server would need to handle cancellation to stop TTS playback mid-sentence and/or stop STT listening early.

### 5.2 Relevance to Live Steering

MCP cancellation is relevant but not critical for the core feature:
- The primary need (stop AI generation) is handled at the Osaurus level via `session.stop()`
- MCP cancellation would be a nice-to-have for stopping a running `converse` tool call (e.g., if TTS is playing a long response)
- This can be added later as an enhancement

---

## 6. Complexity Assessment Summary

| Approach | Complexity | UX Quality | Hands-Free |
|---|---|---|---|
| Option B: Hotkey interrupt | **Easy** (1-2 days) | Good | No |
| Option A: VAD-during-generation | **Medium** (3-5 days) | Great | Yes |
| Option C: Full duplex | **Hard** (1-2 weeks) | Best | Yes |

### Recommended Path

**Phase 1 (Easy):** Implement Option B -- hotkey interrupt. Get the stop+voice-input flow working with a keyboard shortcut. This validates the core UX.

**Phase 2 (Medium):** Implement Option A -- VAD monitoring during generation. This adds the hands-free wake word detection during generation.

**Phase 3 (Hard, optional):** Explore Option C -- full duplex. This requires solving audio feedback loops and ambient noise filtering.

---

## 7. Code Locations Summary

### Files That Need Changes

| File | Change | Phase |
|---|---|---|
| `Packages/OsaurusCore/Services/Voice/VADService.swift` | Add `.vadInterruptDetected` notification; add `monitorDuringGeneration()` mode | A |
| `Packages/OsaurusCore/Views/Chat/FloatingInputCard.swift` | Handle interrupt notification; trigger stop + voice input | A, B |
| `Packages/OsaurusCore/Views/Chat/ChatView.swift` | Wire up VAD monitoring on `isStreaming` change; add `interjectMessage()` to ChatSession | A |
| `Packages/OsaurusCore/Managers/Chat/ChatWindowState.swift` | Possibly coordinate VAD state with window lifecycle | A |
| `Packages/OsaurusCore/Managers/HotKeyManager.swift` | Register interrupt hotkey | B |
| `Packages/OsaurusCore/AppDelegate.swift` | Handle new notification routing | A |
| `Packages/OsaurusCore/Services/Chat/AgentNameDetector.swift` | No changes needed (works as-is) | -- |
| `Packages/OsaurusCore/Services/Chat/ChatEngine.swift` | No changes needed (cancellation already works) | -- |
| `Packages/OsaurusCore/Models/Voice/VADConfiguration.swift` | Add config for interrupt-during-generation toggle | A |

### Files for Reference (No Changes Needed)

| File | Why It's Relevant |
|---|---|
| `Services/WorkEngine.swift` | Existing interrupt/redirect pattern to follow |
| `Services/WorkExecutionEngine.swift` | `InterruptCheckCallback` and `shouldInterrupt` pattern |
| `Tests/Chat/ChatSessionStopTests.swift` | Existing stop behavior tests to extend |
| `Managers/SpeechService.swift` | Audio engine management, keepAlive flag |

---

## 8. Open Questions

1. **Audio feedback during monitoring:** If Osaurus or VoiceMode is playing TTS audio, the microphone will pick it up. How to filter this? Options: echo cancellation, energy threshold gating, or simply not monitoring during TTS playback.

2. **Which window to interrupt?** If multiple chat windows are open, the interrupt should target the one that is currently streaming. The `lastFocusedWindowId` from `ChatWindowManager` is one approach.

3. **Partial response preservation:** When interrupting, should the partial AI response be kept in the conversation history? Currently `stop()` calls `finalizeRun(persistConversationArtifacts: false)` which means partial responses are trimmed. For redirect, we might want to keep the partial response so the AI knows what it already said.

4. **Work mode integration:** Should live steering also work in Work mode? The existing `WorkEngine.redirect()` method suggests this is architecturally possible but would need separate wiring.
