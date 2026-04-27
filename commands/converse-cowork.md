---
name: converse-cowork
description: Split speak/listen voice conversation for MCP clients with a 60-second tool timeout
argument-hint: [message]
---

# /converse-cowork

Voice conversation pattern for MCP hosts with a hard 60-second tool timeout.

**CRITICAL: Some hosts kill MCP tool calls after 60 seconds regardless of the timeout parameter you pass. Split speak and listen into two separate tool calls.**

## The Pattern

### Step 1: SPEAK (no listening)
```
converse(message="Your message here", wait_for_response=false, wait_for_conch=true)
```
This speaks the message and returns immediately. Takes 5-30 seconds depending on message length.

### Step 2: LISTEN (no speaking)
```
converse(message="", skip_tts=true, wait_for_response=true, listen_duration_min=5, listen_duration_max=50, timeout=55, wait_for_conch=true)
```
This skips TTS and only listens for the user's response. Keep `listen_duration_max` under 50 seconds to stay within the 60s timeout with buffer.

### Why Two Calls?

Some MCP hosts enforce a 60-second hard timeout on all tool calls. A single converse call that speaks (10-30s) + listens can exceed that limit. Splitting into two calls keeps each under the limit.

## Full Example

```
// Step 1: Speak
converse(message="What would you like to work on today?", wait_for_response=false, wait_for_conch=true)

// Step 2: Listen
converse(message="", skip_tts=true, wait_for_response=true, listen_duration_min=5, listen_duration_max=50, timeout=55, wait_for_conch=true)
```

## When User Needs to Say Something Long

For dictation or detailed instructions, call listen multiple times:

```
// Speak first
converse(message="Go ahead, I'm listening.", wait_for_response=false, wait_for_conch=true)

// Listen round 1
result1 = converse(message="", skip_tts=true, wait_for_response=true, listen_duration_min=5, listen_duration_max=50, timeout=55, wait_for_conch=true)

// If user is still talking (result ends mid-sentence), listen again
result2 = converse(message="", skip_tts=true, wait_for_response=true, listen_duration_min=5, listen_duration_max=50, timeout=55, wait_for_conch=true)
```

## Important Notes

- **Use this only for hosts with a hard 60-second MCP timeout.** Normal Cursor/Claude Code/Factory flows should use `/converse`.
- The `timeout` parameter may be ignored by hosts with hard tool-call limits. Set it anyway for documentation.
- Keep TTS messages SHORT. Long messages take longer to generate and play, eating into your 60s budget.
- The `skip_tts=true` parameter tells converse to skip text-to-speech and go straight to listening.

## MCP Setup

In `claude_desktop_config.json`:

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
