"""
ElevenLabs client wrapper for VoiceMode.

Provides TTS (text-to-speech) and STT (speech-to-text) via the ElevenLabs SDK,
integrating with VoiceMode's audio playback and provider failover systems.
"""

import logging
import time
from typing import Optional, Iterator

from elevenlabs import ElevenLabs

logger = logging.getLogger("voicemode")

_client: Optional[ElevenLabs] = None
_client_api_key: Optional[str] = None


def get_client(api_key: str) -> ElevenLabs:
    """Get or create singleton ElevenLabs client."""
    global _client, _client_api_key
    if _client is None or _client_api_key != api_key:
        _client = ElevenLabs(api_key=api_key)
        _client_api_key = api_key
    return _client


def elevenlabs_tts_stream(
    text: str,
    voice_id: str,
    model_id: str = "eleven_flash_v2_5",
    output_format: str = "pcm_24000",
    speed: float = 1.0,
    api_key: str = "",
) -> Iterator[bytes]:
    """
    Generate speech using ElevenLabs TTS (streaming).

    Returns an iterator of audio bytes chunks. Uses the synchronous SDK
    streaming method which yields chunks as they're generated.

    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID
        model_id: TTS model ID
        output_format: Audio output format (pcm_24000 for streaming playback)
        speed: Playback speed (0.25 to 4.0)
        api_key: ElevenLabs API key
    """
    client = get_client(api_key)

    kwargs = {
        "text": text,
        "voice_id": voice_id,
        "model_id": model_id,
        "output_format": output_format,
    }

    if speed != 1.0:
        from elevenlabs import VoiceSettings
        kwargs["voice_settings"] = VoiceSettings(speed=speed)

    logger.info(f"ElevenLabs TTS: voice={voice_id}, model={model_id}, format={output_format}")
    return client.text_to_speech.stream(**kwargs)


def elevenlabs_tts_convert(
    text: str,
    voice_id: str,
    model_id: str = "eleven_flash_v2_5",
    output_format: str = "mp3_44100_128",
    speed: float = 1.0,
    api_key: str = "",
) -> bytes:
    """
    Generate speech using ElevenLabs TTS (non-streaming, full audio).

    Returns complete audio bytes. Use for saving to file or when
    full audio is needed before playback.
    """
    client = get_client(api_key)

    kwargs = {
        "text": text,
        "voice_id": voice_id,
        "model_id": model_id,
        "output_format": output_format,
    }

    if speed != 1.0:
        from elevenlabs import VoiceSettings
        kwargs["voice_settings"] = VoiceSettings(speed=speed)

    audio_iterator = client.text_to_speech.convert(**kwargs)
    return b"".join(audio_iterator)


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

    logger.info(f"ElevenLabs STT batch: '{text[:80]}...' lang={lang} ({elapsed_ms:.0f}ms)")

    return {
        "text": text,
        "language": lang,
        "elapsed_ms": elapsed_ms,
    }
