from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from voice_mode.converse_session import ConversePorts, ConverseRequest, ConverseSession
from voice_mode.voice_transcriber import ListenResult


class _AsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _request(**overrides) -> ConverseRequest:
    base = {
        "message": "Hello",
        "wait_for_response": True,
        "should_skip_tts": False,
        "voice": "Donna",
        "tts_model": "eleven_v3",
        "tts_provider": "elevenlabs",
        "tts_instructions": None,
        "audio_format": "mp3",
        "speed": 1.0,
        "listen_duration_max": 5.0,
        "listen_duration_min": 0.5,
        "disable_silence_detection": False,
        "vad_aggressiveness": 1,
        "chime_enabled": True,
        "chime_leading_silence": None,
        "chime_trailing_silence": None,
        "audio_ducking_enabled": True,
        "save_audio": False,
        "audio_dir": None,
        "debug": False,
        "debug_dir": None,
        "sample_rate": 16000,
        "channels": 1,
        "use_realtime_stt": False,
        "stt_language": "en",
        "metrics_level": "summary",
        "transport": "local",
        "save_transcriptions": False,
        "global_disable_silence_detection": False,
        "default_vad_aggressiveness": 1,
        "silence_threshold_ms": 500,
    }
    base.update(overrides)
    return ConverseRequest(**base)


def _ports(**overrides) -> ConversePorts:
    base = {
        "progress": AsyncMock(),
        "info": AsyncMock(),
        "tts_with_failover": AsyncMock(
            return_value=(
                True,
                {"ttfa": 0.01, "generation": 0.02, "playback": 0.03},
                {"provider": "elevenlabs"},
            )
        ),
        "play_audio_feedback": AsyncMock(),
        "record_audio_with_silence_detection": MagicMock(
            return_value=(np.arange(16, dtype=np.int16), True)
        ),
        "speech_to_text": AsyncMock(
            return_value={"text": "batch reply", "provider": "elevenlabs"}
        ),
        "provider_realtime_stt": AsyncMock(
            return_value={"text": "realtime reply", "provider": "elevenlabs_realtime"}
        ),
        "log_conversation_stt": MagicMock(),
        "track_voice_interaction": MagicMock(),
        "save_transcription": MagicMock(),
        "log_error": MagicMock(),
        "end_event_session": MagicMock(),
    }
    if "realtime_stt" in overrides and "provider_realtime_stt" not in overrides:
        overrides["provider_realtime_stt"] = overrides.pop("realtime_stt")
    base.update(overrides)
    return ConversePorts(**base)


@pytest.fixture
def session():
    event_logger = MagicMock()
    event_logger.RECORDING_START = "RECORDING_START"
    event_logger.RECORDING_END = "RECORDING_END"
    event_logger.STT_COMPLETE = "STT_COMPLETE"
    event_logger.STT_NO_SPEECH = "STT_NO_SPEECH"
    return ConverseSession(
        audio_operation_lock=_AsyncLock(),
        dj_ducker_factory=lambda: nullcontext(),
        event_logger=event_logger,
    )


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    async def _noop_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr("voice_mode.converse_session.asyncio.sleep", _noop_sleep)


@pytest.mark.asyncio
async def test_run_speak_only_returns_immediate_result(session):
    request = _request(wait_for_response=False)
    ports = _ports()

    result = await session.run(request, ports)

    assert result.result == "✓ Message spoken successfully (gen: 0.0s, play: 0.0s)"
    ports.play_audio_feedback.assert_not_awaited()
    ports.provider_realtime_stt.assert_not_awaited()
    ports.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_converse_ports_accepts_realtime_stt_compatibility_alias():
    realtime_stt = AsyncMock(return_value={"text": "legacy"})

    ports = _ports(realtime_stt=realtime_stt)

    assert ports.provider_realtime_stt is realtime_stt
    assert ports.realtime_stt is realtime_stt


