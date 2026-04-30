"""Deep internal session boundary for the primary converse turn pipeline."""

from __future__ import annotations

import asyncio
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

from voice_mode.voice_transcriber import ListenOptions, VoiceTranscriber


ProgressFn = Callable[[object, int, int, str], Awaitable[None]]
InfoFn = Callable[[object, str], Awaitable[None]]
TTSFn = Callable[..., Awaitable[tuple[bool, Optional[dict], Optional[dict]]]]
FeedbackFn = Callable[..., Awaitable[None]]
RecordFn = Callable[..., tuple]
STTFn = Callable[..., Awaitable[dict]]
ProviderRealtimeSTTFn = Callable[..., Awaitable[dict]]
ConversationSTTLogFn = Callable[..., None]
TrackVoiceInteractionFn = Callable[..., None]
SaveTranscriptionFn = Callable[..., None]
ErrorLogFn = Callable[[str], None]
EndSessionFn = Callable[[], None]


@dataclass(frozen=True)
class ConverseRequest:
    message: str
    wait_for_response: bool
    should_skip_tts: bool
    voice: Optional[str]
    tts_model: Optional[str]
    tts_provider: Optional[str]
    tts_instructions: Optional[str]
    audio_format: Optional[str]
    speed: Optional[float]
    listen_duration_max: float
    listen_duration_min: float
    disable_silence_detection: bool
    vad_aggressiveness: Optional[int]
    chime_enabled: Optional[bool]
    chime_leading_silence: Optional[float]
    chime_trailing_silence: Optional[float]
    audio_ducking_enabled: bool
    save_audio: bool
    audio_dir: Optional[str]
    debug: bool
    debug_dir: Optional[str]
    sample_rate: int
    channels: int
    use_realtime_stt: bool
    stt_language: Optional[str]
    metrics_level: str
    transport: str = "local"
    save_transcriptions: bool = False
    global_disable_silence_detection: bool = False
    default_vad_aggressiveness: Optional[int] = None
    silence_threshold_ms: Optional[int] = None


@dataclass
class ConverseTurnResult:
    response_text: Optional[str] = None
    result: Optional[str] = None
    timings: dict = field(default_factory=dict)
    stt_metrics: Optional[dict] = None
    stt_model_used: str = "scribe_v2"
    stt_provider: str = "unknown"
    stt_audio_file: Optional[str] = None
    stt_audio_format: Optional[str] = None
    tts_success: bool = False
    tts_metrics: Optional[dict] = None
    tts_config: Optional[dict] = None
    timing_summary: Optional[str] = None
    mcp_success: bool = False


@dataclass(frozen=True, init=False)
class ConversePorts:
    progress: ProgressFn
    info: InfoFn
    tts_with_failover: TTSFn
    play_audio_feedback: FeedbackFn
    record_audio_with_silence_detection: RecordFn
    speech_to_text: STTFn
    provider_realtime_stt: ProviderRealtimeSTTFn
    log_conversation_stt: Optional[ConversationSTTLogFn] = None
    track_voice_interaction: Optional[TrackVoiceInteractionFn] = None
    save_transcription: Optional[SaveTranscriptionFn] = None
    log_error: Optional[ErrorLogFn] = None
    end_event_session: Optional[EndSessionFn] = None

    def __init__(
        self,
        *,
        progress: ProgressFn,
        info: InfoFn,
        tts_with_failover: TTSFn,
        play_audio_feedback: FeedbackFn,
        record_audio_with_silence_detection: RecordFn,
        speech_to_text: STTFn,
        provider_realtime_stt: Optional[ProviderRealtimeSTTFn] = None,
        realtime_stt: Optional[ProviderRealtimeSTTFn] = None,
        log_conversation_stt: Optional[ConversationSTTLogFn] = None,
        track_voice_interaction: Optional[TrackVoiceInteractionFn] = None,
        save_transcription: Optional[SaveTranscriptionFn] = None,
        log_error: Optional[ErrorLogFn] = None,
        end_event_session: Optional[EndSessionFn] = None,
    ):
        if provider_realtime_stt is None:
            if realtime_stt is None:
                raise TypeError("provider_realtime_stt is required")
            provider_realtime_stt = realtime_stt

        object.__setattr__(self, "progress", progress)
        object.__setattr__(self, "info", info)
        object.__setattr__(self, "tts_with_failover", tts_with_failover)
        object.__setattr__(self, "play_audio_feedback", play_audio_feedback)
        object.__setattr__(self, "record_audio_with_silence_detection", record_audio_with_silence_detection)
        object.__setattr__(self, "speech_to_text", speech_to_text)
        object.__setattr__(self, "provider_realtime_stt", provider_realtime_stt)
        object.__setattr__(self, "log_conversation_stt", log_conversation_stt)
        object.__setattr__(self, "track_voice_interaction", track_voice_interaction)
        object.__setattr__(self, "save_transcription", save_transcription)
        object.__setattr__(self, "log_error", log_error)
        object.__setattr__(self, "end_event_session", end_event_session)

    @property
    def realtime_stt(self) -> ProviderRealtimeSTTFn:
        """Compatibility alias for the low-level realtime STT provider call.

        ConverseSession owns conversational listening through VoiceTranscriber;
        this port is only the provider operation used by that transcriber.
        """
        return self.provider_realtime_stt


