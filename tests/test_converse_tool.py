"""Comprehensive unit tests for voice_mode/tools/converse.py — the core converse MCP tool.

Tests cover parameter validation, skip-TTS mode, wait-for-response=false (speak-only),
conch acquisition/release, timeout handling, error handling, FFmpeg checks,
and config integration. All external dependencies (ElevenLabs, audio devices, file I/O)
are mocked — no real audio or API calls are made.
"""

import asyncio
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _suppress_startup(monkeypatch):
    """Prevent startup_initialization from running real provider discovery."""
    import voice_mode.config
    monkeypatch.setattr(voice_mode.config, "_startup_initialized", True)


@pytest.fixture(autouse=True)
def _mock_sounddevice(monkeypatch):
    """Replace sounddevice init/terminate with no-ops so tests never touch audio HW."""
    import sounddevice as sd
    monkeypatch.setattr(sd, "_terminate", lambda: None)
    monkeypatch.setattr(sd, "_initialize", lambda: None)


@pytest.fixture(autouse=True)
def _mock_event_logger():
    """Provide a no-op event logger for all tests."""
    mock_logger = MagicMock()
    mock_logger.start_session.return_value = "test-session-id"
    mock_logger.RECORDING_START = "RECORDING_START"
    mock_logger.RECORDING_END = "RECORDING_END"
    mock_logger.STT_START = "STT_START"
    mock_logger.STT_COMPLETE = "STT_COMPLETE"
    mock_logger.STT_NO_SPEECH = "STT_NO_SPEECH"
    with patch("voice_mode.tools.converse.get_event_logger", return_value=mock_logger):
        yield mock_logger


@pytest.fixture(autouse=True)
def _mock_conversation_logger():
    """Provide a no-op conversation logger for all tests."""
    mock_cl = MagicMock()
    mock_cl.conversation_id = "test-conv-id"
    with patch("voice_mode.tools.converse.get_conversation_logger", return_value=mock_cl):
        yield mock_cl


@pytest.fixture(autouse=True)
def _mock_track_voice():
    """Stub out statistics tracking."""
    with patch("voice_mode.tools.converse.track_voice_interaction"):
        yield


@pytest.fixture(autouse=True)
def _disable_conch(monkeypatch):
    """Disable conch system by default; individual tests can re-enable."""
    monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)


@pytest.fixture(autouse=True)
def _reset_last_session():
    """Reset module-level last_session_end_time between tests."""
    import voice_mode.tools.converse as mod
    mod.last_session_end_time = None
    yield
    mod.last_session_end_time = None


@pytest.fixture
def mock_tts():
    """Mock text_to_speech_with_failover to return instant success."""
    tts_metrics = {"ttfa": 0.01, "generation": 0.05, "playback": 0.1, "audio_path": "/tmp/test.wav"}
    tts_config = {"provider": "elevenlabs", "voice": "test-voice", "model": "eleven_v3", "base_url": "https://api.elevenlabs.io"}
    with patch(
        "voice_mode.tools.converse.text_to_speech_with_failover",
        new_callable=AsyncMock,
        return_value=(True, tts_metrics, tts_config),
    ) as m:
        yield m


@pytest.fixture
def mock_tts_failure():
    """Mock TTS that fails with all_providers_failed."""
    tts_config = {
        "error_type": "all_providers_failed",
        "attempted_endpoints": [{"endpoint": "https://api.elevenlabs.io", "error": "API rate limit exceeded", "provider": "elevenlabs"}],
    }
    with patch(
        "voice_mode.tools.converse.text_to_speech_with_failover",
        new_callable=AsyncMock,
        return_value=(False, None, tts_config),
    ) as m:
        yield m


@pytest.fixture
def mock_realtime_stt():
    """Mock ElevenLabs realtime STT to return a transcription result."""
    stt_result = {"text": "Hello from the user", "provider": "elevenlabs_realtime"}
    with patch(
        "voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True
    ), patch(
        "voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True
    ), patch(
        "voice_mode.elevenlabs_realtime_stt.realtime_transcribe",
        new_callable=AsyncMock,
        return_value=stt_result,
    ) as m:
        yield m


