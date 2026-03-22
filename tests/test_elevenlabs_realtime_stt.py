"""Tests for ElevenLabs Realtime STT (WebSocket-based).

Covers voice_mode/elevenlabs_realtime_stt.py::realtime_transcribe.
All WebSocket / sounddevice interactions are mocked.
"""

import asyncio
import pytest
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
            loop = asyncio.get_event_loop()
            loop.call_soon(lambda: conn.fire("session_started", {}))
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

            # Give event loop time to start, then fire committed transcript
            await asyncio.sleep(0.3)
            conn.fire("committed_transcript", {"text": "hello from mic"})

            result = await asyncio.wait_for(task, timeout=5.0)

        assert result is not None
        assert result["text"] == "hello from mic"
        assert result["provider"] == "elevenlabs"
        assert result["endpoint"] == "scribe_v2_realtime"

    async def test_close_error_after_commit_does_not_overwrite(self):
        """WebSocket close/error after a committed transcript must NOT overwrite the text."""
        conn = FakeConnection()

        async def fake_connect(opts):
            loop = asyncio.get_event_loop()
            loop.call_soon(lambda: conn.fire("session_started", {}))
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


# ---------------------------------------------------------------------------
# Error scenarios
# ---------------------------------------------------------------------------

class TestRealtimeSTTErrors:

    async def test_resource_exhausted_sets_error(self):
        """resource_exhausted error (no prior commit) -> error_message is set."""
        conn = FakeConnection()

        async def fake_connect(opts):
            loop = asyncio.get_event_loop()
            loop.call_soon(lambda: conn.fire("session_started", {}))
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
            loop = asyncio.get_event_loop()
            loop.call_soon(lambda: conn.fire("session_started", {}))
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
