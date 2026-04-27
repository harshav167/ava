"""Listening-session boundary for VoiceMode speech transcription."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Awaitable, Callable, Optional

import numpy as np

from voice_mode.silero_vad import StopPolicy, build_stop_policy


RealtimeSTTFn = Callable[..., Awaitable[dict]]
RecordFn = Callable[..., tuple[np.ndarray, bool]]
STTFn = Callable[..., Awaitable[dict]]


class TranscriptMode(str, Enum):
    """Listening backend selection for a voice transcription turn."""

    AUTO = "auto"
    REALTIME = "realtime"
    LOCAL = "local"


@dataclass(frozen=True)
class ListenOptions:
    """Caller-facing listening options for one microphone transcription turn."""

    max_duration: float
    min_duration: float
    language_code: Optional[str] = None
    previous_text: Optional[str] = None
    disable_silence_detection: bool = False
    vad_aggressiveness: Optional[int] = None
    mode: TranscriptMode = TranscriptMode.AUTO
    use_realtime_stt: bool = True
    save_audio: bool = False
    audio_dir: Optional[str] = None
    transport: str = "local"
    on_partial: Optional[Callable[[str], None]] = None


@dataclass
class ListenResult:
    """Normalized result from realtime or local transcription."""

    stt_result: dict
    record_duration: float
    stt_duration: float
    stt_model_used: str
    fallback_used: bool = False
    audio_file: Optional[str] = None
    audio_format: Optional[str] = None
    stop_policy: StopPolicy = field(default_factory=build_stop_policy)


class VoiceTranscriber:
    """Owns conversational listening flow and STT result normalization.

    SpeechService and VoiceProvider stay as low-level STT/TTS facades. Converse
    callers should enter microphone listening through this boundary so retry,
    local fallback, no-speech normalization, and stop policy remain in one place.
    """

    def __init__(
        self,
        *,
        realtime_stt: RealtimeSTTFn,
        record_audio_with_silence_detection: RecordFn,
        speech_to_text: STTFn,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.perf_counter,
        realtime_retry_delays: tuple[float, ...] = (1, 2, 4),
    ):
        self.realtime_stt = realtime_stt
        self.record_audio_with_silence_detection = record_audio_with_silence_detection
        self.speech_to_text = speech_to_text
        self.sleep = sleep
        self.monotonic = monotonic
        self.realtime_retry_delays = realtime_retry_delays

    async def listen_for_transcript(self, options: ListenOptions) -> ListenResult:
        """Listen once and return a normalized STT dictionary.

        The caller does not need to know whether realtime, local recording, or
        realtime-to-local fallback handled the microphone session.
        """
        stop_policy = build_stop_policy(
            max_duration=options.max_duration,
            min_duration=options.min_duration,
            disable_silence_detection=options.disable_silence_detection,
            vad_aggressiveness=options.vad_aggressiveness,
        )

        if self._should_use_realtime(options):
            realtime_result = await self._listen_realtime(options, stop_policy)
            if not self._is_connection_failed(realtime_result.stt_result):
                return realtime_result

        local_result = await self._listen_local(options, stop_policy)
        if self._should_use_realtime(options):
            local_result.fallback_used = True
            if local_result.stt_result.get("error_type") == "recording_failed":
                local_result.stt_result = {"error_type": "no_speech", "provider": "local_vad"}
        return local_result

    def _should_use_realtime(self, options: ListenOptions) -> bool:
        return options.mode in {TranscriptMode.AUTO, TranscriptMode.REALTIME} and options.use_realtime_stt

    async def _listen_realtime(self, options: ListenOptions, stop_policy: StopPolicy) -> ListenResult:
        started = self.monotonic()
        stt_result = await self.realtime_stt(
            max_duration=stop_policy.max_duration,
            min_duration=stop_policy.min_duration,
            language_code=options.language_code,
            vad_aggressiveness=stop_policy.vad_aggressiveness,
            disable_silence_detection=stop_policy.disable_silence_detection,
            previous_text=options.previous_text,
            on_partial=options.on_partial,
        )

        for delay in self.realtime_retry_delays:
            if not self._is_connection_failed(stt_result):
                break
            await self.sleep(delay)
            stt_result = await self.realtime_stt(
                max_duration=stop_policy.max_duration,
                min_duration=stop_policy.min_duration,
                language_code=options.language_code,
                vad_aggressiveness=stop_policy.vad_aggressiveness,
                disable_silence_detection=stop_policy.disable_silence_detection,
                previous_text=options.previous_text,
                on_partial=options.on_partial,
            )

        elapsed = self.monotonic() - started
        return ListenResult(
            stt_result=self._normalize_stt_result(stt_result, provider="elevenlabs"),
            record_duration=elapsed,
            stt_duration=elapsed,
            stt_model_used="scribe_v2_realtime",
            stop_policy=stop_policy,
        )

    async def _listen_local(self, options: ListenOptions, stop_policy: StopPolicy) -> ListenResult:
        loop = asyncio.get_event_loop()
        record_started = self.monotonic()
        record_audio = partial(
            self.record_audio_with_silence_detection,
            stop_policy.max_duration,
            stop_policy.disable_silence_detection,
            stop_policy.min_duration,
            stop_policy.vad_aggressiveness,
            stop_policy=stop_policy,
        )
        audio_data, speech_detected = await loop.run_in_executor(None, record_audio)
        record_duration = self.monotonic() - record_started

        if len(audio_data) == 0:
            return ListenResult(
                stt_result={"error_type": "recording_failed", "provider": "local_audio"},
                record_duration=record_duration,
                stt_duration=0.0,
                stt_model_used="scribe_v2",
                stop_policy=stop_policy,
            )

        if not speech_detected:
            return ListenResult(
                stt_result={"error_type": "no_speech", "provider": "local_vad"},
                record_duration=record_duration,
                stt_duration=0.0,
                stt_model_used="scribe_v2",
                stop_policy=stop_policy,
            )

        stt_started = self.monotonic()
        stt_result = await self.speech_to_text(
            audio_data,
            options.save_audio,
            options.audio_dir,
            options.transport,
        )
        normalized_result = self._normalize_stt_result(stt_result, provider="unknown")
        return ListenResult(
            stt_result=normalized_result,
            record_duration=record_duration,
            stt_duration=self.monotonic() - stt_started,
            stt_model_used="scribe_v2",
            audio_file=normalized_result.get("audio_file"),
            audio_format=normalized_result.get("audio_format"),
            stop_policy=stop_policy,
        )

    def _normalize_stt_result(self, stt_result: Optional[dict], *, provider: str) -> dict:
        if not stt_result:
            return {"error_type": "no_speech", "provider": provider}
        if "error_type" in stt_result:
            return stt_result
        if not stt_result.get("text"):
            return {"error_type": "no_speech", "provider": stt_result.get("provider", provider)}
        return stt_result

    def _is_connection_failed(self, stt_result: Optional[dict]) -> bool:
        return isinstance(stt_result, dict) and stt_result.get("error_type") == "connection_failed"


async def listen_for_transcript(
    *,
    max_duration: float,
    min_duration: float,
    language_code: Optional[str] = None,
    previous_text: Optional[str] = None,
    disable_silence_detection: bool = False,
    vad_aggressiveness: Optional[int] = None,
    mode: TranscriptMode = TranscriptMode.AUTO,
    use_realtime_stt: bool = True,
    on_partial: Optional[Callable[[str], None]] = None,
    save_audio: bool = False,
    audio_dir: Optional[str] = None,
    transport: str = "local",
    realtime_stt: RealtimeSTTFn,
    record_audio_with_silence_detection: RecordFn,
    speech_to_text: STTFn,
) -> ListenResult:
    """Functional wrapper for callers that do not need a long-lived transcriber."""
    transcriber = VoiceTranscriber(
        realtime_stt=realtime_stt,
        record_audio_with_silence_detection=record_audio_with_silence_detection,
        speech_to_text=speech_to_text,
    )
    return await transcriber.listen_for_transcript(
        ListenOptions(
            max_duration=max_duration,
            min_duration=min_duration,
            language_code=language_code,
            previous_text=previous_text,
            disable_silence_detection=disable_silence_detection,
            vad_aggressiveness=vad_aggressiveness,
            mode=mode,
            use_realtime_stt=use_realtime_stt,
            save_audio=save_audio,
            audio_dir=audio_dir,
            transport=transport,
            on_partial=on_partial,
        )
    )
