"""
Provider discovery and registry management for voice-mode.

The registry is intentionally small: VoiceMode currently supports ElevenLabs
for TTS/STT, and SpeechService uses this registry for endpoint/model/voice
selection before delegating to the provider adapter.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("voicemode")


ELEVENLABS_TTS_MODELS = [
    "eleven_flash_v2_5",
    "eleven_v3",
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_flash_v2",
]

ELEVENLABS_STT_MODELS = [
    "scribe_v2_realtime",
    "scribe_v2",
]


@dataclass
class EndpointInfo:
    """Information about a configured voice endpoint."""

    base_url: str
    models: List[str]
    voices: List[str]
    provider_type: Optional[str] = None
    last_check: Optional[str] = None
    last_error: Optional[str] = None


def detect_provider_type(base_url: str) -> str:
    """Detect the provider represented by a configured endpoint URL."""

    if not base_url:
        return "unknown"
    if base_url.startswith("elevenlabs://") or "elevenlabs" in base_url.lower():
        return "elevenlabs"
    return "unknown"


def is_local_provider(base_url: str) -> bool:
    """Return whether an endpoint should be treated as local for audio prep."""

    if not base_url:
        return False
    normalized = base_url.lower()
    return (
        "localhost" in normalized
        or "127.0.0.1" in normalized
        or normalized.startswith("http://0.0.0.0")
        or normalized.startswith("http://[::1]")
    )


class ProviderRegistry:
    """Configured provider registry used by SpeechService selection."""

    def __init__(self):
        self.registry: Dict[str, Dict[str, EndpointInfo]] = {
            "tts": {},
            "stt": {},
        }
        self._discovery_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Initialize the registry from current configuration."""

        if self._initialized:
            return

        async with self._discovery_lock:
            if self._initialized:
                return

            from .config import (
                ELEVENLABS_TTS_VOICE,
                STT_BASE_URLS,
                TTS_BASE_URLS,
                TTS_MODELS,
                TTS_VOICES,
            )

            logger.info("Initializing provider registry...")
            self.registry = {"tts": {}, "stt": {}}

            voices = list(TTS_VOICES)
            if ELEVENLABS_TTS_VOICE and ELEVENLABS_TTS_VOICE not in voices:
                voices.insert(0, ELEVENLABS_TTS_VOICE)
            if not voices:
                voices = ["k4hP4cQadSZQc0Oar2Ld"]

            tts_models = list(TTS_MODELS) or ["eleven_v3"]
            for model in ELEVENLABS_TTS_MODELS:
                if model not in tts_models:
                    tts_models.append(model)

            for url in TTS_BASE_URLS:
                self.registry["tts"][url] = EndpointInfo(
                    base_url=url,
                    models=tts_models,
                    voices=voices,
                    provider_type=detect_provider_type(url),
                )

            for url in STT_BASE_URLS:
                self.registry["stt"][url] = EndpointInfo(
                    base_url=url,
                    models=list(ELEVENLABS_STT_MODELS),
                    voices=[],
                    provider_type=detect_provider_type(url),
                )

            self._initialized = True
            logger.info(
                "Provider registry initialized with %s TTS and %s STT endpoints",
                len(self.registry["tts"]),
                len(self.registry["stt"]),
            )

    async def refresh(self) -> None:
        """Force a reload from current configuration."""

        async with self._discovery_lock:
            self._initialized = False
        await self.initialize()

    def get_endpoints(self, service_type: str) -> List[EndpointInfo]:
        """Get endpoints for a service type in configured priority order."""

        if service_type not in self.registry:
            return []

        from .config import STT_BASE_URLS, TTS_BASE_URLS

        base_urls = TTS_BASE_URLS if service_type == "tts" else STT_BASE_URLS
        configured = self.registry[service_type]
        endpoints = [configured[url] for url in base_urls if url in configured]
        endpoints.extend(info for url, info in configured.items() if url not in base_urls)
        return endpoints

    def get_healthy_endpoints(self, service_type: str) -> List[EndpointInfo]:
        """Return configured endpoints that have not recorded a failure."""

        return [endpoint for endpoint in self.get_endpoints(service_type) if not endpoint.last_error]

    def select_tts_endpoint(
        self,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Optional[EndpointInfo]:
        """Select the TTS endpoint SpeechService should use."""

        if base_url:
            endpoint = self.registry["tts"].get(base_url)
            if endpoint:
                return endpoint
        if voice:
            endpoint = self.find_endpoint_with_voice(voice)
            if endpoint:
                return endpoint
        if model:
            endpoint = self.find_endpoint_with_model("tts", model)
            if endpoint:
                return endpoint
        endpoints = self.get_healthy_endpoints("tts") or self.get_endpoints("tts")
        return endpoints[0] if endpoints else None

    def select_stt_endpoint(
        self,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Optional[EndpointInfo]:
        """Select the STT endpoint SpeechService should use."""

        if base_url:
            endpoint = self.registry["stt"].get(base_url)
            if endpoint:
                return endpoint
        if model:
            endpoint = self.find_endpoint_with_model("stt", model)
            if endpoint:
                return endpoint
        endpoints = self.get_healthy_endpoints("stt") or self.get_endpoints("stt")
        return endpoints[0] if endpoints else None

    def find_endpoint_with_voice(self, voice: str) -> Optional[EndpointInfo]:
        """Find the first TTS endpoint that supports a specific voice."""

        return next(
            (endpoint for endpoint in self.get_endpoints("tts") if voice in endpoint.voices),
            None,
        )

    def find_endpoint_with_model(self, service_type: str, model: str) -> Optional[EndpointInfo]:
        """Find the first endpoint that supports a specific model."""

        return next(
            (endpoint for endpoint in self.get_endpoints(service_type) if model in endpoint.models),
            None,
        )

    def get_registry_for_llm(self) -> Dict[str, Any]:
        """Get registry data formatted for LLM inspection."""

        return {
            "tts": {
                url: {
                    "models": info.models,
                    "voices": info.voices,
                    "provider_type": info.provider_type,
                    "last_check": info.last_check,
                    "last_error": info.last_error,
                }
                for url, info in self.registry["tts"].items()
            },
            "stt": {
                url: {
                    "models": info.models,
                    "provider_type": info.provider_type,
                    "last_check": info.last_check,
                    "last_error": info.last_error,
                }
                for url, info in self.registry["stt"].items()
            },
        }

    async def mark_failed(self, service_type: str, base_url: str, error: str):
        """Record that an endpoint failed."""

        if base_url in self.registry.get(service_type, {}):
            self.registry[service_type][base_url].last_error = error
            self.registry[service_type][base_url].last_check = datetime.now(timezone.utc).isoformat()
            logger.info("%s endpoint %s failed: %s", service_type, base_url, error)


provider_registry = ProviderRegistry()
