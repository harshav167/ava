# VoiceMode Cursor Plugin

VoiceMode exposes its Cursor plugin metadata from this repository.

## Components

- `.cursor-plugin/plugin.json` wires Cursor to the canonical command folder and MCP server config.
- `commands/converse.md` is the canonical `/converse` command used by Cursor, Claude, and Factory plugin manifests.
- `mcp.json` is the plugin-scoped MCP definition and points the `voicemode` MCP server at `http://127.0.0.1:8765/mcp`.
- `.cursor/commands/converse.md` and `.claude/commands/converse.md` include the same voice-primary behavior for hosts that read project-local commands instead of plugin commands.

## Local Requirements

Start or restart the VoiceMode server after code changes:

```bash
./scripts/voicemode-server.sh restart
```

Set `ELEVENLABS_API_KEY` in `~/.voicemode/voicemode.env`.