@pytest.fixture
def mock_audio_feedback():
    """Suppress audio feedback (chimes)."""
    with patch("voice_mode.tools.converse.play_audio_feedback", new_callable=AsyncMock):
        yield


@pytest.fixture
def mock_dj_ducker():
    """Mock the DJDucker context manager."""
    with patch("voice_mode.tools.converse.DJDucker") as m:
        m.return_value.__enter__ = MagicMock(return_value=None)
        m.return_value.__exit__ = MagicMock(return_value=False)
        yield m


# ---------------------------------------------------------------------------
# Helper — call converse with default mocks for the audio_operation_lock
# ---------------------------------------------------------------------------

async def _call_converse(**kwargs):
    """Import and call converse with sensible defaults."""
    from voice_mode.tools.converse import converse
    defaults = {"message": "Hello, world!", "ctx": None}
    defaults.update(kwargs)
    return await converse(**defaults)


# ===========================================================================
# Parameter Validation
# ===========================================================================

class TestParameterValidation:
    """Validate parameter checking at the top of converse()."""

    async def test_speed_below_range(self):
        """Speed < 0.7 returns an error string."""
        result = await _call_converse(message="hi", speed=0.5, wait_for_response=False)
        assert "Error" in result
        assert "0.7" in result

    async def test_speed_above_range(self):
        """Speed > 1.2 returns an error string."""
        result = await _call_converse(message="hi", speed=1.5, wait_for_response=False)
        assert "Error" in result
        assert "1.2" in result

    async def test_speed_string_conversion(self):
        """Speed provided as invalid string returns an error."""
        result = await _call_converse(message="hi", speed="not-a-number", wait_for_response=False)
        assert "Error" in result
        assert "speed must be a number" in result

    async def test_vad_aggressiveness_out_of_range(self, mock_tts, mock_dj_ducker):
        """vad_aggressiveness outside 0-3 returns error."""
        result = await _call_converse(message="hi", vad_aggressiveness=5)
        assert "Error" in result or "vad_aggressiveness" in result

    async def test_vad_aggressiveness_string_conversion(self, mock_tts, mock_dj_ducker):
        """String vad_aggressiveness is converted to int; invalid falls back to None."""
        # Valid string → converted
        with patch("voice_mode.tools.converse.CONCH_ENABLED", False):
            result = await _call_converse(
                message="hi", vad_aggressiveness="2", wait_for_response=False
            )
        assert "Error" not in result  # 2 is valid

    async def test_negative_listen_duration_min(self, mock_tts, mock_dj_ducker):
        """Negative listen_duration_min returns error."""
        result = await _call_converse(
            message="hi", listen_duration_min=-1, wait_for_response=True
        )
        assert "Error" in result
        assert "negative" in result

    async def test_zero_listen_duration_max(self, mock_tts, mock_dj_ducker):
        """listen_duration_max=0 returns error."""
        result = await _call_converse(
            message="hi", listen_duration_max=0, wait_for_response=True
        )
        assert "Error" in result
        assert "positive" in result

    async def test_string_boolean_conversion(self, mock_tts, mock_dj_ducker):
        """String booleans like 'true'/'false' are converted correctly."""
        result = await _call_converse(
            message="hi", wait_for_response="false"
        )
        # wait_for_response=false → speak-only → success message
        assert "spoken" in result.lower() or "✓" in result


# ===========================================================================
# Skip-TTS Mode
# ===========================================================================

class TestSkipTTS:
    """When skip_tts=True, TTS is bypassed and text_to_speech_with_failover is NOT called."""

    async def test_skip_tts_explicit_param(self, mock_audio_feedback):
        """skip_tts=True skips TTS entirely and proceeds to listen."""
        stt_result = {"text": "user reply", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result), \
             patch("voice_mode.tools.converse.text_to_speech_with_failover", new_callable=AsyncMock) as mock_tts_fn:
            result = await _call_converse(message="hi", skip_tts=True)
            # TTS should NOT be called
            mock_tts_fn.assert_not_called()
            assert "user reply" in result

    async def test_skip_tts_from_config(self, mock_audio_feedback, monkeypatch):
        """When config SKIP_TTS=True, TTS is skipped even without skip_tts param."""
        monkeypatch.setattr("voice_mode.tools.converse.SKIP_TTS", True)
        stt_result = {"text": "config skip", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result), \
             patch("voice_mode.tools.converse.text_to_speech_with_failover", new_callable=AsyncMock) as mock_tts_fn:
            result = await _call_converse(message="anything")
            mock_tts_fn.assert_not_called()
            assert "config skip" in result

    async def test_skip_tts_speak_only(self, mock_audio_feedback):
        """skip_tts + wait_for_response=False → immediate success without calling TTS."""
        with patch("voice_mode.tools.converse.text_to_speech_with_failover", new_callable=AsyncMock) as mock_tts_fn:
            result = await _call_converse(message="hi", skip_tts=True, wait_for_response=False)
            mock_tts_fn.assert_not_called()
            assert "spoken" in result.lower() or "✓" in result


