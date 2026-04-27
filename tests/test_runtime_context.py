"""Focused tests for RuntimeContext settings and tool selection."""

import os
from pathlib import Path

from voice_mode.runtime_context import EnvFileLoader, RuntimeContext


def test_runtime_context_loads_settings_from_environment():
    runtime = RuntimeContext.load(
        environment={
            "VOICEMODE_BASE_DIR": "/tmp/voice-test",
            "VOICEMODE_SAVE_ALL": "true",
            "VOICEMODE_METRICS_LEVEL": "verbose",
            "VOICEMODE_TTS_BASE_URLS": "elevenlabs://tts,custom://tts",
            "VOICEMODE_STT_BASE_URLS": "elevenlabs://stt,custom://stt",
            "VOICEMODE_VOICES": "voice-a,voice-b",
            "VOICEMODE_TTS_MODELS": "model-a,model-b",
            "ELEVENLABS_API_KEY": "test-key",
            "VOICEMODE_STT_LANGUAGE": "en",
            "VOICEMODE_SERVE_PORT": "9999",
        }
    )

    settings = runtime.settings()

    assert settings.base_dir == Path("/tmp/voice-test")
    assert settings.audio.save_audio is True
    assert settings.audio.save_transcriptions is True
    assert settings.logging.metrics_level == "verbose"
    assert settings.providers.tts_base_urls == ("elevenlabs://tts", "custom://tts")
    assert settings.providers.stt_base_urls == ("elevenlabs://stt", "custom://stt")
    assert settings.providers.tts_voices == ("voice-a", "voice-b")
    assert settings.providers.tts_models == ("model-a", "model-b")
    assert settings.providers.elevenlabs_api_key == "test-key"
    assert settings.providers.stt_language == "en"
    assert settings.server.serve_port == 9999


def test_runtime_context_preserves_elevenlabs_default_provider_urls():
    runtime = RuntimeContext.load(environment={"ELEVENLABS_API_KEY": "test-key"})

    settings = runtime.settings()

    assert settings.tts_base_urls == ("elevenlabs://tts",)
    assert settings.stt_base_urls == ("elevenlabs://stt",)
    assert runtime.provider_base_urls("tts") == ("elevenlabs://tts",)
    assert runtime.provider_base_urls("stt") == ("elevenlabs://stt",)


def test_runtime_context_provider_settings_parse_overrides():
    runtime = RuntimeContext.load(
        environment={
            "OPENAI_API_KEY": "openai-key",
            "ELEVENLABS_API_KEY": "eleven-key",
            "VOICEMODE_TTS_BASE_URLS": "custom://tts, elevenlabs://tts",
            "VOICEMODE_STT_BASE_URLS": "custom://stt, elevenlabs://stt",
            "VOICEMODE_TTS_SPEED": "1.2",
            "VOICEMODE_ELEVENLABS_TTS_MODEL": "tts-model",
            "VOICEMODE_ELEVENLABS_TTS_VOICE": "voice-id",
            "VOICEMODE_ELEVENLABS_STT_MODEL": "stt-model",
            "VOICEMODE_ELEVENLABS_REALTIME_STT": "false",
            "VOICEMODE_ELEVENLABS_VOICE_STABILITY": "0.74",
            "VOICEMODE_ELEVENLABS_VOICE_SIMILARITY_BOOST": "0.91",
            "VOICEMODE_ELEVENLABS_VOICE_STYLE": "0.33",
            "VOICEMODE_ELEVENLABS_VOICE_USE_SPEAKER_BOOST": "false",
            "VOICEMODE_ELEVENLABS_VOICE_SEED": "12345",
        }
    )

    providers = runtime.provider_settings()

    assert providers.openai_api_key == "openai-key"
    assert providers.elevenlabs_api_key == "eleven-key"
    assert providers.tts_base_urls == ("custom://tts", "elevenlabs://tts")
    assert providers.stt_base_urls == ("custom://stt", "elevenlabs://stt")
    assert providers.tts_speed == 1.2
    assert providers.elevenlabs_tts_model == "tts-model"
    assert providers.elevenlabs_tts_voice == "voice-id"
    assert providers.elevenlabs_stt_model == "stt-model"
    assert providers.elevenlabs_use_realtime_stt is False
    assert providers.elevenlabs_voice_stability == 0.74
    assert providers.elevenlabs_voice_similarity_boost == 0.91
    assert providers.elevenlabs_voice_style == 0.33
    assert providers.elevenlabs_voice_use_speaker_boost is False
    assert providers.elevenlabs_voice_seed == 12345


