"""Tests for ElevenLabs Realtime STT (WebSocket-based).

Covers voice_mode/elevenlabs_realtime_stt.py::realtime_transcribe.
All WebSocket / sounddevice interactions are mocked.
"""

import asyncio
import wave

import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeConnection:
    """Simulates an ElevenLabs realtime WebSocket connection.

    Register handlers with .on(event, handler), then trigger them from test
    code by calling .fire(event, data).
    """

    def __init__(self):
        self._handlers: dict = {}
        self.closed = False
        self.sent_chunks: list = []

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def fire(self, event, data=None):
        for h in self._handlers.get(event, []):
            if data is not None:
                h(data)
            else:
                h()

    async def send(self, payload):
        self.sent_chunks.append(payload)

    async def commit(self):
        self.sent_chunks.append({"commit": True})

    async def close(self):
        self.closed = True


def _mock_sounddevice():
    """Return a mock sounddevice module that won't touch real hardware."""
    mock_sd = MagicMock()
    mock_stream = MagicMock()
    mock_stream.read.return_value = (np.zeros(1600, dtype="int16"), False)
    mock_sd.InputStream.return_value = mock_stream
    return mock_sd


# ---------------------------------------------------------------------------
# Successful transcription
# ---------------------------------------------------------------------------

class TestRealtimeSTTSuccess:

    async def test_successful_transcription(self):
        """session_started -> committed_transcript -> result with text."""
        conn = FakeConnection()

        async def fake_connect(opts):
            # Fire session_started after a small delay so handlers are registered first
            async def _fire_later():
                await asyncio.sleep(0.1)
                conn.fire("session_started", {})
            asyncio.create_task(_fire_later())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            task = asyncio.create_task(realtime_transcribe(
                api_key="test-key",
                max_duration=5.0,
                min_duration=0.1,
            ))

            # Give event loop time to start, then fire committed transcript.
            # A commit is transcript data, not a stop signal; VAD finalization
            # or another terminal condition must end the turn.
            await asyncio.sleep(0.3)
            conn.fire("committed_transcript", {"text": "hello from mic"})
            conn.fire("close")

            result = await asyncio.wait_for(task, timeout=5.0)

        assert result is not None
        assert result["text"] == "hello from mic"
        assert result["provider"] == "elevenlabs"
        assert result["endpoint"] == "scribe_v2_realtime"

    async def test_close_error_after_commit_does_not_overwrite(self):
        """WebSocket close/error after a committed transcript must NOT overwrite the text."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
            asyncio.create_task(_fire())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            task = asyncio.create_task(realtime_transcribe(
                api_key="test-key",
                max_duration=5.0,
                min_duration=0.1,
            ))

            await asyncio.sleep(0.3)
            # First: commit text
            conn.fire("committed_transcript", {"text": "good text"})
            # Then: error fires (e.g. WebSocket close race condition)
            await asyncio.sleep(0.05)
            conn.fire("error", {"message": "connection closed unexpectedly"})

            result = await asyncio.wait_for(task, timeout=5.0)

        # The committed text MUST survive the post-commit error
        assert result["text"] == "good text"
        assert "error_type" not in result

    async def test_local_vad_finalize_triggers_commit_from_main_loop(self):
        """Local VAD finalize callback should cause the main loop to commit and finish."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
                await asyncio.sleep(0.15)
                conn.fire("committed_transcript", {"text": "finalized text"})
            asyncio.create_task(_fire())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch(
                "voice_mode.elevenlabs_realtime_stt._stream_microphone_with_local_vad",
                new=AsyncMock(side_effect=lambda *args, **kwargs: kwargs["on_local_finalize"]()),
            ),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(
                    api_key="test-key",
                    max_duration=5.0,
                    min_duration=0.1,
                ),
                timeout=5.0,
            )

        assert result["text"] == "finalized text"
        assert {"commit": True} in conn.sent_chunks

    async def test_stop_policy_controls_realtime_vad_thresholds(self):
        """A supplied stop policy should drive realtime VAD timing and threshold."""
        conn = FakeConnection()
        observed = {}

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
                await asyncio.sleep(0.15)
                conn.fire("committed_transcript", {"text": "policy text"})
            asyncio.create_task(_fire())
            return conn

        async def fake_stream(connection, max_duration, min_duration, start_time,
                              silence_threshold_secs, vad_prob_threshold,
                              disable_silence_detection, **kwargs):
            observed.update(
                {
                    "max_duration": max_duration,
                    "min_duration": min_duration,
                    "silence_threshold_secs": silence_threshold_secs,
                    "vad_prob_threshold": vad_prob_threshold,
                    "disable_silence_detection": disable_silence_detection,
                }
            )
            kwargs["on_local_finalize"]()

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch(
                "voice_mode.elevenlabs_realtime_stt._stream_microphone_with_local_vad",
                new=AsyncMock(side_effect=fake_stream),
            ),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe
            from voice_mode.silero_vad import build_stop_policy

            policy = build_stop_policy(
                max_duration=4.0,
                min_duration=0.2,
                vad_aggressiveness=3,
            )
            result = await asyncio.wait_for(
                realtime_transcribe(api_key="test-key", stop_policy=policy),
                timeout=5.0,
            )

        assert result["text"] == "policy text"
        assert observed == {
            "max_duration": 4.0,
            "min_duration": 0.2,
            "silence_threshold_secs": 1.0,
            "vad_prob_threshold": 0.85,
            "disable_silence_detection": False,
        }