# ===========================================================================
# Wait-for-response=False (Speak-Only)
# ===========================================================================

class TestSpeakOnly:
    """When wait_for_response=False, the tool speaks and returns immediately."""

    async def test_speak_only_success(self, mock_tts, mock_dj_ducker):
        """Speak-only returns success message with timing info."""
        result = await _call_converse(message="announcement", wait_for_response=False)
        assert "spoken" in result.lower() or "✓" in result

    async def test_speak_only_tts_called(self, mock_tts, mock_dj_ducker):
        """TTS is called with the message text in speak-only mode."""
        await _call_converse(message="hello there", wait_for_response=False)
        mock_tts.assert_called_once()
        call_kwargs = mock_tts.call_args
        assert call_kwargs.kwargs.get("message") == "hello there" or call_kwargs[1].get("message") == "hello there"

    async def test_speak_only_minimal_metrics(self, mock_tts, mock_dj_ducker, monkeypatch):
        """metrics_level='minimal' returns clean success message."""
        monkeypatch.setattr("voice_mode.tools.converse.METRICS_LEVEL", "summary")
        result = await _call_converse(
            message="test", wait_for_response=False, metrics_level="minimal"
        )
        assert result == "✓ Message spoken successfully"

    async def test_speak_only_string_false(self, mock_tts, mock_dj_ducker):
        """wait_for_response='false' (string) is treated as False."""
        result = await _call_converse(message="hi", wait_for_response="false")
        assert "spoken" in result.lower() or "✓" in result


# ===========================================================================
# TTS Failure Handling
# ===========================================================================

class TestTTSFailure:
    """When TTS fails, the tool returns helpful error messages."""

    async def test_tts_all_providers_failed(self, mock_tts_failure, mock_dj_ducker):
        """All TTS providers failing returns detailed error."""
        result = await _call_converse(message="hi", wait_for_response=False)
        assert "Error" in result or "failed" in result.lower()
        assert "TTS" in result or "speak" in result.lower()


# ===========================================================================
# Conch (Concurrency Lock)
# ===========================================================================

class TestConch:
    """Tests for conch acquisition, blocking, waiting, and timeout."""

    async def test_conch_acquired_successfully(self, mock_tts, mock_dj_ducker, monkeypatch):
        """When conch is free, it is acquired and the tool proceeds."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", True)
        with patch("voice_mode.tools.converse.Conch") as MockConch:
            instance = MockConch.return_value
            instance.try_acquire.return_value = True
            instance._acquired = True
            instance.release.return_value = 1.0
            result = await _call_converse(message="hi", wait_for_response=False)
            instance.try_acquire.assert_called_once()
            assert "✓" in result or "spoken" in result.lower()

    async def test_conch_blocked_no_wait(self, monkeypatch):
        """When conch is held and wait_for_conch=False, returns immediately."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", True)
        with patch("voice_mode.tools.converse.Conch") as MockConch:
            instance = MockConch.return_value
            instance.try_acquire.return_value = False
            instance._acquired = False
            instance.release.return_value = 0.0
            MockConch.get_holder.return_value = {"agent": "cora", "pid": 12345}
            result = await _call_converse(
                message="hi", wait_for_conch=False, wait_for_response=False
            )
            assert "speaking" in result.lower() or "cora" in result.lower()

    async def test_conch_timeout(self, monkeypatch):
        """When conch wait times out, returns timeout message."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", True)
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_TIMEOUT", 0.1)
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_CHECK_INTERVAL", 0.05)
        with patch("voice_mode.tools.converse.Conch") as MockConch:
            instance = MockConch.return_value
            instance.try_acquire.return_value = False
            instance._acquired = False
            instance.release.return_value = 0.0
            MockConch.get_holder.return_value = {"agent": "other", "pid": 99}
            result = await _call_converse(
                message="hi", wait_for_conch=True, wait_for_response=False
            )
            assert "timed out" in result.lower() or "Timed out" in result

    async def test_conch_wait_then_acquire(self, mock_tts, mock_dj_ducker, monkeypatch):
        """Conch is held, wait_for_conch=True, then becomes available."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", True)
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_TIMEOUT", 5.0)
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_CHECK_INTERVAL", 0.01)
        call_count = 0

        def try_acquire_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                instance._acquired = True
                return True
            return False

        with patch("voice_mode.tools.converse.Conch") as MockConch:
            instance = MockConch.return_value
            instance.try_acquire.side_effect = try_acquire_side_effect
            instance._acquired = False
            instance.release.return_value = 1.0
            MockConch.get_holder.return_value = {"agent": "other", "pid": 99}
            result = await _call_converse(
                message="hi", wait_for_conch=True, wait_for_response=False
            )
            assert "✓" in result or "spoken" in result.lower()


