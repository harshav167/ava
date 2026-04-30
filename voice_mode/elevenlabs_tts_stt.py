"""
ElevenLabs TTS and STT for VoiceMode.

All voice synthesis and transcription goes through ElevenLabs.
"""

import asyncio
import logging
import os
import signal
import subprocess
import tempfile
import threading
from typing import Optional, Tuple, Dict, Any

from .config import (
    ELEVENLABS_API_KEY, ELEVENLABS_TTS_MODEL, ELEVENLABS_TTS_VOICE,
    STT_PROMPT, STT_LANGUAGE,
)

# Backward compatibility alias
WHISPER_LANGUAGE = STT_LANGUAGE

logger = logging.getLogger("voicemode")

_playback_process_lock = threading.Lock()
_current_playback_cancel_event: threading.Event | None = None
_current_playback_process: subprocess.Popen | None = None
_active_playback_cancel_events: set[threading.Event] = set()
_active_playback_processes: set[subprocess.Popen] = set()


def _register_playback_event(cancel_event: threading.Event) -> None:
    """Track a TTS worker so later MCP turns can stop orphaned playback."""
    global _current_playback_cancel_event
    with _playback_process_lock:
        _active_playback_cancel_events.add(cancel_event)
        _current_playback_cancel_event = cancel_event


def _unregister_playback_event(cancel_event: threading.Event) -> None:
    global _current_playback_cancel_event
    with _playback_process_lock:
        _active_playback_cancel_events.discard(cancel_event)
        if _current_playback_cancel_event is cancel_event:
            _current_playback_cancel_event = None


def _register_playback_process(proc: subprocess.Popen, cancel_event: threading.Event) -> None:
    global _current_playback_process, _current_playback_cancel_event
    with _playback_process_lock:
        _active_playback_processes.add(proc)
        _active_playback_cancel_events.add(cancel_event)
        _current_playback_process = proc
        _current_playback_cancel_event = cancel_event


def _unregister_playback_process(proc: subprocess.Popen) -> None:
    global _current_playback_process
    with _playback_process_lock:
        _active_playback_processes.discard(proc)
        if _current_playback_process is proc:
            _current_playback_process = None


def _terminate_playback_process(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=2)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.warning(f"Failed to stop active playback process group: {e}")
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception as fallback_error:
            logger.warning(f"Failed to stop active playback process: {fallback_error}")


def stop_current_playback() -> None:
    """Stop all active ffplay processes and TTS workers started by ElevenLabs TTS."""
    global _current_playback_process, _current_playback_cancel_event
    with _playback_process_lock:
        procs = set(_active_playback_processes)
        events = set(_active_playback_cancel_events)
        if _current_playback_process is not None:
            procs.add(_current_playback_process)
        if _current_playback_cancel_event is not None:
            events.add(_current_playback_cancel_event)
        _active_playback_processes.clear()
        _active_playback_cancel_events.clear()
        _current_playback_process = None
        _current_playback_cancel_event = None

    for cancel_event in events:
        cancel_event.set()

    for proc in procs:
        _terminate_playback_process(proc)


