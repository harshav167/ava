"""
Provider discovery and registry management for voice-mode.

ElevenLabs-only provider system. All TTS/STT goes through ElevenLabs.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config
from .config import TTS_BASE_URLS, STT_BASE_URLS

logger = logging.getLogger("voicemode")


# ElevenLabs model lists
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


def detect_provider_type(base_url: str) -> str:
    """Detect provider type from base URL.

    Always returns "elevenlabs" for any valid URL since ElevenLabs
    is the only supported provider.
    """
    if not base_url:
        return "unknown"
    return "elevenlabs"


def is_local_provider(base_url: str) -> bool:
    """Check if a provider URL is for a local service.

    Always returns False — no local providers are supported.
    """
    return False


@dataclass
class EndpointInfo:
    """Information about a discovered endpoint."""
    base_url: str
    models: List[str]
    voices: List[str]  # Only for TTS
    provider_type: Optional[str] = None  # e.g., "elevenlabs"
    last_check: Optional[str] = None  # ISO format timestamp of last attempt
    last_error: Optional[str] = None  # Last error if any


class ProviderRegistry:
    """Manages discovery and selection of ElevenLabs voice service endpoints."""

    def __init__(self):
        self.registry: Dict[str, Dict[str, EndpointInfo]] = {
            "tts": {},
            "stt": {}
        }
        self._discovery_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Initialize the registry with configured ElevenLabs endpoints."""
        if self._initialized:
            return

        async with self._discovery_lock:
            if self._initialized:  # Double-check after acquiring lock
                return

            logger.info("Initializing provider registry...")

            # Initialize TTS endpoints
            for url in TTS_BASE_URLS:
                self.registry["tts"][url] = EndpointInfo(
                    base_url=url,
                    models=ELEVENLABS_TTS_MODELS,
                    voices=[],  # ElevenLabs voices are referenced by ID, not name
                    provider_type="elevenlabs"
                )

            # Initialize STT endpoints
            for url in STT_BASE_URLS:
                self.registry["stt"][url] = EndpointInfo(
                    base_url=url,
                    models=ELEVENLABS_STT_MODELS,
                    voices=[],
                    provider_type="elevenlabs"
                )

            self._initialized = True
            logger.info(
                f"Provider registry initialized with "
                f"{len(self.registry['tts'])} TTS and "
                f"{len(self.registry['stt'])} STT endpoints"
            )

    def get_endpoints(self, service_type: str) -> List[EndpointInfo]:
        """Get all endpoints for a service type in priority order."""
        endpoints = []

        # Return endpoints in the order they were configured
        base_urls = TTS_BASE_URLS if service_type == "tts" else STT_BASE_URLS

        for url in base_urls:
            info = self.registry[service_type].get(url)
            if info:
                endpoints.append(info)

        return endpoints

    def get_healthy_endpoints(self, service_type: str) -> List[EndpointInfo]:
        """Deprecated: Use get_endpoints instead. Returns all endpoints."""
        return self.get_endpoints(service_type)

    def find_endpoint_with_voice(self, voice: str) -> Optional[EndpointInfo]:
        """Find the first TTS endpoint that supports a specific voice."""
        for endpoint in self.get_endpoints("tts"):
            if voice in endpoint.voices:
                return endpoint
        return None

    def find_endpoint_with_model(self, service_type: str, model: str) -> Optional[EndpointInfo]:
        """Find the first endpoint that supports a specific model."""
        for endpoint in self.get_endpoints(service_type):
            if model in endpoint.models:
                return endpoint
        return None

    def get_registry_for_llm(self) -> Dict[str, Any]:
        """Get registry data formatted for LLM inspection."""
        return {
            "tts": {
                url: {
                    "models": info.models,
                    "voices": info.voices,
                    "provider_type": info.provider_type,
                    "last_check": info.last_check,
                    "last_error": info.last_error
                }
                for url, info in self.registry["tts"].items()
            },
            "stt": {
                url: {
                    "models": info.models,
                    "provider_type": info.provider_type,
                    "last_check": info.last_check,
                    "last_error": info.last_error
                }
                for url, info in self.registry["stt"].items()
            }
        }

    async def mark_failed(self, service_type: str, base_url: str, error: str):
        """Record that an endpoint failed.

        This updates the last_error and last_check fields for diagnostics,
        but doesn't prevent the endpoint from being tried again.
        """
        if base_url in self.registry[service_type]:
            self.registry[service_type][base_url].last_error = error
            self.registry[service_type][base_url].last_check = datetime.now(timezone.utc).isoformat()
            logger.info(f"{service_type} endpoint {base_url} failed: {error}")


# Global registry instance
provider_registry = ProviderRegistry()