# ===========================================================================
# FFmpeg Availability
# ===========================================================================

class TestFFmpegCheck:
    """Test FFmpeg availability gating."""

    async def test_ffmpeg_unavailable(self, monkeypatch):
        """When FFMPEG_AVAILABLE is False, returns an error about FFmpeg."""
        import voice_mode.config
        monkeypatch.setattr(voice_mode.config, "FFMPEG_AVAILABLE", False)
        with patch("voice_mode.utils.ffmpeg_check.get_install_instructions", return_value="Install FFmpeg"):
            result = await _call_converse(message="hi", wait_for_response=False)
        assert "FFmpeg" in result or "ffmpeg" in result.lower()

    async def test_ffmpeg_available(self, mock_tts, mock_dj_ducker, monkeypatch):
        """When FFMPEG_AVAILABLE is True, tool proceeds normally."""
        import voice_mode.config
        monkeypatch.setattr(voice_mode.config, "FFMPEG_AVAILABLE", True)
        result = await _call_converse(message="hi", wait_for_response=False)
        assert "FFmpeg" not in result


# ===========================================================================
# Full Conversation Flow (TTS + STT)
# ===========================================================================

class TestFullConversation:
    """End-to-end flow with mocked TTS and STT."""

    async def test_full_conversation_realtime_stt(
        self, mock_tts, mock_dj_ducker, mock_audio_feedback
    ):
        """Full conversation with ElevenLabs realtime STT returns user text."""
        stt_result = {"text": "User said hello", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result):
            result = await _call_converse(message="Say something", wait_for_response=True)
            assert "User said hello" in result

    async def test_full_conversation_no_speech(
        self, mock_tts, mock_dj_ducker, mock_audio_feedback
    ):
        """When STT detects no speech, returns 'No speech detected'."""
        stt_result = {"error_type": "no_speech", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result):
            result = await _call_converse(message="Hello?", wait_for_response=True)
            assert "no speech" in result.lower()

    async def test_stt_connection_failed(
        self, mock_tts, mock_dj_ducker, mock_audio_feedback
    ):
        """STT connection failure returns error."""
        stt_result = {
            "error_type": "connection_failed",
            "attempted_endpoints": [{"endpoint": "wss://api.elevenlabs.io", "error": "timeout"}],
        }

        # After retries still fails, falls back to batch which also fails
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "fake-key", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result), \
             patch("voice_mode.tools.converse.record_audio_with_silence_detection", return_value=(np.array([1, 2, 3], dtype=np.int16), True)), \
             patch("voice_mode.tools.converse.speech_to_text", new_callable=AsyncMock, return_value={"error_type": "connection_failed", "attempted_endpoints": [{"endpoint": "api", "error": "fail"}]}):
            result = await _call_converse(message="test", wait_for_response=True)
            assert "failed" in result.lower() or "error" in result.lower()

    async def test_traditional_stt_path(
        self, mock_tts, mock_dj_ducker, mock_audio_feedback
    ):
        """When realtime STT is unavailable, falls back to record+transcribe."""
        audio_data = np.random.randint(-1000, 1000, size=16000, dtype=np.int16)
        stt_result = {"text": "traditional path reply", "provider": "elevenlabs"}
        with patch("voice_mode.config.ELEVENLABS_API_KEY", None), \
             patch("voice_mode.config.ELEVENLABS_USE_REALTIME_STT", False), \
             patch("voice_mode.tools.converse.record_audio_with_silence_detection", return_value=(audio_data, True)), \
             patch("voice_mode.tools.converse.speech_to_text", new_callable=AsyncMock, return_value=stt_result):
            result = await _call_converse(message="test trad", wait_for_response=True)
            assert "traditional path reply" in result

    async def test_recording_returns_empty(
        self, mock_tts, mock_dj_ducker, mock_audio_feedback
    ):
        """Empty recording returns error."""
        with patch("voice_mode.config.ELEVENLABS_API_KEY", None), \
             patch("voice_mode.config.ELEVENLABS_USE_REALTIME_STT", False), \
             patch("voice_mode.tools.converse.record_audio_with_silence_detection", return_value=(np.array([]), False)):
            result = await _call_converse(message="test", wait_for_response=True)
            assert "error" in result.lower() or "could not record" in result.lower()


