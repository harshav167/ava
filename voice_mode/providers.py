"""
Provider selection and management for voice-mode.

ElevenLabs-only provider system. Legacy function signatures kept for backward
compatibility but all paths return ElevenLabs info.
"""

import logging
from typing import Dict, Optional, List, Any, Tuple

from .config import TTS_VOICES, TTS_MODELS, TTS_BASE_URLS, OPENAI_API_KEY, get_voice_preferences
from .provider_discovery import provider_registry, EndpointInfo, is_local_provider

logger = logging.getLogger("voicemode")


async def get_tts_client_and_voice(
    voice: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> None:
    """Deprecated — use elevenlabs_tts directly."""
    raise NotImplementedError("Use elevenlabs_tts directly from voice_mode.elevenlabs_tts_stt")


async def get_stt_client(
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> None:
    """Deprecated — use elevenlabs_stt directly."""
    raise NotImplementedError("Use elevenlabs_stt directly from voice_mode.elevenlabs_tts_stt")


def _select_voice_for_endpoint(endpoint_info: EndpointInfo) -> str:
    """Select the best available voice for an endpoint."""
    if TTS_VOICES:
        return TTS_VOICES[0]
    return "k4hP4cQadSZQc0Oar2Ld"


def _select_model_for_endpoint(endpoint_info: EndpointInfo, requested_model: Optional[str] = None) -> str:
    """Select the best available model for an endpoint."""
    if requested_model:
        return requested_model
    if TTS_MODELS:
        return TTS_MODELS[0]
    return "eleven_v3"


# Compatibility functions for existing code

async def is_provider_available(provider_id: str, timeout: float = 2.0) -> bool:
    """Check if a provider is available (compatibility function)."""
    await provider_registry.initialize()

    # Only ElevenLabs is supported
    if provider_id in ("elevenlabs", "elevenlabs-stt"):
        return True
    return False


def get_provider_by_voice(voice: str) -> Optional[Dict[str, Any]]:
    """Get provider info by voice — always returns ElevenLabs."""
    from .config import ELEVENLABS_TTS_VOICE

    return {
        "id": "elevenlabs",
        "name": "ElevenLabs TTS",
        "type": "tts",
        "base_url": "elevenlabs://tts",
        "voices": [voice if voice else ELEVENLABS_TTS_VOICE]
    }


def select_best_voice(provider: str = "elevenlabs", available_voices: Optional[List[str]] = None) -> Optional[str]:
    """Select the best available voice — returns ElevenLabs default."""
    user_preferences = get_voice_preferences()
    if user_preferences:
        return user_preferences[0]
    if available_voices:
        return available_voices[0]
    return "k4hP4cQadSZQc0Oar2Ld"
