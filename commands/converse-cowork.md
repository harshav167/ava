---
description: Voice conversation for Claude Desktop (Cowork) — handles 60s timeout limit
argument-hint: [message]
---

# /converse-cowork

Voice conversation optimized for **Claude Desktop / Cowork** which has a **hardcoded 60-second MCP timeout**.

**CRITICAL: Claude Desktop kills MCP tool calls after 60 seconds regardless of the timeout parameter you pass. You MUST split speak and listen into two separate tool calls.**

## The Pattern

### Step 1: SPEAK (no listening)
```
converse(message="Your message here", wait_for_response=false, speed=1.2)
```
This speaks the message and returns immediately. Takes 5-30 seconds depending on message length.

### Step 2: LISTEN (no speaking)
```
converse(message="", skip_tts=true, wait_for_response=true, speed=1.2, listen_duration_min=5, listen_duration_max=50, timeout=55)
```
This skips TTS and only listens for the user's response. Keep `listen_duration_max` under 50 seconds to stay within the 60s timeout with buffer.

### Why Two Calls?

Claude Desktop enforces a 60-second hard timeout on ALL MCP tool calls. A single converse call that speaks (10-30s) + listens (up to 60s) will always exceed 60s and get killed. Splitting into two calls keeps each under the limit.

## Full Example

```
// Step 1: Speak
converse(message="What would you like to work on today?", wait_for_response=false, speed=1.2)

// Step 2: Listen
converse(message="", skip_tts=true, wait_for_response=true, listen_duration_min=5, listen_duration_max=50, timeout=55)
```

## When User Needs to Say Something Long

For dictation or detailed instructions, call listen multiple times:

```
// Speak first
converse(message="Go ahead, I'm listening.", wait_for_response=false, speed=1.2)

// Listen round 1
result1 = converse(message="", skip_tts=true, wait_for_response=true, listen_duration_max=50, timeout=55)

// If user is still talking (result ends mid-sentence), listen again
result2 = converse(message="", skip_tts=true, wait_for_response=true, listen_duration_max=50, timeout=55)
```

## Important Notes

- **This command is ONLY for Claude Desktop / Cowork.** Claude Code and Factory Droid do NOT have this 60s limit.
- The `timeout` parameter is ignored by Claude Desktop — it always uses 60s. Set it anyway for documentation.
- Keep TTS messages SHORT. Long messages take longer to generate and play, eating into your 60s budget.
- The `skip_tts=true` parameter tells converse to skip text-to-speech and go straight to listening.

## MCP Setup for Claude Desktop

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
