---
description: Start an ongoing voice conversation
argument-hint: [message]
---

# /voicemode:converse

Start a voice conversation using the `voicemode:converse` MCP tool.

## Implementation

Use the `converse` MCP tool with the user's message. All parameters have sensible defaults.

## If MCP Connection Fails

1. Check MCP server is configured in `~/.factory/mcp.json`:
   ```json
   {
     "mcpServers": {
       "voicemode": {
         "command": "uvx",
         "args": ["--from", "git+https://github.com/harshav167/ava.git", "voicemode"]
       }
     }
   }
   ```

2. Ensure `ELEVENLABS_API_KEY` is set in `~/.voicemode/voicemode.env`

3. Reconnect the MCP server
