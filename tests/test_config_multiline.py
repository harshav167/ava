"""Tests for multiline environment variable handling in config loader."""

import os

from voice_mode.config import apply_env_file
from voice_mode.runtime_context import RuntimeContext


def test_config_multiline_quoted_values(tmp_path):
    """Test that config loader handles multiline quoted values."""
    config_file = tmp_path / "voicemode.env"
    config_file.write_text(
        """VOICEMODE_VOICES=af_nicole
VOICEMODE_PRONOUNCE='TTS bag carrier
TTS bottle drink'
VOICEMODE_DEBUG=false
"""
    )
    environment = {}

    apply_env_file(config_file, environment)

    assert environment["VOICEMODE_VOICES"] == "af_nicole"
    assert environment["VOICEMODE_DEBUG"] == "false"

    pronounce_value = environment["VOICEMODE_PRONOUNCE"]
    assert "TTS bag carrier" in pronounce_value
    assert "TTS bottle drink" in pronounce_value
    assert "\n" in pronounce_value

    from voice_mode.pronounce import parse_compact_rules

    rules = parse_compact_rules(pronounce_value)
    assert len(rules["tts"]) == 2
    assert rules["tts"][0].pattern == "bag"
    assert rules["tts"][0].replacement == "carrier"
    assert rules["tts"][1].pattern == "bottle"
    assert rules["tts"][1].replacement == "drink"


def test_config_single_line_quoted_values(tmp_path):
    """Test that config loader handles single-line quoted values."""
    config_file = tmp_path / "voicemode.env"
    config_file.write_text(
        """VOICEMODE_PRONOUNCE='TTS bag carrier'
VOICEMODE_TEST="STT foo bar"
"""
    )
    environment = {}

    apply_env_file(config_file, environment)

    assert environment["VOICEMODE_PRONOUNCE"] == "TTS bag carrier"
    assert environment["VOICEMODE_TEST"] == "STT foo bar"


def test_config_loader_preserves_existing_environment(tmp_path):
    config_file = tmp_path / "voicemode.env"
    config_file.write_text("VOICEMODE_VOICES=from_file\n")
    environment = {"VOICEMODE_VOICES": "from_env"}

    apply_env_file(config_file, environment)

    assert environment["VOICEMODE_VOICES"] == "from_env"



def test_runtime_context_applies_multiline_env_file_without_global_mutation(tmp_path, monkeypatch):
    config_file = tmp_path / "voicemode.env"
    config_file.write_text(
        """VOICEMODE_VOICES=af_nicole
VOICEMODE_PRONOUNCE='TTS bag carrier
TTS bottle drink'
"""
    )
    environment = {}
    monkeypatch.delenv("VOICEMODE_PRONOUNCE", raising=False)

    runtime = RuntimeContext.load(environment={})
    parsed = runtime.apply_env_file(config_file, environment)

    assert parsed["VOICEMODE_PRONOUNCE"] == "TTS bag carrier\nTTS bottle drink"
    assert environment["VOICEMODE_PRONOUNCE"] == "TTS bag carrier\nTTS bottle drink"
    assert "VOICEMODE_PRONOUNCE" not in os.environ
