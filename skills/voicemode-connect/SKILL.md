---
name: voicemode-connect
description: |
  Remote voice via VoiceMode Connect. Use when users want to add voice to Droid using their phone or web app, without local STT/TTS setup.
---

# VoiceMode Connect for Factory Droid

Voice conversations through the voicemode.dev cloud platform. Connect Droid to voice clients (iOS app, web app) without running local STT/TTS services.

## How It Works

**Agents** (Droid, Claude Code) connect via MCP to voicemode.dev.
**Clients** (iOS app, web app) connect via WebSocket.
The platform routes voice messages between them.

## Quick Setup

### 1. Add the MCP Server

Add to your Droid MCP configuration:

```json
{
  "mcpServers": {
    "voicemode-dev": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://voicemode.dev/mcp"]
    }
  }
}
```

Note: This is separate from local VoiceMode. Local VoiceMode uses HTTP transport on port 8765:

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

### 2. Authenticate

When you first use a Connect tool, Droid will prompt for OAuth authentication. Sign in with your voicemode.dev account.

### 3. Connect a Client

Open the iOS app or web dashboard (voicemode.dev/dashboard) and sign in with the same account.

### 4. Start Talking

Use the `status` tool to see connected devices, then use `converse` to have a voice conversation.

## MCP Tools

| Tool | Description |
|------|-------------|
| `status` | Show connected devices and agents |
| `converse` | Two-way voice conversation via connected client |