class ConverseSession:
    """Runs the primary speak + optional listen turn behind a single boundary."""

    def __init__(self, *, audio_operation_lock, dj_ducker_factory, event_logger=None):
        self.audio_operation_lock = audio_operation_lock
        self.dj_ducker_factory = dj_ducker_factory
        self.event_logger = event_logger

    async def run(self, request: ConverseRequest, ports: ConversePorts, ctx=None) -> ConverseTurnResult:
        try:
            return await self._run_turn(request, ports, ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._track_failed_interaction(request, ports, str(exc))
            raise

    async def _run_turn(self, request: ConverseRequest, ports: ConversePorts, ctx=None) -> ConverseTurnResult:
        timings: dict = {}
        result = ConverseTurnResult(timings=timings)

        async with self.audio_operation_lock:
            await ports.progress(ctx, 0, 4, "Starting TTS")
            await ports.info(ctx, "Connecting to ElevenLabs...")

            tts_start = time.perf_counter()
            if request.should_skip_tts:
                result.tts_success = True
                result.tts_metrics = {"ttfa": 0, "generation": 0, "playback": 0, "total": 0}
                result.tts_config = {"provider": "no-op", "voice": "none"}
            else:
                ducking_context = (
                    self.dj_ducker_factory() if request.audio_ducking_enabled else nullcontext()
                )
                with ducking_context:
                    result.tts_success, result.tts_metrics, result.tts_config = await ports.tts_with_failover(
                        message=request.message,
                        voice=request.voice,
                        model=request.tts_model,
                        instructions=request.tts_instructions,
                        audio_format=request.audio_format,
                        initial_provider=request.tts_provider,
                        speed=request.speed,
                    )

            await ports.progress(ctx, 1, 4, "Playing audio")
            await ports.info(ctx, "Playing audio...")

            if result.tts_metrics:
                timings["ttfa"] = result.tts_metrics.get("ttfa", 0)
                timings["tts_gen"] = result.tts_metrics.get("generation", 0)
                timings["tts_play"] = result.tts_metrics.get("playback", 0)
            timings["tts_total"] = time.perf_counter() - tts_start

            if not result.tts_success:
                result.result = self._format_tts_failure(result.tts_config)
                return result

            if not request.wait_for_response:
                await ports.progress(ctx, 4, 4, "Complete")
                await ports.info(ctx, "Message spoken")
                timing_info = ""
                if request.metrics_level != "minimal" and result.tts_success and result.tts_metrics:
                    timing_info = (
                        f" (gen: {result.tts_metrics.get('generation', 0):.1f}s, "
                        f"play: {result.tts_metrics.get('playback', 0):.1f}s)"
                    )
                result.result = f"✓ Message spoken successfully{timing_info}"
                result.mcp_success = True
                return result

            await ports.progress(ctx, 2, 4, "Recording")
            await ports.info(ctx, "Recording started...")
            await asyncio.sleep(0.5)

            await ports.play_audio_feedback(
                "listening",
                None,
                request.chime_enabled,
                "chime",
                chime_leading_silence=request.chime_leading_silence,
                chime_trailing_silence=request.chime_trailing_silence,
            )

            if self.event_logger:
                self.event_logger.log_event(self.event_logger.RECORDING_START)

            await ports.progress(ctx, 3, 4, "Transcribing")
            await ports.info(ctx, "Transcribing...")
            transcriber = VoiceTranscriber(
                realtime_stt=ports.provider_realtime_stt,
                record_audio_with_silence_detection=ports.record_audio_with_silence_detection,
                speech_to_text=ports.speech_to_text,
                sleep=asyncio.sleep,
            )
            listen_result = await transcriber.listen_for_transcript(
                ListenOptions(
                    max_duration=request.listen_duration_max,
                    min_duration=request.listen_duration_min,
                    language_code=request.stt_language,
                    previous_text=request.message[:50] if request.message else None,
                    disable_silence_detection=request.disable_silence_detection,
                    vad_aggressiveness=request.vad_aggressiveness,
                    use_realtime_stt=request.use_realtime_stt,
                    save_audio=request.save_audio,
                    audio_dir=request.audio_dir,
                    transport=request.transport,
                )
            )
            stt_result = listen_result.stt_result
            result.stt_model_used = listen_result.stt_model_used
            result.stt_audio_file = listen_result.audio_file
            result.stt_audio_format = listen_result.audio_format
            timings["record"] = listen_result.record_duration
            timings["stt"] = listen_result.stt_duration

            if self.event_logger:
                event_data = {"duration": listen_result.record_duration}
                if request.use_realtime_stt and not listen_result.fallback_used:
                    event_data["provider"] = "elevenlabs_realtime"
                self.event_logger.log_event(self.event_logger.RECORDING_END, event_data)

            if stt_result.get("error_type") == "recording_failed":
                result.result = "Error: Could not record audio"
                return result

            await ports.play_audio_feedback(
                "finished",
                None,
                request.chime_enabled,
                "whisper",
                chime_leading_silence=request.chime_leading_silence,
                chime_trailing_silence=request.chime_trailing_silence,
            )

            await ports.progress(ctx, 3, 4, "Transcribing")
            await ports.info(ctx, "Transcription complete")

            if isinstance(stt_result, dict):
                result.stt_metrics = stt_result.get("metrics")
                if result.stt_metrics:
                    timings["stt_request_ms"] = result.stt_metrics.get("request_time_ms", 0)
                    timings["stt_file_size_bytes"] = result.stt_metrics.get("file_size_bytes", 0)
                    timings["stt_is_local"] = result.stt_metrics.get("is_local", False)

                if "error_type" in stt_result:
                    if stt_result["error_type"] == "connection_failed":
                        error_lines = ["STT service connection failed:"]
                        for attempt in stt_result.get("attempted_endpoints", []):
                            endpoint = attempt.get("endpoint", attempt.get("provider", "unknown"))
                            error_lines.append(f"  - {endpoint}: {attempt['error']}")
                        result.result = "\n".join(error_lines)
                        return result
                    if stt_result["error_type"] == "no_speech":
                        result.response_text = None
                        result.stt_provider = stt_result.get("provider", "unknown")
                else:
                    result.response_text = stt_result.get("text")
                    result.stt_provider = stt_result.get("provider", "unknown")

            return await self._complete_turn(request, ports, result, ctx)

    async def _complete_turn(
        self,
        request: ConverseRequest,
        ports: ConversePorts,
        result: ConverseTurnResult,
        ctx,
    ) -> ConverseTurnResult:
        self._log_stt_event(request, result)
        self._log_conversation_stt(request, ports, result)

        await ports.progress(ctx, 4, 4, "Complete")
        await ports.info(ctx, "Voice interaction complete")

        timing_str = self._build_timing_summary(result.timings)
        result.timing_summary = timing_str

        self._track_completed_interaction(request, ports, result, timing_str)
        self._end_event_session(ports)
        self._save_completed_transcription(request, ports, result, timing_str)

        result.result = self._format_converse_result(
            response_text=result.response_text,
            stt_provider=result.stt_provider,
            metrics_level=request.metrics_level,
            timing_str=timing_str,
            timings=result.timings,
        )
        result.mcp_success = True
        return result

    def _format_tts_failure(self, tts_config: Optional[dict]) -> str:
        if tts_config and tts_config.get("error_type") == "all_providers_failed":
            error_lines = ["Error: Could not speak message. TTS service connection failed:"]
            for attempt in tts_config.get("attempted_endpoints", []):
                endpoint_or_provider = attempt.get("endpoint", attempt.get("provider", "unknown"))
                error_lines.append(f"  - {endpoint_or_provider}: {attempt['error']}")
            return "\n".join(error_lines)
        return "Error: Could not speak message. All TTS providers failed."

    def _build_timing_summary(self, timings: dict) -> str:
        total_time = sum(
            value for key, value in timings.items() if key in {"tts_total", "record", "stt"}
        )

        timing_parts = []
        if "ttfa" in timings:
            timing_parts.append(f"ttfa {timings['ttfa']:.1f}s")
        if "tts_gen" in timings:
            timing_parts.append(f"gen {timings['tts_gen']:.1f}s")
        if "tts_play" in timings:
            timing_parts.append(f"play {timings['tts_play']:.1f}s")
        if "record" in timings:
            timing_parts.append(f"record {timings['record']:.1f}s")
        if "stt" in timings:
            timing_parts.append(f"stt {timings['stt']:.1f}s")
        if timings.get("stt_file_size_bytes", 0) > 0:
            timing_parts.append(f"audio {timings['stt_file_size_bytes'] / 1024:.0f}KB")

        return ", ".join(timing_parts) + f", total {total_time:.1f}s"

    def _format_converse_result(
        self,
        *,
        response_text: Optional[str],
        stt_provider: str,
        metrics_level: str,
        timing_str: str,
        timings: dict,
    ) -> str:
        if response_text:
            stt_info = f" (STT: {stt_provider})" if stt_provider != "unknown" else ""
            if metrics_level == "minimal":
                return f"Voice response: {response_text}"
            if metrics_level == "verbose":
                verbose_parts = [
                    f"Voice response: {response_text}{stt_info}",
                    f"Timing: {timing_str}",
                ]
                if "stt_request_ms" in timings:
                    verbose_parts.append(f"STT request: {timings['stt_request_ms']:.0f}ms")
                if "stt_file_size_bytes" in timings:
                    verbose_parts.append(f"STT file: {timings['stt_file_size_bytes'] / 1024:.0f}KB")
                if "stt_is_local" in timings:
                    verbose_parts.append(f"STT local: {timings['stt_is_local']}")
                return " | ".join(verbose_parts)
            return f"Voice response: {response_text}{stt_info} | Timing: {timing_str}"

        if metrics_level == "minimal":
            return "No speech detected"
        return f"No speech detected | Timing: {timing_str}"

    def _log_stt_event(self, request: ConverseRequest, result: ConverseTurnResult) -> None:
        if not self.event_logger:
            return

        stt_event_data = {}
        if result.response_text:
            stt_event_data["text"] = result.response_text
        if result.stt_metrics:
            stt_event_data["metrics"] = {
                "file_size_bytes": result.stt_metrics.get("file_size_bytes", 0),
                "request_time_ms": result.stt_metrics.get("request_time_ms", 0),
                "is_local": result.stt_metrics.get("is_local", False),
                "format": "wav",
                "sample_rate_hz": request.sample_rate,
                "bitrate_kbps": (request.sample_rate * 16 * request.channels) // 1000,
            }

        if result.response_text:
            event_name = getattr(self.event_logger, "STT_COMPLETE", "STT_COMPLETE")
        else:
            event_name = getattr(self.event_logger, "STT_NO_SPEECH", "STT_NO_SPEECH")
        self.event_logger.log_event(event_name, stt_event_data)

    def _log_conversation_stt(
        self,
        request: ConverseRequest,
        ports: ConversePorts,
        result: ConverseTurnResult,
    ) -> None:
        if not ports.log_conversation_stt:
            return

        try:
            ports.log_conversation_stt(
                text=result.response_text if result.response_text else "[no speech detected]",
                model=result.stt_model_used,
                provider="elevenlabs",
                provider_url="api.elevenlabs.io",
                provider_type="elevenlabs",
                audio_file=result.stt_audio_file,
                audio_format=result.stt_audio_format or "mp3",
                transport=request.transport,
                timing=self._build_stt_timing_summary(result.timings),
                silence_detection={
                    "enabled": not (
                        request.global_disable_silence_detection
                        or request.disable_silence_detection
                    ),
                    "vad_aggressiveness": request.default_vad_aggressiveness,
                    "silence_threshold_ms": request.silence_threshold_ms,
                },
                transcription_time=result.timings.get("stt"),
                total_turnaround_time=None,
            )
        except Exception as exc:
            self._log_error(ports, f"Failed to log STT to JSONL: {exc}")

    def _build_stt_timing_summary(self, timings: dict) -> Optional[str]:
        stt_timing_parts = []
        if "record" in timings:
            stt_timing_parts.append(f"record {timings['record']:.1f}s")
        if "stt" in timings:
            stt_timing_parts.append(f"stt {timings['stt']:.1f}s")
        return ", ".join(stt_timing_parts) if stt_timing_parts else None

    def _track_completed_interaction(
        self,
        request: ConverseRequest,
        ports: ConversePorts,
        result: ConverseTurnResult,
        timing_str: str,
    ) -> None:
        if not ports.track_voice_interaction:
            return

        actual_response = result.response_text or "[no speech detected]"
        ports.track_voice_interaction(
            message=request.message,
            response=actual_response,
            timing_str=timing_str,
            transport=request.transport,
            voice_provider=request.tts_provider,
            voice_name=request.voice,
            model=request.tts_model,
            success=bool(result.response_text),
            error_message=None if result.response_text else "No speech detected",
        )

    def _track_failed_interaction(
        self,
        request: ConverseRequest,
        ports: ConversePorts,
        error_message: str,
    ) -> None:
        if not ports.track_voice_interaction:
            return

        ports.track_voice_interaction(
            message=request.message,
            response="[error]",
            timing_str=None,
            transport=request.transport,
            voice_provider=request.tts_provider,
            voice_name=request.voice,
            model=request.tts_model,
            success=False,
            error_message=error_message,
        )

    def _save_completed_transcription(
        self,
        request: ConverseRequest,
        ports: ConversePorts,
        result: ConverseTurnResult,
        timing_str: str,
    ) -> None:
        if not (request.save_transcriptions and result.response_text and ports.save_transcription):
            return

        conversation_text = f"Assistant: {request.message}\n\nUser: {result.response_text}"
        metadata = {
            "type": "conversation",
            "transport": request.transport,
            "voice": request.voice,
            "model": request.tts_model,
            "stt_model": "whisper-1",
            "timing": timing_str,
            "timestamp": datetime.now().isoformat(),
        }
        ports.save_transcription(conversation_text, prefix="conversation", metadata=metadata)

    def _end_event_session(self, ports: ConversePorts) -> None:
        if ports.end_event_session:
            ports.end_event_session()

    def _log_error(self, ports: ConversePorts, message: str) -> None:
        if ports.log_error:
            ports.log_error(message)
