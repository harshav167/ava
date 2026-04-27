from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from voice_mode.voice_transcriber import ListenOptions, TranscriptMode, VoiceTranscriber


class FakeClock:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def __call__(self):
        if not self.values:
            raise AssertionError("FakeClock exhausted")
        value = self.values.pop(0)
        self.calls.append(value)
        return value


class SleepRecorder:
    def __init__(self):
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)


@pytest.mark.asyncio
async def test_listen_for_transcript_realtime_success_uses_stop_policy_values():
    observed = {}

    async def realtime_stt(**kwargs):
        observed.update(kwargs)
        return {"text": "hello realtime", "provider": "elevenlabs"}

    record_audio = MagicMock(return_value=(np.arange(4, dtype=np.int16), True))
    speech_to_text = AsyncMock(return_value={"text": "should not be used"})
    partials = []

    def on_partial(text):
        partials.append(text)

    clock = FakeClock([10.0, 10.25])
    transcriber = VoiceTranscriber(
        realtime_stt=realtime_stt,
        record_audio_with_silence_detection=record_audio,
        speech_to_text=speech_to_text,
        monotonic=clock,
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(
            max_duration=8.0,
            min_duration=1.5,
            language_code="en",
            previous_text="previous turn",
            disable_silence_detection=True,
            vad_aggressiveness=9,
            on_partial=on_partial,
        )
    )

    assert result.stt_result == {"text": "hello realtime", "provider": "elevenlabs"}
    assert result.record_duration == pytest.approx(0.25)
    assert result.stt_duration == pytest.approx(0.25)
    assert result.stt_model_used == "scribe_v2_realtime"
    assert result.fallback_used is False
    assert result.stop_policy.max_duration == 8.0
    assert result.stop_policy.min_duration == 1.5
    assert result.stop_policy.disable_silence_detection is True
    assert result.stop_policy.vad_aggressiveness == 3
    assert observed == {
        "max_duration": 8.0,
        "min_duration": 1.5,
        "language_code": "en",
        "vad_aggressiveness": 3,
        "disable_silence_detection": True,
        "previous_text": "previous turn",
        "on_partial": on_partial,
    }
    assert clock.calls == [10.0, 10.25]
    record_audio.assert_not_called()
    speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_for_transcript_realtime_retry_exhaustion_falls_back_to_local():
    failure = {"error_type": "connection_failed", "provider": "elevenlabs"}
    realtime_stt = AsyncMock(side_effect=[failure, failure, failure, failure])
    record_audio = MagicMock(return_value=(np.arange(8, dtype=np.int16), True))
    speech_to_text = AsyncMock(
        return_value={"text": "fallback text", "provider": "elevenlabs", "audio_file": "fallback.wav"}
    )
    sleep = SleepRecorder()
    clock = FakeClock([20.0, 20.4, 20.4, 20.9, 20.9, 20.9])
    transcriber = VoiceTranscriber(
        realtime_stt=realtime_stt,
        record_audio_with_silence_detection=record_audio,
        speech_to_text=speech_to_text,
        sleep=sleep,
        monotonic=clock,
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(
            max_duration=6.0,
            min_duration=0.75,
            vad_aggressiveness=0,
            save_audio=True,
            audio_dir="/tmp/audio",
            transport="stdio",
        )
    )

    assert realtime_stt.await_count == 4
    assert sleep.delays == [1, 2, 4]
    record_audio.assert_called_once()
    assert record_audio.call_args.args == (6.0, False, 0.75, 0)
    assert record_audio.call_args.kwargs == {"stop_policy": result.stop_policy}
    speech_to_text.assert_awaited_once()
    assert speech_to_text.await_args.args[1:] == (True, "/tmp/audio", "stdio")
    assert result.stt_result["text"] == "fallback text"
    assert result.audio_file == "fallback.wav"
    assert result.fallback_used is True
    assert result.record_duration == pytest.approx(0.5)
    assert result.stt_duration == pytest.approx(0.0)
    assert result.stt_model_used == "scribe_v2"
    assert clock.calls == [20.0, 20.4, 20.4, 20.9, 20.9, 20.9]