@pytest.mark.asyncio
async def test_run_speak_only_ducks_media_exactly_once(monkeypatch):
    from voice_mode.audio_ducker import DJDucker, is_ducking_active

    monkeypatch.setattr(
        "voice_mode.audio_ducker._is_app_playing",
        lambda name: name == "Spotify",
    )
    simulate_media_key = MagicMock()
    monkeypatch.setattr(
        "voice_mode.audio_ducker._simulate_media_play_pause",
        simulate_media_key,
    )

    async def tts_with_session_ducking(**kwargs):
        assert is_ducking_active() is True
        return True, {"ttfa": 0.01, "generation": 0.02, "playback": 0.03}, {"provider": "elevenlabs"}

    session = ConverseSession(
        audio_operation_lock=_AsyncLock(),
        dj_ducker_factory=DJDucker,
        event_logger=MagicMock(),
    )
    request = _request(wait_for_response=False)
    ports = _ports(tts_with_failover=AsyncMock(side_effect=tts_with_session_ducking))

    result = await session.run(request, ports)

    assert result.mcp_success is True
    ports.tts_with_failover.assert_awaited_once()
    assert simulate_media_key.call_count == 2


@pytest.mark.asyncio
async def test_run_speak_only_skips_media_ducking_when_disabled(monkeypatch):
    from voice_mode.audio_ducker import DJDucker, is_ducking_active

    monkeypatch.setattr(
        "voice_mode.audio_ducker._is_app_playing",
        lambda name: name == "Spotify",
    )
    simulate_media_key = MagicMock()
    monkeypatch.setattr(
        "voice_mode.audio_ducker._simulate_media_play_pause",
        simulate_media_key,
    )

    async def tts_without_session_ducking(**kwargs):
        assert is_ducking_active() is False
        return True, {"ttfa": 0.01, "generation": 0.02, "playback": 0.03}, {"provider": "elevenlabs"}

    session = ConverseSession(
        audio_operation_lock=_AsyncLock(),
        dj_ducker_factory=DJDucker,
        event_logger=MagicMock(),
    )
    request = _request(wait_for_response=False, audio_ducking_enabled=False)
    ports = _ports(tts_with_failover=AsyncMock(side_effect=tts_without_session_ducking))

    result = await session.run(request, ports)

    assert result.mcp_success is True
    ports.tts_with_failover.assert_awaited_once()
    simulate_media_key.assert_not_called()


@pytest.mark.asyncio
async def test_run_realtime_stt_path_returns_response(session):
    request = _request(use_realtime_stt=True)
    ports = _ports(
        realtime_stt=AsyncMock(
            return_value={
                "text": "realtime reply",
                "provider": "elevenlabs_realtime",
                "metrics": {
                    "request_time_ms": 12.5,
                    "file_size_bytes": 0,
                    "is_local": False,
                },
            }
        )
    )

    result = await session.run(request, ports)

    assert result.response_text == "realtime reply"
    assert result.result.startswith("Voice response: realtime reply (STT: elevenlabs_realtime)")
    assert result.stt_provider == "elevenlabs_realtime"
    assert result.stt_model_used == "scribe_v2_realtime"
    assert result.mcp_success is True
    ports.provider_realtime_stt.assert_awaited_once_with(
        max_duration=5.0,
        min_duration=0.5,
        language_code="en",
        vad_aggressiveness=1,
        disable_silence_detection=False,
        previous_text="Hello",
        on_partial=None,
    )
    ports.log_conversation_stt.assert_called_once()
    ports.track_voice_interaction.assert_called_once()
    ports.end_event_session.assert_called_once()
    assert ports.play_audio_feedback.await_count == 2


