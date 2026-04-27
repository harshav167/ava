---
name: verify
description: Run tests and import checks to verify the codebase is healthy. Use after making changes or before committing.
---

Run the following verification steps in order. Stop on first failure and report.

1. **Import check**: `uv run python -c "from voice_mode.server import mcp"`
2. **Unit tests**: `uv run pytest tests/ -v --tb=short -x -q`
3. **Format check**: `ruff format --check voice_mode/`

Report pass/fail for each step. If all pass, say "All checks passed."
