"""
Compatibility provider selection facade for voice-mode.

New code should use voice_mode.voice_provider.SpeechService. This module remains
load-bearing for diagnostics and legacy imports by exposing provider-selection
metadata without exposing provider discovery internals to speech callers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .provider_discovery import EndpointInfo, provider_registry
from .voice_provider import DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, get_voice_provider


async def get_tts_client_and_voice(
    voice: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[Any, str, str, EndpointInfo]:
    """Return selected TTS compatibility tuple for legacy callers.

    The first element is the VoiceProvider adapter, not a raw SDK client. Legacy
    callers in this repository only inspect the selected voice/model/endpoint.
    """

    await provider_registry.initialize()
    endpoint = provider_registry.select_tts_endpoint(
        voice=voice,
        model=model,
        base_url=base_url,
    )
    if endpoint is None:
        raise RuntimeError("No TTS provider endpoints configured")

    selected_voice = _select_voice_for_endpoint(endpoint, voice)
    selected_model = _select_model_for_endpoint(endpoint, model)
    return get_voice_provider(), selected_voice, selected_model, endpoint


async def get_stt_client(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[Any, str, EndpointInfo]:
    """Return selected STT compatibility tuple for legacy callers."""

    await provider_registry.initialize()
    selected_model = model or "scribe_v2"
    endpoint = provider_registry.select_stt_endpoint(model=selected_model, base_url=base_url)
    if endpoint is None:
        raise RuntimeError("No STT provider endpoints configured")
    return get_voice_provider(), selected_model, endpoint


def _select_voice_for_endpoint(
    endpoint_info: EndpointInfo,
    requested_voice: Optional[str] = None,
) -> str:
    """Select the best available voice for an endpoint."""

    if requested_voice:
        return requested_voice
    if endpoint_info.voices:
        return endpoint_info.voices[0]
    return DEFAULT_TTS_VOICE


def _select_model_for_endpoint(
    endpoint_info: EndpointInfo,
    requested_model: Optional[str] = None,
) -> str:
    """Select the best available model for an endpoint."""

    if requested_model:
        return requested_model
    if endpoint_info.models:
        return endpoint_info.models[0]
    return DEFAULT_TTS_MODEL


async def is_provider_available(provider_id: str, timeout: float = 2.0) -> bool:
    """Check if a configured provider id is available."""

    del timeout
    await provider_registry.initialize()
    normalized = provider_id.lower()
    if normalized in {"elevenlabs", "elevenlabs-tts"}:
        return bool(provider_registry.get_endpoints("tts"))
    if normalized == "elevenlabs-stt":
        return bool(provider_registry.get_endpoints("stt"))
    return False


def get_provider_by_voice(voice: str) -> Optional[Dict[str, Any]]:
    """Return provider metadata for a TTS voice."""

    endpoint = provider_registry.find_endpoint_with_voice(voice)
    if endpoint is None:
        endpoints = provider_registry.get_endpoints("tts")
        endpoint = endpoints[0] if endpoints else None

    return {
        "id": "elevenlabs",
        "name": "ElevenLabs TTS",
        "type": "tts",
        "base_url": endpoint.base_url if endpoint else "elevenlabs://tts",
        "voices": [voice or DEFAULT_TTS_VOICE],
    }


def select_best_voice(
    provider: str = "elevenlabs",
    available_voices: Optional[List[str]] = None,
) -> Optional[str]:
    """Select the best available voice for compatibility callers."""

    if provider and provider.lower() not in {"elevenlabs", "elevenlabs-tts"}:
        return None
    if available_voices:
        return available_voices[0]

    endpoints = provider_registry.get_endpoints("tts")
    if endpoints and endpoints[0].voices:
        return endpoints[0].voices[0]
    return DEFAULT_TTS_VOICE
