"""Tests for ElevenLabs batch STT integration.

Covers voice_mode/elevenlabs_tts_stt.py::elevenlabs_stt and
voice_mode/elevenlabs_client.py::elevenlabs_stt_batch.
"""

import io
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio_file(size: int = 1024) -> io.BytesIO:
    """Return a seekable in-memory file simulating audio data."""
    buf = io.BytesIO(b"\x00" * size)
    buf.name = "audio.wav"
    return buf


def _mock_stt_result(text: str = "hello world", lang: str = "en"):
    """Build a mock result object matching ElevenLabs SDK shape."""
    result = MagicMock()
    result.text = text
    result.language_code = lang
    return result


# ---------------------------------------------------------------------------
# elevenlabs_stt_batch (client layer)
# ---------------------------------------------------------------------------

class TestElevenLabsSTTBatch:
    """Tests for the low-level batch STT wrapper in elevenlabs_client.py."""

    def test_basic_batch_stt(self):
        """Successful transcription returns text and language."""
        mock_client = MagicMock()
        mock_client.speech_to_text.convert.return_value = _mock_stt_result("testing one two three", "en")

        with patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client):
            from voice_mode.elevenlabs_client import elevenlabs_stt_batch

            result = elevenlabs_stt_batch(
                audio_file=_audio_file(),
                model_id="scribe_v2",
                language_code="en",
                api_key="test-key",
            )

        assert result["text"] == "testing one two three"
        assert result["language"] == "en"
        assert "elapsed_ms" in result

        # Verify SDK was called with correct kwargs
        call_kwargs = mock_client.speech_to_text.convert.call_args.kwargs
        assert call_kwargs["model_id"] == "scribe_v2"
        assert call_kwargs["language_code"] == "en"

    def test_batch_stt_with_keyterms(self):
        """keyterms are forwarded to the SDK."""
        mock_client = MagicMock()
        mock_client.speech_to_text.convert.return_value = _mock_stt_result("VoiceMode is great")

        with patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client):
            from voice_mode.elevenlabs_client import elevenlabs_stt_batch

            elevenlabs_stt_batch(
                audio_file=_audio_file(),
                model_id="scribe_v2",
                keyterms=["VoiceMode", "ElevenLabs"],
                api_key="test-key",
            )

        call_kwargs = mock_client.speech_to_text.convert.call_args.kwargs
        assert call_kwargs["keyterms"] == ["VoiceMode", "ElevenLabs"]

    def test_batch_stt_auto_language_omitted(self):
        """language_code='auto' is NOT passed to the SDK."""
        mock_client = MagicMock()
        mock_client.speech_to_text.convert.return_value = _mock_stt_result("ok")

        with patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client):
            from voice_mode.elevenlabs_client import elevenlabs_stt_batch

            elevenlabs_stt_batch(
                audio_file=_audio_file(),
                model_id="scribe_v2",
                language_code="auto",
                api_key="test-key",
            )

        call_kwargs = mock_client.speech_to_text.convert.call_args.kwargs
        assert "language_code" not in call_kwargs

    def test_batch_stt_empty_text(self):
        """Empty transcription returns empty string."""
        mock_client = MagicMock()
        mock_client.speech_to_text.convert.return_value = _mock_stt_result("")

        with patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client):
            from voice_mode.elevenlabs_client import elevenlabs_stt_batch

            result = elevenlabs_stt_batch(
                audio_file=_audio_file(),
                api_key="test-key",
            )

        assert result["text"] == ""

    def test_batch_stt_none_text(self):
        """None text from SDK is treated as empty string."""
        mock_client = MagicMock()
        result_obj = MagicMock()
        result_obj.text = None
        result_obj.language_code = None
        mock_client.speech_to_text.convert.return_value = result_obj

        with patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client):
            from voice_mode.elevenlabs_client import elevenlabs_stt_batch

            result = elevenlabs_stt_batch(
                audio_file=_audio_file(),
                api_key="test-key",
            )

        assert result["text"] == ""


# ---------------------------------------------------------------------------
# elevenlabs_stt (higher-level wrapper in elevenlabs_tts_stt.py)
#
# NOTE: elevenlabs_stt_batch is imported *inside* the function body via
#   `from .elevenlabs_client import elevenlabs_stt_batch`
# so we must patch at the source: voice_mode.elevenlabs_client.elevenlabs_stt_batch
# ---------------------------------------------------------------------------

class TestElevenLabsSTTWrapper:
    """Tests for the async elevenlabs_stt wrapper."""

    @patch("voice_mode.elevenlabs_tts_stt.STT_PROMPT", "")
    @patch("voice_mode.elevenlabs_tts_stt.STT_LANGUAGE", "en")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stt_success(self):
        """Successful STT returns text + provider info."""
        mock_batch = MagicMock(return_value={"text": "hello world", "language": "en", "elapsed_ms": 100})

        with patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", mock_batch):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_stt

            result = await elevenlabs_stt(audio_file=_audio_file(), model="scribe_v2")

        assert result["text"] == "hello world"
        assert result["provider"] == "elevenlabs"
        assert "metrics" in result

    @patch("voice_mode.elevenlabs_tts_stt.STT_PROMPT", "VoiceMode,Claude")
    @patch("voice_mode.elevenlabs_tts_stt.STT_LANGUAGE", "en")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stt_passes_keyterms_from_prompt(self):
        """STT_PROMPT is parsed into keyterms and forwarded."""
        mock_batch = MagicMock(return_value={"text": "ok", "language": "en", "elapsed_ms": 50})

        with patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", mock_batch):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_stt

            await elevenlabs_stt(audio_file=_audio_file())

        call_kwargs = mock_batch.call_args.kwargs
        assert call_kwargs["keyterms"] == ["VoiceMode", "Claude"]

    @patch("voice_mode.elevenlabs_tts_stt.STT_PROMPT", "")
    @patch("voice_mode.elevenlabs_tts_stt.STT_LANGUAGE", "auto")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stt_auto_language_defaults_to_none(self):
        """When STT_LANGUAGE is 'auto', we send None to let the SDK auto-detect."""
        mock_batch = MagicMock(return_value={"text": "ok", "language": "en", "elapsed_ms": 50})

        with patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", mock_batch):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_stt

            await elevenlabs_stt(audio_file=_audio_file())

        call_kwargs = mock_batch.call_args.kwargs
        assert call_kwargs["language_code"] is None

    @patch("voice_mode.elevenlabs_tts_stt.STT_PROMPT", "")
    @patch("voice_mode.elevenlabs_tts_stt.STT_LANGUAGE", "en")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stt_no_speech(self):
        """Empty transcription returns no_speech error."""
        mock_batch = MagicMock(return_value={"text": "", "language": "en", "elapsed_ms": 50})

        with patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", mock_batch):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_stt

            result = await elevenlabs_stt(audio_file=_audio_file())

        assert result["error_type"] == "no_speech"
        assert result["provider"] == "elevenlabs"

    @patch("voice_mode.elevenlabs_tts_stt.STT_PROMPT", "")
    @patch("voice_mode.elevenlabs_tts_stt.STT_LANGUAGE", "en")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stt_api_failure(self):
        """SDK exception returns connection_failed error."""
        mock_batch = MagicMock(side_effect=RuntimeError("Server error 500"))

        with patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", mock_batch):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_stt

            result = await elevenlabs_stt(audio_file=_audio_file())

        assert result["error_type"] == "connection_failed"
        assert "Server error 500" in result["attempted_endpoints"][0]["error"]
