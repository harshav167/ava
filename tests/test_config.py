"""Compatibility tests for config module globals."""

def test_config_provider_globals_use_runtime_context_parser(monkeypatch):
    from voice_mode import config

    monkeypatch.setattr(config, "load_voicemode_env", lambda environment=None: None)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    monkeypatch.setenv("VOICEMODE_TTS_BASE_URLS", "custom://tts, elevenlabs://tts")
    monkeypatch.setenv("VOICEMODE_STT_BASE_URLS", "custom://stt, elevenlabs://stt")
    monkeypatch.setenv("VOICEMODE_TTS_SPEED", "1.2")
    monkeypatch.setenv("VOICEMODE_VOICES", "voice-a, voice-b")
    monkeypatch.setenv("VOICEMODE_TTS_MODELS", "model-a, model-b")
    monkeypatch.setenv("VOICEMODE_ELEVENLABS_TTS_MODEL", "tts-model")
    monkeypatch.setenv("VOICEMODE_ELEVENLABS_TTS_VOICE", "voice-id")
    monkeypatch.setenv("VOICEMODE_ELEVENLABS_STT_MODEL", "stt-model")
    monkeypatch.setenv("VOICEMODE_ELEVENLABS_REALTIME_STT", "false")

    config.reload_configuration()

    assert config.OPENAI_API_KEY == "openai-key"
    assert config.ELEVENLABS_API_KEY == "eleven-key"
    assert config.TTS_BASE_URLS == ["custom://tts", "elevenlabs://tts"]
    assert config.STT_BASE_URLS == ["custom://stt", "elevenlabs://stt"]
    assert config.TTS_SPEED == 1.2
    assert config.TTS_VOICES == ["voice-a", "voice-b"]
    assert config.TTS_MODELS == ["model-a", "model-b"]
    assert config.ELEVENLABS_TTS_MODEL == "tts-model"
    assert config.ELEVENLABS_TTS_VOICE == "voice-id"
    assert config.ELEVENLABS_STT_MODEL == "stt-model"
    assert config.ELEVENLABS_USE_REALTIME_STT is False


def test_config_reload_keeps_elevenlabs_default_provider_urls(monkeypatch):
    from voice_mode import config

    monkeypatch.setattr(config, "load_voicemode_env", lambda environment=None: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    monkeypatch.delenv("VOICEMODE_TTS_BASE_URLS", raising=False)
    monkeypatch.delenv("VOICEMODE_STT_BASE_URLS", raising=False)

    config.reload_configuration()

    assert config.TTS_BASE_URLS == ["elevenlabs://tts"]
    assert config.STT_BASE_URLS == ["elevenlabs://stt"]
