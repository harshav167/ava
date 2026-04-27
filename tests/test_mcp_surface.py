"""Tests for MCP surface loading defaults."""

import importlib

from voice_mode.runtime_context import RuntimeContext


def test_default_tools_exclude_service():
    import voice_mode.tools as tools_mod

    runtime = RuntimeContext.load(environment={})
    loaded, mode = tools_mod.determine_tools_to_load(runtime)
    assert "service" not in loaded
    assert {"converse", "connect_status", "exchanges"}.issubset(loaded)


def test_default_resources_are_minimal(monkeypatch):
    import voice_mode.resources as resources_mod

    monkeypatch.delenv("VOICEMODE_RESOURCES_ENABLED", raising=False)
    monkeypatch.delenv("VOICEMODE_RESOURCES_DISABLED", raising=False)
    importlib.reload(resources_mod)

    assert resources_mod.DEFAULT_RESOURCE_MODULES == {"version", "audio_files", "docs_resources", "changelog"}


def test_default_prompts_are_minimal(monkeypatch):
    import voice_mode.prompts as prompts_mod

    monkeypatch.delenv("VOICEMODE_PROMPTS_ENABLED", raising=False)
    monkeypatch.delenv("VOICEMODE_PROMPTS_DISABLED", raising=False)
    importlib.reload(prompts_mod)

    assert prompts_mod.DEFAULT_PROMPT_MODULES == {"converse"}
