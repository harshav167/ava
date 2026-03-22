"""Tests for ElevenLabs TTS integration (voice_mode/elevenlabs_tts_stt.py)."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(audio_bytes=b"\x00\x01\x02"):
    """Return a mock ElevenLabs client whose convert() yields audio bytes."""
    client = MagicMock()
    client.text_to_speech.convert.return_value = iter([audio_bytes])
    return client


def _tts_patches(mock_client):
    """
    Return the standard set of patches needed for elevenlabs_tts tests.

    VoiceSettings and play are imported *inside* the function body, so we
    patch them at their origin modules (elevenlabs.VoiceSettings, elevenlabs.play.play)
    rather than on voice_mode.elevenlabs_tts_stt.
    """
    return (
        patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
        patch("elevenlabs.play.play"),
        patch("elevenlabs.VoiceSettings", MagicMock),
    )


# ---------------------------------------------------------------------------
# Basic TTS
# ---------------------------------------------------------------------------

class TestElevenLabsTTSBasic:
    """Basic TTS call paths."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "test-voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "test-key")
    async def test_basic_tts_success(self):
        """Short text produces a single convert() call and returns success."""
        mock_client = _make_mock_client()

        with _tts_patches(mock_client)[0], _tts_patches(mock_client)[1] as mock_play, _tts_patches(mock_client)[2]:
            # Re-create patches so they share the same mock_client
            pass

        # Use explicit patches to share the same mock_client
        mock_client = _make_mock_client()
        p1 = patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client)
        p2 = patch("elevenlabs.play.play")
        p3 = patch("elevenlabs.VoiceSettings", MagicMock)

        with p1, p2 as mock_play, p3:
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="Hello world",
                voice="caller-voice",
                model="caller-model",
            )

        assert success is True
        assert metrics is not None
        assert "generation" in metrics
        assert "playback" in metrics
        assert config["provider"] == "elevenlabs"
        # Caller params override config defaults
        assert config["voice"] == "caller-voice"
        assert config["model"] == "caller-model"

        # Only one chunk → one convert call, one play call
        mock_client.text_to_speech.convert.assert_called_once()
        mock_play.assert_called_once()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "test-voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "test-key")
    async def test_tts_empty_text(self):
        """Empty string still calls convert() (edge-case, not an error)."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="", voice="v", model="m",
            )

        assert success is True
        mock_client.text_to_speech.convert.assert_called_once()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "key")
    async def test_tts_uses_caller_params_over_config(self):
        """convert() must use caller-provided voice/model, falling back to config."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            await elevenlabs_tts(text="hi", voice="caller-voice", model="caller-model")

        call_kwargs = mock_client.text_to_speech.convert.call_args
        assert call_kwargs.kwargs["voice_id"] == "caller-voice"
        assert call_kwargs.kwargs["model_id"] == "caller-model"


# ---------------------------------------------------------------------------
# Speed parameter
# ---------------------------------------------------------------------------

class TestElevenLabsTTSSpeed:
    """Speed parameter handling."""

    @pytest.mark.parametrize("speed", [0.7, 1.0, 1.2])
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_speed_values(self, speed):
        """Speed kwarg is forwarded to VoiceSettings."""
        mock_client = _make_mock_client()
        captured_settings = []

        class FakeVoiceSettings:
            def __init__(self, **kw):
                captured_settings.append(kw)

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", FakeVoiceSettings),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(
                text="test", voice="v", model="m", speed=speed,
            )

        assert success is True
        assert captured_settings[0]["speed"] == speed

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_default_speed_is_1_2(self):
        """When no speed kwarg is provided, default to 1.2."""
        mock_client = _make_mock_client()
        captured_settings = []

        class FakeVoiceSettings:
            def __init__(self, **kw):
                captured_settings.append(kw)

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", FakeVoiceSettings),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            await elevenlabs_tts(text="test", voice="v", model="m")

        assert captured_settings[0]["speed"] == 1.2


# ---------------------------------------------------------------------------
# Chunking for long text
# ---------------------------------------------------------------------------

class TestElevenLabsTTSChunking:
    """Text chunking for long inputs (>2000 chars)."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_long_text_is_chunked(self):
        """Text longer than 2000 chars is split into multiple convert() calls."""
        # Build a ~3000-char string of sentences
        sentences = []
        while sum(len(s) for s in sentences) < 3000:
            sentences.append("This is a moderately long sentence that will help us exceed the limit. ")
        long_text = " ".join(sentences)
        assert len(long_text) > 2000

        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play") as mock_play,
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(
                text=long_text, voice="v", model="m",
            )

        assert success is True
        assert mock_client.text_to_speech.convert.call_count >= 2
        assert mock_play.call_count == mock_client.text_to_speech.convert.call_count

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_short_text_not_chunked(self):
        """Text under 2000 chars is NOT split."""
        short_text = "Hello. World. Foo bar."
        assert len(short_text) < 2000

        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(
                text=short_text, voice="v", model="m",
            )

        assert success is True
        mock_client.text_to_speech.convert.assert_called_once()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_chunking_splits_on_sentence_boundaries(self):
        """Chunks should end at sentence boundaries (.!?), not mid-sentence."""
        # 10 sentences of ~250 chars each → ~2500 total → 2 chunks
        sentence = "A" * 245 + ". "
        long_text = sentence * 10
        assert len(long_text) > 2000

        mock_client = _make_mock_client()
        recorded_chunks = []

        def capture_convert(**kwargs):
            recorded_chunks.append(kwargs["text"])
            return iter([b"\x00"])

        mock_client.text_to_speech.convert.side_effect = capture_convert

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            await elevenlabs_tts(text=long_text, voice="v", model="m")

        assert len(recorded_chunks) >= 2
        # Each chunk (except possibly the last) should end at a sentence boundary
        for chunk in recorded_chunks[:-1]:
            assert chunk.rstrip().endswith("."), f"Chunk does not end at sentence boundary: ...{chunk[-30:]}"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestElevenLabsTTSErrors:
    """Failure scenarios."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_api_error(self):
        """API error returns (False, None, error_config)."""
        mock_client = MagicMock()
        mock_client.text_to_speech.convert.side_effect = RuntimeError("API rate limit")

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert metrics is None
        assert config["error_type"] == "all_providers_failed"
        assert "API rate limit" in config["attempted_endpoints"][0]["error"]

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_network_error(self):
        """Network-level error is reported properly."""
        mock_client = MagicMock()
        mock_client.text_to_speech.convert.side_effect = ConnectionError("DNS resolution failed")

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert "DNS resolution failed" in config["attempted_endpoints"][0]["error"]

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_play_error_is_caught(self):
        """If play() raises, TTS reports failure."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play", side_effect=OSError("ffplay not found")),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert "ffplay not found" in config["attempted_endpoints"][0]["error"]
