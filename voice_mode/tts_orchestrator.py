"""Deep TTS orchestration boundary for playback-oriented speech synthesis."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .runtime_context import get_runtime_context
from .utils import get_event_logger
from .voice_provider import SpeakOptions, SpeechService, VoiceProvider, get_speech_service

logger = logging.getLogger("voicemode")


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice: str
    model: str
    base_url: str
    instructions: Optional[str] = None
    audio_format: Optional[str] = None
    speed: Optional[float] = None
    debug: bool = False
    debug_dir: Optional[Path] = None
    save_audio: bool = False
    audio_dir: Optional[Path] = None

    def to_speak_options(self) -> SpeakOptions:
        return SpeakOptions(
            text=self.text,
            voice=self.voice,
            model=self.model,
            base_url=self.base_url,
            instructions=self.instructions,
            audio_format=self.audio_format,
            speed=self.speed,
            debug=self.debug,
            debug_dir=self.debug_dir,
            save_audio=self.save_audio,
            audio_dir=self.audio_dir,
        )


class TTSOrchestrator:
    def __init__(
        self,
        provider: Optional[VoiceProvider] = None,
        speech_service: Optional[SpeechService] = None,
    ):
        self.speech_service = speech_service or (
            SpeechService(provider=provider) if provider is not None else get_speech_service()
        )

    async def speak(self, request: TTSRequest) -> tuple[bool, Optional[dict]]:
        settings = get_runtime_context().settings()
        event_logger = get_event_logger()
        if event_logger:
            event_logger.log_event(event_logger.TTS_START, {
                "message": request.text[:200],
                "voice": request.voice,
                "model": request.model,
                "base_url": request.base_url,
            })

        logger.info(
            "TTS orchestrator request: endpoint=%s model=%s voice=%s format=%s",
            request.base_url,
            request.model,
            request.voice,
            request.audio_format or "default",
        )

        options = request.to_speak_options()
        if options.speed is None:
            options = SpeakOptions(
                text=options.text,
                voice=options.voice,
                model=options.model,
                base_url=options.base_url,
                instructions=options.instructions,
                audio_format=options.audio_format,
                speed=settings.tts_speed,
                debug=options.debug,
                debug_dir=options.debug_dir,
                save_audio=options.save_audio,
                audio_dir=options.audio_dir,
            )

        success, metrics, _config = await self.speech_service.speak(options)
        return success, metrics
