---
name: restart
description: Restart the VoiceMode dev server and verify it's healthy. Use after code changes.
disable-model-invocation: true
---

Restart the VoiceMode MCP server and verify it comes up healthy:

1. Run `./scripts/voicemode-server.sh restart 2>&1`
2. Wait 5 seconds: `sleep 5`
3. Check status: `./scripts/voicemode-server.sh status`
4. If status shows "not listening", the port may be stuck. Run:
   ```bash
   lsof -ti :8765 | xargs kill 2>/dev/null
   sleep 2
   ./scripts/voicemode-server.sh start
   sleep 5
   ./scripts/voicemode-server.sh status
   ```
5. Report whether the server is running and listening on port 8765.
