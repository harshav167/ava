---
name: voicemode-connect
description: Remote voice via VoiceMode Connect. Use when users want to add voice to an AI coding assistant using their phone or web app, without local STT/TTS setup.
---

# VoiceMode Connect

Voice conversations through the voicemode.dev cloud platform. Connect your AI assistant to voice clients (iOS app, web app) without running local STT/TTS services.

## How It Works

**Agents** (Cursor, Claude Code, Factory, or other MCP hosts) connect via MCP to voicemode.dev.
**Clients** (iOS app, web app) connect via WebSocket.
The platform routes voice messages between them.

## Quick Setup

### 1. Add the MCP Server

Add to your MCP host configuration:

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

When you first use a Connect tool, your MCP host will prompt for OAuth authentication. Sign in with your voicemode.dev account.

### 3. Connect a Client

Open the iOS app or web dashboard (voicemode.dev/dashboard) and sign in with the same account.

### 4. Start Talking

Use the `status` tool to see connected devices, then use `converse` to have a voice conversation.

## MCP Tools

| Tool | Description |
|------|-------------|
| `status` | Show connected devices and agents |
| `converse` | Two-way voice conversation via connected client |

## Relationship to Local VoiceMode

| Feature | Local VoiceMode | VoiceMode Connect |
|---------|-----------------|-------------------|
| STT/TTS | ElevenLabs (eleven_v3 / Scribe v2) | Client device (phone/browser) |
| Setup | HTTP server on port 8765 | Just add MCP server |
| Internet | Required (ElevenLabs API) | Required |
| Latency | Lower | Higher |
| Mobile voice | No | Yes |

**Use both**: Local VoiceMode for desktop voice, Connect for mobile voice.

## Documentation

- [Overview](../../docs/connect/README.md) - What is VoiceMode Connect
- [Architecture](../../docs/connect/architecture.md) - How agents and clients connect
- [Claude Code Setup](../../docs/connect/setup/claude-code.md) - Detailed setup guide
- [MCP Tools Reference](../../docs/connect/reference/mcp-tools.md) - Tool parameters

## Open Questions

- How do multiple agents on the same account interact?
- What happens when multiple clients are connected?
- How is the target device selected for `converse`?

These are documented in [docs/connect/](../../docs/connect/) as we learn more.