async def elevenlabs_tts(
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
    logger.info(f"elevenlabs_tts called with: text='{text[:50]}...', voice={voice}, model={model}")
    logger.info(f"kwargs: {kwargs}")
    playback_cancel_event = threading.Event()
    _register_playback_event(playback_cancel_event)

    try:
        from .elevenlabs_client import get_client
        from .runtime_context import get_runtime_context
        from elevenlabs import VoiceSettings
        import time as _time
        import re

        # Use function params as overrides, fall back to config defaults
        el_voice = voice if voice else ELEVENLABS_TTS_VOICE
        el_model = model if model else ELEVENLABS_TTS_MODEL
        logger.info(f"ElevenLabs TTS: voice={el_voice}, model={el_model}")

        el_client = get_client(ELEVENLABS_API_KEY)
        settings = get_runtime_context().provider_settings()

        speed = kwargs.get("speed")
        if speed is None:
            speed = 1.2  # Default faster playback

        # Chunk long text into sentences to avoid timeout on ElevenLabs convert()
        # ElevenLabs handles up to ~5000 chars well, but very long texts can hang
        MAX_CHUNK_CHARS = 2000
        if len(text) > MAX_CHUNK_CHARS:
            # Split on sentence boundaries
            chunks = re.split(r'(?<=[.!?])\s+', text)
            # Merge small chunks to avoid too many API calls
            merged = []
            current = ""
            for chunk in chunks:
                if len(current) + len(chunk) + 1 > MAX_CHUNK_CHARS and current:
                    merged.append(current.strip())
                    current = chunk
                else:
                    current = current + " " + chunk if current else chunk
            if current.strip():
                merged.append(current.strip())
            logger.info(f"ElevenLabs TTS: split {len(text)} chars into {len(merged)} chunks")
        else:
            merged = [text]

        gen_start = _time.perf_counter()

        chunks_played = []  # Track which chunks were successfully played

        def _generate_and_play(chunks):
            """Run blocking ElevenLabs convert+play in a thread."""
            for i, chunk_text in enumerate(chunks):
                if playback_cancel_event.is_set():
                    logger.info("ElevenLabs TTS playback cancelled before next chunk")
                    break
                logger.info(f"ElevenLabs TTS chunk {i+1}/{len(chunks)}: {len(chunk_text)} chars")

                try:
                    convert_kwargs = {
                        "text": chunk_text,
                        "voice_id": el_voice,
                        "model_id": el_model,
                        "output_format": "mp3_44100_128",
                        "voice_settings": VoiceSettings(
                            speed=speed,
                            stability=settings.elevenlabs_voice_stability,
                            similarity_boost=settings.elevenlabs_voice_similarity_boost,
                            style=settings.elevenlabs_voice_style,
                            use_speaker_boost=settings.elevenlabs_voice_use_speaker_boost,
                        ),
                    }
                    if settings.elevenlabs_voice_seed is not None:
                        convert_kwargs["seed"] = settings.elevenlabs_voice_seed
                    audio_iterator = el_client.text_to_speech.convert(**convert_kwargs)

                    # Collect audio bytes with timeout protection
                    audio_bytes = b"".join(audio_iterator)

                    # Retry once if we got zero bytes
                    if len(audio_bytes) == 0:
                        logger.warning(f"ElevenLabs TTS chunk {i+1} returned 0 bytes, retrying in 1s...")
                        import time as _retry_time
                        _retry_time.sleep(1)
                        retry_kwargs = dict(convert_kwargs)
                        retry_kwargs["voice_settings"] = VoiceSettings(
                            speed=speed,
                            stability=settings.elevenlabs_voice_stability,
                            similarity_boost=settings.elevenlabs_voice_similarity_boost,
                            style=settings.elevenlabs_voice_style,
                            use_speaker_boost=settings.elevenlabs_voice_use_speaker_boost,
                        )
                        retry_iterator = el_client.text_to_speech.convert(**retry_kwargs)
                        audio_bytes = b"".join(retry_iterator)
                        if len(audio_bytes) == 0:
                            logger.error(f"ElevenLabs TTS chunk {i+1} still 0 bytes after retry, skipping")
                            continue

                    logger.info(f"ElevenLabs TTS chunk {i+1} collected {len(audio_bytes)} bytes")

                    if playback_cancel_event.is_set():
                        logger.info(f"ElevenLabs TTS chunk {i+1} cancelled before playback")
                        break

                    # Write to temp file and play with ffplay + timeout
                    # start_new_session=True isolates ffplay in its own process group
                    # so SDL2/CoreAudio signals don't propagate to parent
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp.write(audio_bytes)
                    tmp.close()

                    proc = None
                    try:
                        proc = subprocess.Popen(
                            ["ffplay", "-autoexit", "-nodisp", tmp.name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,  # Isolate: signals won't kill parent
                        )
                        _register_playback_process(proc, playback_cancel_event)
                        while proc.poll() is None:
                            if playback_cancel_event.is_set():
                                logger.info(f"ElevenLabs TTS chunk {i+1} cancelled — terminating ffplay")
                                _terminate_playback_process(proc)
                                break
                            try:
                                proc.wait(timeout=0.1)
                            except subprocess.TimeoutExpired:
                                pass
                        if playback_cancel_event.is_set():
                            break
                        chunks_played.append(i)
                    except subprocess.TimeoutExpired:
                        logger.error(f"ffplay timed out on chunk {i+1}")
                        if proc is not None:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                                proc.wait(timeout=2)
                            except Exception:
                                pass
                    finally:
                        if proc is not None:
                            _unregister_playback_process(proc)
                        os.unlink(tmp.name)

                except Exception as e:
                    logger.error(f"ElevenLabs TTS chunk {i+1} failed: {e}")
                    # Continue to next chunk instead of crashing

        # Run blocking TTS in a thread so the async event loop isn't frozen.
        # Media ducking is owned by the voice turn/session boundary.
        await asyncio.to_thread(_generate_and_play, merged)

        total_time = _time.perf_counter() - gen_start

        if playback_cancel_event.is_set():
            raise asyncio.CancelledError()

        _unregister_playback_event(playback_cancel_event)

        # If no chunks were successfully played, report failure
        if not chunks_played:
            raise Exception(f"All {len(merged)} TTS chunks failed — no audio played")

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
            "model": el_model,
            "endpoint": "api.elevenlabs.io/v1/text-to-speech",
        }
        logger.info(f"ElevenLabs TTS succeeded: {total_time:.2f}s")
        return True, metrics, config

    except asyncio.CancelledError:
        logger.warning("ElevenLabs TTS cancelled — stopping playback")
        stop_current_playback()
        raise

    except Exception as e:
        _unregister_playback_event(playback_cancel_event)
        logger.error(f"ElevenLabs TTS failed: {e}")
        error_config = {
            "error_type": "all_providers_failed",
            "attempted_endpoints": [{
                "endpoint": "api.elevenlabs.io/v1/text-to-speech",
                "provider": "elevenlabs",
                "voice": voice or ELEVENLABS_TTS_VOICE,
                "model": model or ELEVENLABS_TTS_MODEL,
                "error": str(e),
            }],
        }
        return False, None, error_config


async def elevenlabs_stt(
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
            model_id=model,
            language_code=STT_LANGUAGE if (STT_LANGUAGE and STT_LANGUAGE != "auto") else None,
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


# Backward compatibility aliases
simple_tts_failover = elevenlabs_tts
simple_stt_failover = elevenlabs_stt