@pytest.mark.asyncio
async def test_run_realtime_failure_falls_back_to_batch_transcription(session):
    failure = {
        "error_type": "connection_failed",
        "attempted_endpoints": [
            {"endpoint": "wss://api.elevenlabs.io", "error": "boom"}
        ],
    }
    request = _request(use_realtime_stt=True)
    ports = _ports(
        realtime_stt=AsyncMock(side_effect=[failure, failure, failure, failure]),
        speech_to_text=AsyncMock(
            return_value={
                "text": "fallback reply",
                "provider": "elevenlabs",
                "metrics": {
                    "request_time_ms": 20.0,
                    "file_size_bytes": 1024,
                    "is_local": False,
                },
            }
        ),
    )

    result = await session.run(request, ports)

    assert result.response_text == "fallback reply"
    assert "Voice response: fallback reply" in result.result
    assert result.stt_model_used == "scribe_v2"
    assert ports.provider_realtime_stt.await_count == 4
    ports.speech_to_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_listen_turn_constructs_voice_transcriber_with_provider_facade(monkeypatch, session):
    captured = {}

    class FakeTranscriber:
        def __init__(self, *, realtime_stt, record_audio_with_silence_detection, speech_to_text, sleep):
            captured["realtime_stt"] = realtime_stt
            captured["record_audio_with_silence_detection"] = record_audio_with_silence_detection
            captured["speech_to_text"] = speech_to_text
            captured["sleep"] = sleep

        async def listen_for_transcript(self, options):
            captured["options"] = options
            return ListenResult(
                stt_result={"text": "owned by transcriber", "provider": "fake_transcriber"},
                record_duration=0.1,
                stt_duration=0.2,
                stt_model_used="scribe_v2_realtime",
            )

    monkeypatch.setattr("voice_mode.converse_session.VoiceTranscriber", FakeTranscriber)
    request = _request(
        use_realtime_stt=True,
        listen_duration_max=9.0,
        listen_duration_min=2.5,
        stt_language="fr",
        disable_silence_detection=True,
        vad_aggressiveness=3,
        save_audio=True,
        audio_dir="/tmp/session-audio",
        transport="stdio",
    )
    ports = _ports()

    result = await session.run(request, ports)

    assert result.response_text == "owned by transcriber"
    assert captured["realtime_stt"] is ports.provider_realtime_stt
    assert captured["record_audio_with_silence_detection"] is ports.record_audio_with_silence_detection
    assert captured["speech_to_text"] is ports.speech_to_text
    assert captured["options"].max_duration == 9.0
    assert captured["options"].min_duration == 2.5
    assert captured["options"].language_code == "fr"
    assert captured["options"].previous_text == "Hello"
    assert captured["options"].disable_silence_detection is True
    assert captured["options"].vad_aggressiveness == 3
    assert captured["options"].use_realtime_stt is True
    assert captured["options"].save_audio is True
    assert captured["options"].audio_dir == "/tmp/session-audio"
    assert captured["options"].transport == "stdio"
    ports.provider_realtime_stt.assert_not_awaited()
    ports.record_audio_with_silence_detection.assert_not_called()
    ports.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_realtime_failure_with_empty_fallback_returns_no_speech(session):
    failure = {
        "error_type": "connection_failed",
        "attempted_endpoints": [
            {"endpoint": "wss://api.elevenlabs.io", "error": "boom"}
        ],
    }
    request = _request(use_realtime_stt=True)
    ports = _ports(
        realtime_stt=AsyncMock(side_effect=[failure, failure, failure, failure]),
        record_audio_with_silence_detection=MagicMock(
            return_value=(np.array([], dtype=np.int16), False)
        ),
    )

    result = await session.run(request, ports)

    assert result.response_text is None
    assert result.result.startswith("No speech detected")
    assert result.stt_provider == "local_vad"
    assert result.stt_model_used == "scribe_v2"
    ports.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_formats_and_logs_completed_batch_turn(session):
    request = _request(save_transcriptions=True)
    ports = _ports(
        speech_to_text=AsyncMock(
            return_value={
                "text": "batch reply",
                "provider": "elevenlabs",
                "metrics": {
                    "request_time_ms": 20.0,
                    "file_size_bytes": 2048,
                    "is_local": False,
                },
            }
        )
    )

    result = await session.run(request, ports)

    assert result.result.startswith("Voice response: batch reply (STT: elevenlabs)")
    assert "Timing:" in result.result
    assert result.timing_summary is not None
    assert result.mcp_success is True
    session.event_logger.log_event.assert_any_call(
        "STT_COMPLETE",
        {
            "text": "batch reply",
            "metrics": {
                "file_size_bytes": 2048,
                "request_time_ms": 20.0,
                "is_local": False,
                "format": "wav",
                "sample_rate_hz": 16000,
                "bitrate_kbps": 256,
            },
        },
    )
    ports.log_conversation_stt.assert_called_once()
    ports.track_voice_interaction.assert_called_once_with(
        message="Hello",
        response="batch reply",
        timing_str=result.timing_summary,
        transport="local",
        voice_provider="elevenlabs",
        voice_name="Donna",
        model="eleven_v3",
        success=True,
        error_message=None,
    )
    ports.save_transcription.assert_called_once()
    ports.end_event_session.assert_called_once()