@pytest.mark.asyncio
async def test_listen_for_transcript_retries_preserve_realtime_forwarding_options():
    failure = {"error_type": "connection_failed", "provider": "elevenlabs"}
    success = {"text": "retry success", "provider": "elevenlabs_realtime"}
    realtime_stt = AsyncMock(side_effect=[failure, success])
    partials = []

    def on_partial(text):
        partials.append(text)

    transcriber = VoiceTranscriber(
        realtime_stt=realtime_stt,
        record_audio_with_silence_detection=MagicMock(),
        speech_to_text=AsyncMock(),
        sleep=SleepRecorder(),
        monotonic=FakeClock([40.0, 40.5]),
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(
            max_duration=7.0,
            min_duration=2.0,
            language_code="es",
            previous_text="prior context",
            disable_silence_detection=False,
            vad_aggressiveness=1,
            on_partial=on_partial,
        )
    )

    assert result.stt_result == success
    assert realtime_stt.await_count == 2
    for call in realtime_stt.await_args_list:
        assert call.kwargs == {
            "max_duration": 7.0,
            "min_duration": 2.0,
            "language_code": "es",
            "vad_aggressiveness": 1,
            "disable_silence_detection": False,
            "previous_text": "prior context",
            "on_partial": on_partial,
        }
    transcriber.record_audio_with_silence_detection.assert_not_called()
    transcriber.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_for_transcript_local_mode_success_skips_realtime():
    realtime_stt = AsyncMock(return_value={"text": "should not be used"})
    record_audio = MagicMock(return_value=(np.arange(6, dtype=np.int16), True))
    speech_to_text = AsyncMock(
        return_value={
            "text": "local text",
            "provider": "elevenlabs",
            "audio_file": "local.wav",
            "audio_format": "wav",
        }
    )
    transcriber = VoiceTranscriber(
        realtime_stt=realtime_stt,
        record_audio_with_silence_detection=record_audio,
        speech_to_text=speech_to_text,
        monotonic=FakeClock([1.0, 1.2, 1.2, 1.6]),
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(
            max_duration=4.0,
            min_duration=1.0,
            mode=TranscriptMode.LOCAL,
            use_realtime_stt=True,
            disable_silence_detection=False,
            vad_aggressiveness=2,
        )
    )

    realtime_stt.assert_not_awaited()
    record_audio.assert_called_once()
    assert record_audio.call_args.args == (4.0, False, 1.0, 2)
    assert record_audio.call_args.kwargs == {"stop_policy": result.stop_policy}
    speech_to_text.assert_awaited_once()
    assert result.stt_result["text"] == "local text"
    assert result.audio_file == "local.wav"
    assert result.audio_format == "wav"
    assert result.fallback_used is False
    assert result.record_duration == pytest.approx(0.2)
    assert result.stt_duration == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_listen_for_transcript_local_mode_empty_recording_returns_existing_error_dict():
    transcriber = VoiceTranscriber(
        realtime_stt=AsyncMock(),
        record_audio_with_silence_detection=MagicMock(
            return_value=(np.array([], dtype=np.int16), False)
        ),
        speech_to_text=AsyncMock(),
        monotonic=FakeClock([2.0, 2.1]),
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(max_duration=3.0, min_duration=0.5, mode=TranscriptMode.LOCAL)
    )

    assert result.stt_result == {"error_type": "recording_failed", "provider": "local_audio"}
    assert result.record_duration == pytest.approx(0.1)
    assert result.stt_duration == 0.0
    assert result.stt_model_used == "scribe_v2"
    transcriber.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_for_transcript_fallback_empty_recording_normalizes_to_no_speech():
    failure = {"error_type": "connection_failed", "provider": "elevenlabs"}
    transcriber = VoiceTranscriber(
        realtime_stt=AsyncMock(side_effect=[failure, failure, failure, failure]),
        record_audio_with_silence_detection=MagicMock(
            return_value=(np.array([], dtype=np.int16), False)
        ),
        speech_to_text=AsyncMock(),
        sleep=SleepRecorder(),
        monotonic=FakeClock([5.0, 5.3, 5.3, 5.35]),
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(max_duration=3.0, min_duration=0.5, use_realtime_stt=True)
    )

    assert result.stt_result == {"error_type": "no_speech", "provider": "local_vad"}
    assert result.fallback_used is True
    transcriber.speech_to_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_for_transcript_no_speech_normalizes_empty_stt_result():
    transcriber = VoiceTranscriber(
        realtime_stt=AsyncMock(),
        record_audio_with_silence_detection=MagicMock(
            return_value=(np.arange(4, dtype=np.int16), True)
        ),
        speech_to_text=AsyncMock(return_value={"text": "", "provider": "elevenlabs"}),
        monotonic=FakeClock([30.0, 30.2, 30.2, 30.5]),
    )

    result = await transcriber.listen_for_transcript(
        ListenOptions(max_duration=3.0, min_duration=0.5, mode=TranscriptMode.LOCAL)
    )

    assert result.stt_result == {"error_type": "no_speech", "provider": "elevenlabs"}
    assert result.record_duration == pytest.approx(0.2)
    assert result.stt_duration == pytest.approx(0.3)
    transcriber.speech_to_text.assert_awaited_once()