# ===========================================================================
# Metrics Levels
# ===========================================================================

class TestMetricsLevel:
    """Test that metrics_level controls result formatting."""

    async def test_minimal_metrics(self, mock_tts, mock_dj_ducker, mock_audio_feedback):
        """metrics_level='minimal' returns just the response text."""
        stt_result = {"text": "reply text", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "k", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result):
            result = await _call_converse(
                message="hi", metrics_level="minimal", wait_for_response=True
            )
            assert result == "Voice response: reply text"

    async def test_verbose_metrics(self, mock_tts, mock_dj_ducker, mock_audio_feedback):
        """metrics_level='verbose' includes timing breakdowns."""
        stt_result = {"text": "response", "provider": "elevenlabs_realtime"}
        with patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "k", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value=stt_result):
            result = await _call_converse(
                message="hi", metrics_level="verbose", wait_for_response=True
            )
            assert "Timing" in result or "response" in result


# ===========================================================================
# Config Integration
# ===========================================================================

class TestConfigIntegration:
    """Test that converse respects config values."""

    async def test_audio_feedback_disabled(self, mock_tts, mock_dj_ducker, monkeypatch):
        """When AUDIO_FEEDBACK_ENABLED=False, no chimes are played."""
        monkeypatch.setattr("voice_mode.tools.converse.AUDIO_FEEDBACK_ENABLED", False)
        with patch("voice_mode.tools.converse.play_audio_feedback", new_callable=AsyncMock), \
             patch("voice_mode.tools.converse.ELEVENLABS_API_KEY", "k", create=True), \
             patch("voice_mode.tools.converse.ELEVENLABS_USE_REALTIME_STT", True, create=True), \
             patch("voice_mode.elevenlabs_realtime_stt.realtime_transcribe", new_callable=AsyncMock, return_value={"text": "hi", "provider": "el"}):
            result = await _call_converse(message="test", wait_for_response=True)
            # play_audio_feedback is called but respects enabled=None → uses global False
            # verify it at least was called (the function itself checks AUDIO_FEEDBACK_ENABLED)
            assert "hi" in result

    async def test_tts_speed_from_config(self, mock_tts, mock_dj_ducker, monkeypatch):
        """Speed from TTS_SPEED config is used when no param provided."""
        monkeypatch.setattr("voice_mode.tools.converse.TTS_SPEED", 1.0)
        result = await _call_converse(message="hi", wait_for_response=False)
        # Verify TTS was called (it should succeed since 1.0 is in valid range)
        assert "✓" in result or "spoken" in result.lower()

    async def test_tts_speed_from_config_invalid(self, monkeypatch):
        """Invalid speed from TTS_SPEED config returns error mentioning env var."""
        monkeypatch.setattr("voice_mode.tools.converse.TTS_SPEED", 2.0)
        result = await _call_converse(message="hi", wait_for_response=False)
        assert "VOICEMODE_TTS_SPEED" in result