# ---------------------------------------------------------------------------
# Error scenarios
# ---------------------------------------------------------------------------

class TestRealtimeSTTErrors:

    async def test_resource_exhausted_sets_error(self):
        """resource_exhausted error (no prior commit) -> error_message is set."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
            asyncio.create_task(_fire())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            task = asyncio.create_task(realtime_transcribe(
                api_key="test-key",
                max_duration=5.0,
                min_duration=0.1,
            ))

            await asyncio.sleep(0.3)
            conn.fire("error", {"error": "resource_exhausted", "message": "Too many concurrent sessions"})

            result = await asyncio.wait_for(task, timeout=5.0)

        assert result["error_type"] == "connection_failed"
        assert "resource_exhausted" in result["error"] or "Too many" in result["error"]

    async def test_connection_timeout(self):
        """Connection timeout returns connection_failed."""
        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch("voice_mode.elevenlabs_realtime_stt.SESSION_START_TIMEOUT", 0.1),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await realtime_transcribe(
                api_key="test-key",
                max_duration=2.0,
                min_duration=0.1,
            )

        assert result["error_type"] == "connection_failed"
        assert "timed out" in result["error"]

    async def test_connection_exception(self):
        """Generic connection exception returns connection_failed."""
        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(
            side_effect=ConnectionRefusedError("Connection refused")
        )

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await realtime_transcribe(
                api_key="test-key",
                max_duration=2.0,
                min_duration=0.1,
            )

        assert result["error_type"] == "connection_failed"
        assert "Connection refused" in result["error"]

    async def test_session_start_timeout(self):
        """Server connects but never sends session_started -> timeout."""
        conn = FakeConnection()

        async def fake_connect(opts):
            # Connect succeeds but session_started never fires
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch("voice_mode.elevenlabs_realtime_stt.SESSION_START_TIMEOUT", 0.3),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(
                    api_key="test-key",
                    max_duration=2.0,
                    min_duration=0.1,
                ),
                timeout=5.0,
            )

        assert result["error_type"] == "connection_failed"
        assert "session_started" in result["error"].lower() or "session start" in result["error"].lower()

    async def test_no_speech_detected(self):
        """Session starts, no committed transcript before max_duration -> no_speech."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
            asyncio.create_task(_fire())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(
                    api_key="test-key",
                    max_duration=0.5,  # Very short so test completes quickly
                    min_duration=0.1,
                ),
                timeout=5.0,
            )

        assert result["error_type"] == "no_speech"
        assert result["provider"] == "elevenlabs"

    async def test_local_vad_partial_commit_uses_cached_batch_recovery(self, tmp_path):
        """A short VAD-finalized commit from a longer cached recording should be recovered."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
                await asyncio.sleep(0.2)
                conn.fire("committed_transcript", {"text": "The bro bro"})
            asyncio.create_task(_fire())
            return conn

        async def fake_stream(connection, *args, **kwargs):
            audio = np.zeros(16000 * 12, dtype=np.int16)
            from voice_mode import elevenlabs_realtime_stt as mod

            mod._write_cached_audio_files([audio])
            kwargs["on_local_finalize"]()

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        def fake_batch(audio_file, **kwargs):
            return {"text": "The bro bro this is the rest of the recovered sentence from cached audio"}

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch("voice_mode.elevenlabs_realtime_stt.CACHE_DIR", tmp_path),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_RAW", tmp_path / "last_recording.raw"),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_WAV", tmp_path / "last_recording.wav"),
            patch("voice_mode.elevenlabs_realtime_stt._stream_microphone_with_local_vad", new=AsyncMock(side_effect=fake_stream)),
            patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", side_effect=fake_batch),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(api_key="test-key", max_duration=20.0, min_duration=0.1),
                timeout=5.0,
            )

        assert result["endpoint"] == "scribe_v2_batch_fallback"
        assert result["text"] == "The bro bro this is the rest of the recovered sentence from cached audio"
        assert result["metrics"]["fallback_reason"] == "suspected_truncated_realtime_commit"
        assert result["metrics"]["replaced_realtime_partial"] == "The bro bro"

    async def test_realtime_commit_does_not_stop_while_mic_stream_is_active(self, tmp_path):
        """Realtime commits should not stop listening while the mic stream continues."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
                await asyncio.sleep(0.1)
                conn.fire("committed_transcript", {"text": "first part"})
                await asyncio.sleep(0.1)
                conn.fire("committed_transcript", {"text": "second part"})
            asyncio.create_task(_fire())
            return conn

        async def fake_stream(connection, *args, **kwargs):
            audio = np.zeros(16000 * 2, dtype=np.int16)
            from voice_mode import elevenlabs_realtime_stt as mod

            mod._write_cached_audio_files([audio])
            await asyncio.sleep(0.4)
            kwargs["on_local_finalize"]()

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch("voice_mode.elevenlabs_realtime_stt.CACHE_DIR", tmp_path),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_RAW", tmp_path / "last_recording.raw"),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_WAV", tmp_path / "last_recording.wav"),
            patch("voice_mode.elevenlabs_realtime_stt._stream_microphone_with_local_vad", new=AsyncMock(side_effect=fake_stream)),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(api_key="test-key", max_duration=5.0, min_duration=0.1),
                timeout=5.0,
            )

        assert result["text"] == "first part second part"
        assert result["endpoint"] == "scribe_v2_realtime"

    async def test_no_committed_transcript_batch_fallback_uses_cached_wav(self, tmp_path):
        """If realtime returns no transcript but audio was captured, batch fallback should recover it."""
        conn = FakeConnection()

        async def fake_connect(opts):
            async def _fire():
                await asyncio.sleep(0.05)
                conn.fire("session_started", {})
            asyncio.create_task(_fire())
            return conn

        mock_client = MagicMock()
        mock_client.speech_to_text.realtime.connect = AsyncMock(side_effect=fake_connect)
        captured = {}

        def fake_batch(audio_file, **kwargs):
            captured["name"] = getattr(audio_file, "name", "")
            with wave.open(audio_file, "rb") as wf:
                captured["frames"] = wf.getnframes()
            return {"text": "recovered from cached audio"}

        with (
            patch("voice_mode.elevenlabs_realtime_stt.sd", _mock_sounddevice()),
            patch("elevenlabs.client.ElevenLabs", return_value=mock_client),
            patch("voice_mode.elevenlabs_realtime_stt.CACHE_DIR", tmp_path),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_RAW", tmp_path / "last_recording.raw"),
            patch("voice_mode.elevenlabs_realtime_stt.LAST_RECORDING_WAV", tmp_path / "last_recording.wav"),
            patch("voice_mode.elevenlabs_client.elevenlabs_stt_batch", side_effect=fake_batch),
        ):
            from voice_mode.elevenlabs_realtime_stt import realtime_transcribe

            result = await asyncio.wait_for(
                realtime_transcribe(
                    api_key="test-key",
                    max_duration=1.2,
                    min_duration=0.1,
                    disable_silence_detection=True,
                ),
                timeout=5.0,
            )

        assert result["text"] == "recovered from cached audio"
        assert result["endpoint"] == "scribe_v2_batch_fallback"
        assert result["audio_file"].endswith("last_recording.wav")
        assert captured["name"] == "cached_recording.wav"
        assert captured["frames"] > 16000
