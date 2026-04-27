---
name: status
description: Check the VoiceMode MCP server and configuration status
---

# /voicemode:status

Check the status of the VoiceMode MCP server and configuration.

## Usage

```
/voicemode:status
```

## Description

Shows whether the local HTTP MCP server is running on port 8765 and whether VoiceMode configuration is available.

## Implementation

Use the `mcp__voicemode__service` tool:

```json
{
  "service_name": "voicemode",
  "action": "status"
}
```

Check the local launchd-managed server from the shell if the MCP tool is unavailable:

```bash
./scripts/voicemode-server.sh status
```

## Output

Shows:
- MCP server running/listening status
- Relevant configuration status
- Any actionable setup issue