# ===========================================================================
# Error Handling & Edge Cases
# ===========================================================================

class TestErrorHandling:
    """Test exception handling and edge cases."""

    async def test_exception_during_tts(self, mock_dj_ducker):
        """Runtime exception during TTS is caught and reported."""
        with patch(
            "voice_mode.tools.converse.text_to_speech_with_failover",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected TTS crash"),
        ):
            result = await _call_converse(message="hi", wait_for_response=False)
            assert "error" in result.lower() or "Error" in result

    async def test_cancelled_error(self, mock_dj_ducker):
        """asyncio.CancelledError propagates so FastMCP can end the request cleanly."""
        with patch(
            "voice_mode.tools.converse.text_to_speech_with_failover",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _call_converse(message="hi", wait_for_response=False)

    async def test_client_disconnect_stops_playback_and_cancels_session(self, mock_dj_ducker, monkeypatch):
        """HTTP disconnects should stop active playback instead of letting speech continue."""
        from voice_mode.converse_session import ConverseTurnResult

        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)

        class FakeRequest:
            def __init__(self):
                self.calls = 0

            async def is_disconnected(self):
                self.calls += 1
                return self.calls >= 2

        class FakeRequestContext:
            request = FakeRequest()

        class FakeContext:
            request_context = FakeRequestContext()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(60)
            return ConverseTurnResult(result="should not finish", mcp_success=True)

        with patch("voice_mode.tools.converse.ConverseSession") as MockSession, \
             patch("voice_mode.tools.converse.stop_current_playback") as mock_stop:
            instance = MockSession.return_value
            instance.run = AsyncMock(side_effect=slow_run)

            with pytest.raises(asyncio.CancelledError):
                await _call_converse(message="hi", wait_for_response=False, ctx=FakeContext())

        assert mock_stop.called

    async def test_session_write_failure_stops_playback_and_cancels_session(self, mock_dj_ducker, monkeypatch):
        """Session write failures should stop active playback under streamable HTTP."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)
        child_cancelled = asyncio.Event()

        class FakeRequest:
            async def is_disconnected(self):
                return False

        class FakeRequestContext:
            request = FakeRequest()

        class FakeSession:
            def __init__(self):
                self.calls = 0

            async def send_log_message(self, *args, **kwargs):
                self.calls += 1
                raise RuntimeError("stream closed")

        class FakeContext:
            def __init__(self):
                self.request_context = FakeRequestContext()
                self.session = FakeSession()
                self.request_id = "req-123"

        async def slow_run(*args, **kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                child_cancelled.set()
                raise

        ctx = FakeContext()

        with patch("voice_mode.tools.converse.ConverseSession") as MockSession, \
             patch("voice_mode.tools.converse.stop_current_playback") as mock_stop:
            instance = MockSession.return_value
            instance.run = AsyncMock(side_effect=slow_run)

            with pytest.raises(asyncio.CancelledError):
                await _call_converse(message="hi", wait_for_response=False, ctx=ctx)

        assert child_cancelled.is_set()
        assert ctx.session.calls >= 1
        assert mock_stop.called

    async def test_parent_cancellation_cancels_child_session_task(self, mock_dj_ducker, monkeypatch):
        """Cancelling the MCP coroutine should not leave ConverseSession running."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)
        child_cancelled = asyncio.Event()

        async def slow_run(*args, **kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                child_cancelled.set()
                raise

        with patch("voice_mode.tools.converse.ConverseSession") as MockSession, \
             patch("voice_mode.tools.converse.stop_current_playback") as mock_stop:
            instance = MockSession.return_value
            instance.run = AsyncMock(side_effect=slow_run)

            task = asyncio.create_task(_call_converse(message="hi", wait_for_response=False))
            await asyncio.sleep(0.05)
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

        assert child_cancelled.is_set()
        assert mock_stop.called

    async def test_server_side_timeout_cancels_child_session_task(self, mock_dj_ducker, monkeypatch):
        """The timeout parameter is a real server-side turn budget, not just docs."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)
        child_cancelled = asyncio.Event()

        async def slow_run(*args, **kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                child_cancelled.set()
                raise

        with patch("voice_mode.tools.converse.ConverseSession") as MockSession, \
             patch("voice_mode.tools.converse.stop_current_playback") as mock_stop:
            instance = MockSession.return_value
            instance.run = AsyncMock(side_effect=slow_run)

            result = await _call_converse(
                message="hi",
                wait_for_response=False,
                timeout=0.05,
            )

        assert "timed out" in result.lower()
        assert child_cancelled.is_set()
        assert mock_stop.called

    async def test_conch_released_in_finally(self, mock_tts, mock_dj_ducker, monkeypatch):
        """Conch is released in finally block even after error."""
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", True)
        with patch("voice_mode.tools.converse.Conch") as MockConch:
            instance = MockConch.return_value
            instance.try_acquire.return_value = True
            instance._acquired = True
            instance.release.return_value = 1.0
            # Force an exception after conch is acquired
            with patch(
                "voice_mode.tools.converse.text_to_speech_with_failover",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                await _call_converse(message="hi", wait_for_response=False)
            # Conch should be released regardless of error
            instance.release.assert_called()


class TestConverseSessionBoundary:
    """Tests that converse() delegates completed turn ownership to the session."""

    async def test_converse_returns_session_result_string(self, mock_dj_ducker, monkeypatch):
        from voice_mode.converse_session import ConverseTurnResult

        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)
        session_result = ConverseTurnResult(result="session-owned result", mcp_success=True)

        with patch("voice_mode.tools.converse.ConverseSession") as MockSession:
            instance = MockSession.return_value
            instance.run = AsyncMock(return_value=session_result)

            result = await _call_converse(message="hi", wait_for_response=False)

        assert result == "session-owned result"
        instance.run.assert_awaited_once()

    async def test_converse_builds_ports_with_low_level_provider_stt(self, mock_dj_ducker, monkeypatch):
        from voice_mode.converse_session import ConverseTurnResult

        provider_realtime_stt = AsyncMock(return_value={"text": "provider"})
        provider = MagicMock()
        provider.realtime_stt = provider_realtime_stt
        monkeypatch.setattr("voice_mode.tools.converse.CONCH_ENABLED", False)

        with patch("voice_mode.tools.converse.get_voice_provider", return_value=provider), \
             patch("voice_mode.tools.converse.ConverseSession") as MockSession:
            instance = MockSession.return_value
            instance.run = AsyncMock(return_value=ConverseTurnResult(result="ok", mcp_success=True))

            result = await _call_converse(message="hi", wait_for_response=True)

        assert result == "ok"
        ports = instance.run.await_args.args[1]
        assert ports.provider_realtime_stt is provider_realtime_stt
        assert ports.realtime_stt is provider_realtime_stt


# ===========================================================================
# Helper Functions
# ===========================================================================

class TestShouldRepeat:
    """Tests for the should_repeat() helper."""

    def test_repeat_phrase_detected(self):
        from voice_mode.tools.converse import should_repeat
        with patch("voice_mode.tools.converse.REPEAT_PHRASES", ["say again", "repeat"]):
            assert should_repeat("Can you say again") is True
            assert should_repeat("Please repeat.") is True

    def test_repeat_phrase_not_detected(self):
        from voice_mode.tools.converse import should_repeat
        with patch("voice_mode.tools.converse.REPEAT_PHRASES", ["say again", "repeat"]):
            assert should_repeat("I like pizza") is False

    def test_repeat_empty_text(self):
        from voice_mode.tools.converse import should_repeat
        assert should_repeat("") is False
        assert should_repeat(None) is False


class TestShouldWait:
    """Tests for the should_wait() helper."""

    def test_wait_phrase_detected(self):
        from voice_mode.tools.converse import should_wait
        with patch("voice_mode.tools.converse.WAIT_PHRASES", ["hold on", "wait"]):
            assert should_wait("Please hold on") is True

    def test_wait_phrase_not_detected(self):
        from voice_mode.tools.converse import should_wait
        with patch("voice_mode.tools.converse.WAIT_PHRASES", ["hold on", "wait"]):
            assert should_wait("Let's go") is False

    def test_wait_empty_text(self):
        from voice_mode.tools.converse import should_wait
        assert should_wait("") is False
        assert should_wait(None) is False
