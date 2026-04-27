---
description: Start a continuous voice-primary conversation with the user
argument-hint: [message]
---

# /converse

Enter continuous voice-primary conversation mode using the `converse` tool from the `voicemode` MCP server.

## Core Contract

When this command is active, the user may be selectively blind to chat output. Treat MCP voice delivery as the primary communication channel, not an optional enhancement.

`/converse` is reusable plugin guidance for agents across projects, not just a local chat convention. It starts a voice-primary workflow that continues until the user explicitly says to stop, such as "ok stop", "stop converse", or "exit voice mode".

The cadence is outcome-driven, not progress-driven:

1. For a user request that requires work, optionally give one short spoken acknowledgement before starting. Use this only to confirm understanding or say that work is beginning.
2. Do the work silently. Do not narrate routine progress through voice or chat.
3. Speak the substantive result or blocker when there is one.
4. If the result needs user input, listen for the user with `wait_for_response=true`.
5. Do not count an earlier acknowledgement as satisfying the later outcome. The final result still needs its own voice call.
6. Do not send the exact chat response verbatim to TTS. Speak a concise, natural version that preserves the intent and important decisions.
7. Do not fall back to chat-only output. If the MCP call fails or is unavailable, say in chat that voice delivery failed and treat the voice session as blocked until the MCP path is restored.
8. Do not stop the voice loop just because the assistant thinks the answer is complete. Only stop when the user explicitly tells you to stop.

Think of this as selective blindness: the chat transcript exists, but the user depends on voice to continue the session.

## Required Response Order

For a substantive outcome, respond in this order:

1. **Chat first, if the host expects a transcript:** provide the normal answer/update in chat. Keep it brief when the user is actively using voice.
2. **Voice second:** call `converse` with a spoken adaptation of that same response.
3. **Listen by default:** for the main response/outcome, use `wait_for_response=true` so the user can continue speaking.

For work that will take time, the first response may be a short acknowledgement with `wait_for_response=false`, then the agent should work silently. Do not keep sending intermediate spoken progress updates. Speak again only when there is a result, a blocker, or a user decision needed.

There is no special "final answer" exemption in converse mode. If the user has not explicitly said to stop, the assistant must keep the voice loop open after substantive outcomes.

Do not end the turn after a substantive chat message unless the matching `converse` call has succeeded and listened for the user's next response, or unless you are explicitly reporting that voice delivery failed and the voice session is blocked.

## Wait-For-Response Rules

Use `wait_for_response=true` for:

- The main answer or outcome of a turn.
- Clarifying questions.
- Any response where the user should be able to continue the conversation.
- Corrections, apologies, summaries, or confirmations that complete the current thought.

Use `wait_for_response=false` only for the first short acknowledgement before starting work, or for an exceptional announcement where pausing for the user would interrupt the task. Keep these messages rare and high-signal. Do not narrate every small step. Examples:

- "I understand the issue. I will inspect the server path and speak the result when done."
- "I am going to run the focused tests and restart only if they pass."
- "This needs a few minutes of work; I will stay quiet until I have the result."

Avoid routine intermediary updates like "I am reading the file now", "I found the file", "tests are still running", or "I am restarting now" unless that is the actual useful outcome the user needs.

A `wait_for_response=false` progress announcement does not satisfy the requirement for the later main response. The later main response must still be spoken with `wait_for_response=true` unless the user explicitly told the assistant not to listen.

## Stop Condition

Stay in converse mode until the user explicitly says a stop phrase, such as:

- "ok stop"
- "stop converse"
- "exit voice mode"
- "back to chat"

When the user says to stop, acknowledge once in chat and, if appropriate, with a short final voice confirmation using `wait_for_response=false`.

## Conch

Always set `wait_for_conch=true` unless the user explicitly asks otherwise. Multiple agents or sessions may be using voice at once, and Conch is the coordination mechanism that prevents agents from speaking over each other.

If another agent is speaking, queue behind Conch instead of failing or switching to chat-only.

## Tool Name

Use the `converse` tool from the `voicemode` MCP server.

Known client aliases:
- Cursor/project MCP: `converse` on the `voicemode` server
- Claude Code: `voicemode:converse` or `mcp__voicemode__converse`
- Factory Droid: `mcp__voicemode__converse` or `voicemode___converse`
- Claude Desktop: `converse` under the `voicemode` MCP server

## Mandatory Defaults

For main conversation turns, call the tool with these defaults unless the user explicitly asks otherwise:

```
converse(
  message="Short voice adaptation of the chat response",
  speed=1.2,
  listen_duration_min=5,
  listen_duration_max=300,
  timeout=300,
  wait_for_response=true,
  wait_for_conch=true
)
```

For the optional first acknowledgement before work continues immediately:

```
converse(
  message="Brief acknowledgement; I will work silently and report the result.",
  speed=1.2,
  listen_duration_min=5,
  listen_duration_max=300,
  timeout=300,
  wait_for_response=false,
  wait_for_conch=true
)
```

Do not repeat this pattern for ongoing progress updates.

## Timeout Rule

Both `listen_duration_max` and `timeout` are in seconds. `timeout` controls when the MCP call itself times out.

**Always keep `timeout >= listen_duration_max`. Default both to 300 seconds.**

Bad:
```
converse(message="...", listen_duration_max=300, timeout=60)
```

Good:
```
converse(message="...", listen_duration_max=300, timeout=300)
```

## User Cutoff Recovery

If the user says they are being cut off:

```
converse(message="Take your time. I adjusted the listening settings.", listen_duration_min=10, vad_aggressiveness=0, speed=1.2, listen_duration_max=300, timeout=300, wait_for_response=true, wait_for_conch=true)
```

For long dictation:

```
converse(message="Go ahead, I am listening for the full duration.", disable_silence_detection=true, listen_duration_max=300, timeout=300, speed=1.2, wait_for_response=true, wait_for_conch=true)
```

## MCP Failure Behavior

If `converse` fails:

- Do not pretend the user can continue through chat.
- Do not keep working silently in text-only mode.
- Report the failure in chat for the transcript.
- Stop and make restoring MCP voice delivery the next task.

Example chat response:

> Voice delivery failed, so I am stopping here instead of continuing chat-only. The voice session is blocked until the VoiceMode MCP server is restored.

## MCP Setup

VoiceMode runs as an HTTP server on port `8765`, managed by launchd via `scripts/voicemode-server.sh`.

Plugin MCP config:

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
