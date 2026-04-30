"""Provider and speech-service boundaries for VoiceMode voice interactions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional, Protocol

from .provider_discovery import EndpointInfo, provider_registry
from .runtime_context import get_runtime_context


DEFAULT_TTS_VOICE = "k4hP4cQadSZQc0Oar2Ld"
DEFAULT_TTS_MODEL = "eleven_v3"
DEFAULT_BATCH_STT_MODEL = "scribe_v2"
DEFAULT_REALTIME_STT_MODEL = "scribe_v2_realtime"


@dataclass(frozen=True)
class SpeakOptions:
    """Caller-facing options for speech synthesis."""

    text: str
    voice: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    instructions: Optional[str] = None
    audio_format: Optional[str] = None
    speed: Optional[float] = None
    debug: bool = False
    debug_dir: Optional[Path] = None
    save_audio: bool = False
    audio_dir: Optional[Path] = None


@dataclass(frozen=True)
class ListenOptions:
    """Caller-facing options for speech recognition.

    Pass ``audio_file`` for batch STT. Leave it unset for realtime microphone STT.
    """

    audio_file: Optional[BinaryIO] = None
    model: Optional[str] = None
    max_duration: float = 120.0
    min_duration: float = 1.0
    language_code: Optional[str] = None
    vad_aggressiveness: Optional[int] = None
    disable_silence_detection: bool = False
    previous_text: Optional[str] = None
    on_partial: Any = None


class VoiceProvider(Protocol):
    async def tts(
        self,
        *,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        instructions: Optional[str] = None,
        audio_format: Optional[str] = None,
        speed: Optional[float] = None,
        debug: bool = False,
        debug_dir: Any = None,
        save_audio: bool = False,
        audio_dir: Any = None,
    ) -> tuple[bool, Optional[dict], Optional[dict]]: ...

    async def batch_stt(
        self,
        *,
        audio_file: BinaryIO,
        model: str = DEFAULT_BATCH_STT_MODEL,
        base_url: Optional[str] = None,
    ) -> Optional[dict]: ...

    async def realtime_stt(
        self,
        *,
        max_duration: float,
        min_duration: float,
        model: str = DEFAULT_REALTIME_STT_MODEL,
        base_url: Optional[str] = None,
        language_code: Optional[str] = None,
        vad_aggressiveness: Optional[int] = None,
        disable_silence_detection: bool = False,
        previous_text: Optional[str] = None,
        on_partial: Any = None,
    ) -> Optional[dict]: ...


class ElevenLabsVoiceProvider:
    """Compatibility-friendly provider facade hiding ElevenLabs SDK spread."""

    async def tts(
        self,
        *,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        instructions: Optional[str] = None,
        audio_format: Optional[str] = None,
        speed: Optional[float] = None,
        debug: bool = False,
        debug_dir: Any = None,
        save_audio: bool = False,
        audio_dir: Any = None,
    ) -> tuple[bool, Optional[dict], Optional[dict]]:
        from .elevenlabs_tts_stt import elevenlabs_tts

        del base_url
        settings = get_runtime_context().settings()
        return await elevenlabs_tts(
            text=text,
            voice=voice or _first(settings.tts_voices, DEFAULT_TTS_VOICE),
            model=model or _first(settings.tts_models, DEFAULT_TTS_MODEL),
            instructions=instructions,
            audio_format=audio_format,
            debug=debug,
            debug_dir=debug_dir,
            save_audio=save_audio,
            audio_dir=audio_dir,
            speed=speed if speed is not None else settings.tts_speed,
        )

    async def batch_stt(
        self,
        *,
        audio_file: BinaryIO,
        model: str = DEFAULT_BATCH_STT_MODEL,
        base_url: Optional[str] = None,
    ) -> Optional[dict]:
        from .elevenlabs_tts_stt import elevenlabs_stt

        del base_url
        return await elevenlabs_stt(audio_file=audio_file, model=model)

    async def realtime_stt(
        self,
        *,
        max_duration: float,
        min_duration: float,
        model: str = DEFAULT_REALTIME_STT_MODEL,
        base_url: Optional[str] = None,
        language_code: Optional[str] = None,
        vad_aggressiveness: Optional[int] = None,
        disable_silence_detection: bool = False,
        previous_text: Optional[str] = None,
        on_partial: Any = None,
    ) -> Optional[dict]:
        from .elevenlabs_realtime_stt import realtime_transcribe

        del model, base_url
        settings = get_runtime_context().settings()
        return await realtime_transcribe(
            api_key=settings.elevenlabs_api_key,
            max_duration=max_duration,
            min_duration=min_duration,
            language_code=language_code if language_code is not None else settings.stt_language,
            vad_aggressiveness=vad_aggressiveness,
            disable_silence_detection=disable_silence_detection,
            previous_text=previous_text,
            on_partial=on_partial,
        )


class SpeechService:
    """Small caller-facing API for provider-backed speech calls.

    The service owns provider registry initialization, endpoint/model/voice
    selection, and the ElevenLabs compatibility adapter. Listening orchestration
    policy belongs in ``VoiceTranscriber``; ``listen`` remains as a legacy thin
    passthrough for direct provider STT callers.
    """

    def __init__(
        self,
        *,
        provider: Optional[VoiceProvider] = None,
        registry: Any = provider_registry,
    ):
        self.provider = provider or get_voice_provider()
        self.registry = registry

    async def speak(self, options: SpeakOptions) -> tuple[bool, Optional[dict], Optional[dict]]:
        await self.registry.initialize()
        endpoint = self._select_tts_endpoint(options)
        voice = self._select_voice(options, endpoint)
        model = self._select_tts_model(options, endpoint)
        settings = get_runtime_context().settings()

        return await self.provider.tts(
            text=options.text,
            voice=voice,
            model=model,
            base_url=options.base_url or (endpoint.base_url if endpoint else None),
            instructions=options.instructions,
            audio_format=options.audio_format,
            speed=options.speed if options.speed is not None else settings.tts_speed,
            debug=options.debug,
            debug_dir=options.debug_dir,
            save_audio=options.save_audio,
            audio_dir=options.audio_dir,
        )

    async def listen(self, options: ListenOptions) -> Optional[dict]:
        """Legacy provider passthrough for direct STT callers.

        This method selects the configured STT endpoint and calls the provider
        once. It intentionally does not retry, fall back to local recording, or
        normalize no-speech responses; conversation listening policy lives in
        ``voice_mode.voice_transcriber.VoiceTranscriber``.
        """
        await self.registry.initialize()

        if options.audio_file is not None:
            endpoint = self._select_stt_endpoint(options.model or DEFAULT_BATCH_STT_MODEL)
            return await self.provider.batch_stt(
                audio_file=options.audio_file,
                model=options.model or DEFAULT_BATCH_STT_MODEL,
                base_url=endpoint.base_url if endpoint else None,
            )

        endpoint = self._select_stt_endpoint(options.model or DEFAULT_REALTIME_STT_MODEL)
        return await self.provider.realtime_stt(
            max_duration=options.max_duration,
            min_duration=options.min_duration,
            model=options.model or DEFAULT_REALTIME_STT_MODEL,
            base_url=endpoint.base_url if endpoint else None,
            language_code=options.language_code,
            vad_aggressiveness=options.vad_aggressiveness,
            disable_silence_detection=options.disable_silence_detection,
            previous_text=options.previous_text,
            on_partial=options.on_partial,
        )

    def _select_tts_endpoint(self, options: SpeakOptions) -> Optional[EndpointInfo]:
        selector = getattr(self.registry, "select_tts_endpoint", None)
        if selector:
            return selector(voice=options.voice, model=options.model, base_url=options.base_url)

        if options.base_url:
            endpoints = self.registry.get_endpoints("tts")
            endpoint = next((e for e in endpoints if e.base_url == options.base_url), None)
            if endpoint:
                return endpoint

        if options.voice:
            endpoint = self.registry.find_endpoint_with_voice(options.voice)
            if endpoint:
                return endpoint
        if options.model:
            endpoint = self.registry.find_endpoint_with_model("tts", options.model)
            if endpoint:
                return endpoint
        endpoints = self.registry.get_endpoints("tts")
        return endpoints[0] if endpoints else None

    def _select_stt_endpoint(self, model: str) -> Optional[EndpointInfo]:
        selector = getattr(self.registry, "select_stt_endpoint", None)
        if selector:
            return selector(model=model)

        endpoint = self.registry.find_endpoint_with_model("stt", model)
        if endpoint:
            return endpoint
        endpoints = self.registry.get_endpoints("stt")
        return endpoints[0] if endpoints else None

    def _select_voice(self, options: SpeakOptions, endpoint: Optional[EndpointInfo]) -> str:
        if options.voice:
            return options.voice
        settings = get_runtime_context().settings()
        return _first(
            endpoint.voices if endpoint else (),
            _first(settings.tts_voices, DEFAULT_TTS_VOICE),
        )

    def _select_tts_model(self, options: SpeakOptions, endpoint: Optional[EndpointInfo]) -> str:
        if options.model:
            return options.model
        settings = get_runtime_context().settings()
        return _first(
            endpoint.models if endpoint else (),
            _first(settings.tts_models, DEFAULT_TTS_MODEL),
        )


_provider: VoiceProvider | None = None
_speech_service: SpeechService | None = None


def _first(values: Any, default: str) -> str:
    return next(iter(values), default) if values else default


def get_voice_provider() -> VoiceProvider:
    global _provider
    if _provider is None:
        _provider = ElevenLabsVoiceProvider()
    return _provider


def get_speech_service() -> SpeechService:
    global _speech_service
    if _speech_service is None:
        _speech_service = SpeechService()
    return _speech_service


async def speak(options: SpeakOptions) -> tuple[bool, Optional[dict], Optional[dict]]:
    """Compatibility-friendly module function for caller-oriented TTS."""

    return await get_speech_service().speak(options)


async def listen(options: ListenOptions) -> Optional[dict]:
    """Compatibility wrapper for the legacy STT provider passthrough.

    Conversational microphone turns should use ``VoiceTranscriber`` instead;
    this wrapper intentionally performs one provider STT call only.
    """

    return await get_speech_service().listen(options)