def test_runtime_context_default_elevenlabs_voice_profile_is_expressive_but_stable():
    runtime = RuntimeContext.load(environment={})

    providers = runtime.provider_settings()

    assert providers.elevenlabs_voice_stability == 0.68
    assert providers.elevenlabs_voice_similarity_boost == 0.82
    assert providers.elevenlabs_voice_style == 0.15
    assert providers.elevenlabs_voice_use_speaker_boost is False
    assert providers.elevenlabs_voice_seed is None


def test_runtime_context_rejects_unknown_provider_base_url_service():
    runtime = RuntimeContext.load(environment={})

    try:
        runtime.provider_base_urls("embedding")
    except ValueError as exc:
        assert "Unsupported provider service" in str(exc)
    else:
        raise AssertionError("expected ValueError")



def test_runtime_context_finds_env_files_with_explicit_paths(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project" / "nested"
    home_config = home / ".voicemode" / "voicemode.env"
    project_config = project / ".voicemode.env"
    home_config.parent.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True)
    home_config.write_text("VOICEMODE_VOICES=global\n")
    project_config.write_text("VOICEMODE_VOICES=project\n")

    runtime = RuntimeContext.load(
        environment={},
        env_loader=EnvFileLoader(cwd=project, home=home),
    )

    assert runtime.env_files() == [home_config, project_config]


def test_runtime_context_loads_env_files_without_process_environment(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    home_config = home / ".voicemode" / "voicemode.env"
    project_config = cwd / ".voicemode.env"
    home_config.parent.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True)
    home_config.write_text("VOICEMODE_VOICES=global\nELEVENLABS_API_KEY=from-global\n")
    project_config.write_text("VOICEMODE_VOICES=project\nVOICEMODE_TTS_SPEED=1.2\n")
    monkeypatch.delenv("VOICEMODE_VOICES", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    environment = {}
    runtime = RuntimeContext.load(
        environment=environment,
        env_loader=EnvFileLoader(cwd=cwd, home=home),
    )
    loaded_files = runtime.load_env_files(environment, create_default=False)

    assert loaded_files == [home_config, project_config]
    assert environment["VOICEMODE_VOICES"] == "global"
    assert environment["ELEVENLABS_API_KEY"] == "from-global"
    assert environment["VOICEMODE_TTS_SPEED"] == "1.2"
    assert "VOICEMODE_VOICES" not in os.environ



def test_runtime_context_settings_refresh_after_loading_env_files(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    config_file = cwd / ".voicemode.env"
    cwd.mkdir(parents=True)
    config_file.write_text("ELEVENLABS_API_KEY=from-file\nVOICEMODE_TTS_SPEED=1.2\n")

    environment = {}
    runtime = RuntimeContext.load(
        environment=environment,
        env_loader=EnvFileLoader(cwd=cwd, home=home),
    )
    runtime.load_env_files(environment, create_default=False)

    providers = runtime.provider_settings()
    assert providers.elevenlabs_api_key == "from-file"
    assert providers.tts_speed == 1.2


def test_runtime_context_tool_selection_default_surface():
    runtime = RuntimeContext.load(environment={})

    selection = runtime.select_tools({"converse", "connect_status", "exchanges", "service"})

    assert selection.tools_to_load == {"converse", "connect_status", "exchanges"}
    assert selection.mode == "default mode (3 tools)"
    assert selection.invalid == set()


def test_runtime_context_tool_selection_whitelist_and_invalid():
    runtime = RuntimeContext.load(
        environment={"VOICEMODE_TOOLS_ENABLED": "converse,missing"}
    )

    selection = runtime.select_tools({"converse", "service"})

    assert selection.tools_to_load == {"converse"}
    assert selection.invalid == {"missing"}
    assert selection.mode == "whitelist mode (1 tools)"


def test_runtime_context_tool_selection_legacy_mode():
    runtime = RuntimeContext.load(environment={"VOICEMODE_TOOLS": "service"})

    selection = runtime.select_tools({"converse", "service"})

    assert selection.tools_to_load == {"service"}
    assert selection.legacy_requested is True
    assert selection.mode == "legacy mode (1 tools)"
