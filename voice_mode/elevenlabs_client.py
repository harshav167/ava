"""
ElevenLabs client wrapper for VoiceMode.

Provides batch STT (speech-to-text) via the ElevenLabs SDK.
TTS is handled directly in elevenlabs_tts_stt.py using the SDK's built-in stream() player.
"""

import logging
import time
from typing import Optional

from elevenlabs.client import ElevenLabs

logger = logging.getLogger("voicemode")

_client: Optional[ElevenLabs] = None
_client_api_key: Optional[str] = None


def get_client(api_key: str) -> ElevenLabs:
    """Get or create singleton ElevenLabs client."""
    from .config import ELEVENLABS_HTTP_TIMEOUT

    global _client, _client_api_key
    if _client is None or _client_api_key != api_key:
        _client = ElevenLabs(api_key=api_key, timeout=ELEVENLABS_HTTP_TIMEOUT)
        _client_api_key = api_key
    return _client


def elevenlabs_stt_batch(
    audio_file,
    model_id: str = "scribe_v2",
    language_code: Optional[str] = None,
    keyterms: Optional[list] = None,
    api_key: str = "",
) -> dict:
    """
    Transcribe audio using ElevenLabs Scribe v2 (batch/non-realtime).

    This is the fallback STT path when realtime is not available.

    Args:
        audio_file: File-like object with audio data
        model_id: STT model ID (scribe_v2 for batch)
        language_code: ISO language code (None for auto-detect)
        keyterms: List of terms to bias recognition toward
        api_key: ElevenLabs API key

    Returns:
        Dict with 'text' and optional 'language' keys
    """
    client = get_client(api_key)

    kwargs = {"file": audio_file, "model_id": model_id}
    if language_code and language_code != "auto":
        kwargs["language_code"] = language_code
    if keyterms:
        kwargs["keyterms"] = keyterms

    start_time = time.perf_counter()
    result = client.speech_to_text.convert(**kwargs)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    text = result.text.strip() if result.text else ""
    lang = getattr(result, "language_code", None)

    logger.info(f"ElevenLabs STT batch: '{text[:80]}' lang={lang} ({elapsed_ms:.0f}ms)")

    return {
        "text": text,
        "language": lang,
        "elapsed_ms": elapsed_ms,
    }
