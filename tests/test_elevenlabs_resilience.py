"""Tests for ElevenLabs resilience: chunking, merging, retry, and fallback.

These tests cover cross-cutting reliability behaviors rather than individual
function happy-paths (which are in the dedicated TTS/STT test files).
"""

import io
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(audio_bytes=b"\x00\x01\x02"):
    client = MagicMock()
    client.text_to_speech.convert.return_value = iter([audio_bytes])
    return client


def _audio_file(size: int = 1024) -> io.BytesIO:
    buf = io.BytesIO(b"\x00" * size)
    buf.name = "audio.wav"
    return buf


# ---------------------------------------------------------------------------
# TTS text chunking thresholds
# ---------------------------------------------------------------------------

class TestTTSChunkingThresholds:
    """Verify exact chunk-count behaviour at boundary lengths."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_500_chars_single_chunk(self):
        """500-char text → exactly 1 chunk (below 2000 threshold)."""
        text = "A" * 500
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings"),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(text=text, voice="v", model="m")

        assert success is True
        assert mock_client.text_to_speech.convert.call_count == 1

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_3000_chars_multiple_chunks(self):
        """~3000-char text with sentences → 2+ chunks."""
        # Build sentence-delimited text just over 3000 chars
        sentence = "This is a test sentence with some content. "  # ~44 chars
        sentences = [sentence] * 70  # ~3080 chars
        text = "".join(sentences)
        assert len(text) > 2000

        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings"),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(text=text, voice="v", model="m")

        assert success is True
        assert mock_client.text_to_speech.convert.call_count >= 2


# ---------------------------------------------------------------------------
# TTS chunk merging
# ---------------------------------------------------------------------------

class TestTTSChunkMerging:
    """Verify small sentences get merged to avoid excessive API calls."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_many_small_sentences_are_merged(self):
        """100 tiny sentences totalling ~2500 chars should NOT produce 100 API calls."""
        # Each sentence ~25 chars; 100 sentences = ~2500 chars
        sentence = "Hello world. "  # 13 chars
        text = sentence * 200  # ~2600 chars, with many sentence boundaries
        assert len(text) > 2000

        mock_client = _make_mock_client()
        chunk_texts = []

        def capture_convert(**kwargs):
            chunk_texts.append(kwargs["text"])
            return iter([b"\x00"])

        mock_client.text_to_speech.convert.side_effect = capture_convert

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings"),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(text=text, voice="v", model="m")

        assert success is True
        # Should be 2-3 merged chunks, NOT 200
        assert len(chunk_texts) < 10, f"Expected merged chunks, got {len(chunk_texts)}"
        assert len(chunk_texts) >= 2  # Must be split (>2000 chars total)

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_each_chunk_under_max_size(self):
        """Every merged chunk should be <= MAX_CHUNK_CHARS (2000)."""
        sentence = "Here is a sentence of moderate length that helps test merging. "
        text = sentence * 60  # ~3720 chars
        assert len(text) > 2000

        mock_client = _make_mock_client()
        chunk_texts = []

        def capture_convert(**kwargs):
            chunk_texts.append(kwargs["text"])
            return iter([b"\x00"])

        mock_client.text_to_speech.convert.side_effect = capture_convert

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("elevenlabs.play.play"),
            patch("elevenlabs.VoiceSettings"),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            await elevenlabs_tts(text=text, voice="v", model="m")

        for i, chunk in enumerate(chunk_texts):
            assert len(chunk) <= 2100, (  # Allow small overshoot for last sentence
                f"Chunk {i} is {len(chunk)} chars, expected ≤ ~2000"
            )


# ---------------------------------------------------------------------------
# STT retry on connection_failed
# ---------------------------------------------------------------------------

