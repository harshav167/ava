"""
ElevenLabs TTS and STT for VoiceMode.

All voice synthesis and transcription goes through ElevenLabs.
"""

import logging
from typing import Optional, Tuple, Dict, Any

from .config import (
    ELEVENLABS_API_KEY, ELEVENLABS_TTS_MODEL, ELEVENLABS_TTS_VOICE,
    STT_PROMPT, WHISPER_LANGUAGE,
)

logger = logging.getLogger("voicemode")


async def simple_tts_failover(
    text: str,
    voice: str,
    model: str,
    **kwargs
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    ElevenLabs TTS - converts text to speech and plays it.

    Returns:
        Tuple of (success, metrics, config)
    """
    logger.info(f"simple_tts_failover called with: text='{text[:50]}...', voice={voice}, model={model}")
    logger.info(f"kwargs: {kwargs}")

    try:
        from .elevenlabs_client import get_client
        from elevenlabs import stream as elevenlabs_play
        import time as _time

        # Always use the configured ElevenLabs voice ID
        el_voice = ELEVENLABS_TTS_VOICE

        logger.info(f"ElevenLabs TTS: voice={el_voice}, model={ELEVENLABS_TTS_MODEL}")

        el_client = get_client(ELEVENLABS_API_KEY)

        gen_start = _time.perf_counter()
        audio_stream = el_client.text_to_speech.stream(
            text=text,
            voice_id=el_voice,
            model_id=ELEVENLABS_TTS_MODEL,
        )

        # Use the SDK's built-in stream() player (uses mpv/ffplay)
        elevenlabs_play(audio_stream)
        total_time = _time.perf_counter() - gen_start

        # SDK stream() combines generation and playback into one blocking call,
        # so both values reflect the total elapsed time.
        metrics = {
            "generation": round(total_time * 1000, 1),
            "playback": round(total_time * 1000, 1),
        }
        config = {
            "base_url": "elevenlabs://tts",
            "provider": "elevenlabs",
            "voice": el_voice,
            "model": ELEVENLABS_TTS_MODEL,
            "endpoint": "api.elevenlabs.io/v1/text-to-speech",
        }
        logger.info(f"ElevenLabs TTS succeeded: {total_time:.2f}s")
        return True, metrics, config

    except Exception as e:
        logger.error(f"ElevenLabs TTS failed: {e}")
        error_config = {
            "error_type": "all_providers_failed",
            "attempted_endpoints": [{
                "endpoint": "api.elevenlabs.io/v1/text-to-speech",
                "provider": "elevenlabs",
                "voice": ELEVENLABS_TTS_VOICE,
                "model": ELEVENLABS_TTS_MODEL,
                "error": str(e),
            }],
        }
        return False, None, error_config


async def simple_stt_failover(
    audio_file,
    model: str = "scribe_v2",
    **kwargs
) -> Optional[Dict[str, Any]]:
    """
    ElevenLabs STT - converts speech to text using ElevenLabs batch API.

    Returns:
        Dict with transcription result or error information:
        - Success: {"text": "...", "provider": "...", "endpoint": "...", "metrics": {...}}
        - No speech: {"error_type": "no_speech", "provider": "...", "metrics": {...}}
        - Failed: {"error_type": "connection_failed", "attempted_endpoints": [...]}
    """
    import time

    # Get file size for metrics
    file_size_bytes = 0
    try:
        start_pos = audio_file.tell()
        audio_file.seek(0, 2)  # Seek to end
        file_size_bytes = audio_file.tell()
        audio_file.seek(start_pos)  # Restore position
        if not isinstance(file_size_bytes, int):
            file_size_bytes = 0
    except Exception as e:
        logger.debug(f"Could not get file size: {e}")
        file_size_bytes = 0

    # Log STT request details
    logger.info("STT: Starting speech-to-text conversion via ElevenLabs")
    if file_size_bytes > 0:
        logger.info(f"  Audio file size: {file_size_bytes / 1024:.1f}KB")

    try:
        from .elevenlabs_client import elevenlabs_stt_batch

        # Parse keyterms from STT_PROMPT (comma-separated)
        keyterms = [t.strip() for t in STT_PROMPT.split(",") if t.strip()] if STT_PROMPT else None

        # Reset file position for this attempt
        audio_file.seek(0)

        request_start = time.perf_counter()
        result = elevenlabs_stt_batch(
            audio_file=audio_file,
            model_id="scribe_v2",
            language_code=WHISPER_LANGUAGE if WHISPER_LANGUAGE and WHISPER_LANGUAGE != "auto" else None,
            keyterms=keyterms,
            api_key=ELEVENLABS_API_KEY,
        )
        request_time_ms = (time.perf_counter() - request_start) * 1000

        text = result.get("text", "").strip()
        metrics = {
            "file_size_bytes": file_size_bytes,
            "request_time_ms": round(request_time_ms, 1),
            "is_local": False,
        }

        if text:
            logger.info(f"ElevenLabs STT batch succeeded: '{text[:80]}' ({request_time_ms:.0f}ms)")
            return {"text": text, "provider": "elevenlabs", "endpoint": "api.elevenlabs.io/v1/speech-to-text", "metrics": metrics}
        else:
            logger.warning("ElevenLabs STT returned empty result")
            return {"error_type": "no_speech", "provider": "elevenlabs", "metrics": metrics}

    except Exception as e:
        logger.error(f"ElevenLabs STT batch failed: {e}")
        return {
            "error_type": "connection_failed",
            "attempted_endpoints": [{
                "endpoint": "api.elevenlabs.io/v1/speech-to-text",
                "provider": "elevenlabs",
                "error": str(e),
            }],
        }