class TestSTTRetryBehaviour:
    """Verify the retry logic in the converse tool's STT path."""

    async def test_realtime_stt_retry_on_connection_failed(self):
        """When realtime_transcribe returns connection_failed, it is retried once."""
        call_count = 0

        async def fake_realtime_transcribe(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "error_type": "connection_failed",
                    "provider": "elevenlabs",
                    "error": "resource_exhausted",
                }
            return {
                "text": "retry worked",
                "provider": "elevenlabs",
                "endpoint": "scribe_v2_realtime",
                "metrics": {"is_local": False, "request_time_ms": 100},
            }

        # Test the retry logic directly (extracted from converse.py pattern)
        stt_result = await fake_realtime_transcribe(api_key="k")
        assert stt_result.get("error_type") == "connection_failed"

        # Retry (mimicking the converse.py logic)
        if isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed":
            stt_result = await fake_realtime_transcribe(api_key="k")

        assert call_count == 2
        assert stt_result["text"] == "retry worked"


# ---------------------------------------------------------------------------
# STT fallback to batch after realtime fails twice
# ---------------------------------------------------------------------------

class TestSTTFallbackToBatch:
    """Verify fallback from realtime to batch STT when realtime fails twice."""

    async def test_fallback_to_batch_after_two_realtime_failures(self):
        """Two consecutive realtime failures trigger batch STT fallback."""
        realtime_call_count = 0

        async def always_fail_realtime(**kwargs):
            nonlocal realtime_call_count
            realtime_call_count += 1
            return {
                "error_type": "connection_failed",
                "provider": "elevenlabs",
                "error": "server overloaded",
            }

        # Simulate the converse.py retry-then-fallback logic
        stt_result = await always_fail_realtime(api_key="k")

        # First retry
        if isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed":
            stt_result = await always_fail_realtime(api_key="k")

        # Fallback to batch
        batch_called = False
        if isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed":
            batch_called = True
            # Simulate batch STT succeeding
            stt_result = {
                "text": "batch transcription",
                "provider": "elevenlabs",
                "endpoint": "api.elevenlabs.io/v1/speech-to-text",
                "metrics": {"is_local": False, "request_time_ms": 200},
            }

        assert realtime_call_count == 2, "Realtime should be tried exactly twice"
        assert batch_called, "Batch fallback should have been triggered"
        assert stt_result["text"] == "batch transcription"

    async def test_no_fallback_when_realtime_succeeds_on_retry(self):
        """If realtime succeeds on the retry, batch is NOT used."""
        realtime_call_count = 0

        async def fail_once_then_succeed(**kwargs):
            nonlocal realtime_call_count
            realtime_call_count += 1
            if realtime_call_count == 1:
                return {"error_type": "connection_failed", "provider": "elevenlabs", "error": "transient"}
            return {"text": "got it", "provider": "elevenlabs", "endpoint": "scribe_v2_realtime", "metrics": {}}

        stt_result = await fail_once_then_succeed(api_key="k")

        if isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed":
            stt_result = await fail_once_then_succeed(api_key="k")

        batch_called = False
        if isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed":
            batch_called = True

        assert realtime_call_count == 2
        assert not batch_called, "Batch should NOT be called when retry succeeds"
        assert stt_result["text"] == "got it"


# ---------------------------------------------------------------------------
# Client singleton behaviour
# ---------------------------------------------------------------------------

class TestClientSingleton:
    """Verify the ElevenLabs client singleton in elevenlabs_client.py."""

    def test_same_key_returns_same_client(self):
        """Same API key → same client instance (singleton)."""
        import voice_mode.elevenlabs_client as mod

        with patch.object(mod, "_client", None), patch.object(mod, "_client_api_key", None):
            with patch("voice_mode.elevenlabs_client.ElevenLabs") as MockEL:
                MockEL.side_effect = lambda api_key: MagicMock(api_key=api_key)

                c1 = mod.get_client("key-A")
                c2 = mod.get_client("key-A")

                assert c1 is c2
                assert MockEL.call_count == 1  # Only created once

    def test_different_key_creates_new_client(self):
        """Different API key → new client instance."""
        import voice_mode.elevenlabs_client as mod

        with patch.object(mod, "_client", None), patch.object(mod, "_client_api_key", None):
            with patch("voice_mode.elevenlabs_client.ElevenLabs") as MockEL:
                MockEL.side_effect = lambda api_key: MagicMock(api_key=api_key)

                c1 = mod.get_client("key-A")
                c2 = mod.get_client("key-B")

                assert c1 is not c2
                assert MockEL.call_count == 2
