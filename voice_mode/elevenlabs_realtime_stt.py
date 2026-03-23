"""
ElevenLabs Scribe v2 Realtime STT for VoiceMode.

Streams microphone audio to ElevenLabs via WebSocket and returns
committed transcripts. Uses server-side VAD for automatic silence
detection, replacing VoiceMode's local VAD + record-then-transcribe.
"""

import asyncio
import base64
import logging
import time
from typing import Optional, Callable

import sounddevice as sd
from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy
from elevenlabs.realtime.connection import RealtimeEvents

logger = logging.getLogger("voicemode")

# Scribe v2 Realtime expects 16kHz PCM
SCRIBE_SAMPLE_RATE = 16000
CHUNK_DURATION_MS = 100  # 100ms audio chunks
CHUNK_SAMPLES = int(SCRIBE_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

# Timeout for session to start after WebSocket connects
SESSION_START_TIMEOUT = 10.0


async def realtime_transcribe(
    api_key: str,
    max_duration: float = 120.0,
    min_duration: float = 3.0,
    language_code: Optional[str] = None,
    on_partial: Optional[Callable[[str], None]] = None,
    vad_silence_threshold: float = 2.0,
) -> Optional[dict]:
    """
    Stream microphone audio to ElevenLabs Scribe v2 Realtime via WebSocket.

    Uses server-side VAD to auto-commit when silence is detected.
    """
    from elevenlabs.client import ElevenLabs

    # Fresh client every call — no connection reuse between calls
    client = ElevenLabs(api_key=api_key)
    committed_text = ""
    error_message = None
    recording = True
    session_ready = asyncio.Event()
    start_time = time.perf_counter()

    connect_options = {
        "model_id": "scribe_v2_realtime",
        "audio_format": AudioFormat.PCM_16000,
        "sample_rate": SCRIBE_SAMPLE_RATE,
        "commit_strategy": CommitStrategy.VAD,
        "vad_silence_threshold_secs": min(3.0, max(0.3, vad_silence_threshold)),
    }

    # Always set language — auto-detect often misidentifies accented English
    connect_options["language_code"] = language_code if (language_code and language_code != "auto") else "en"

    logger.info(f"ElevenLabs Realtime STT: connecting (max={max_duration}s, min={min_duration}s)")

    try:
        connection = await asyncio.wait_for(
            client.speech_to_text.realtime.connect(connect_options),
            timeout=SESSION_START_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("ElevenLabs Realtime STT: connection timed out")
        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": "WebSocket connection timed out",
        }
    except Exception as e:
        logger.error(f"ElevenLabs Realtime STT: connection failed: {e}")
        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": str(e),
        }

    # Event handlers
    def on_session_started(data):
        logger.info("ElevenLabs Realtime STT: session started")
        session_ready.set()

    def on_partial_transcript_event(data):
        text = data.get("text", "")
        if text and on_partial:
            on_partial(text)
        if text:
            logger.debug(f"ElevenLabs STT partial: {text[:60]}")

    def on_committed_transcript_event(data):
        nonlocal committed_text, recording
        text = data.get("text", "")
        if text:
            committed_text = text.strip()
            elapsed = time.perf_counter() - start_time
            logger.info(f"ElevenLabs STT committed ({elapsed:.1f}s): {committed_text[:80]}")
            if elapsed >= min_duration:
                recording = False

    def on_error_event(data):
        nonlocal error_message, recording
        # Don't overwrite a successful transcript with a close-related error
        if not committed_text:
            error_message = str(data)
            logger.error(f"ElevenLabs Realtime STT error: {data}")
        else:
            logger.debug(f"ElevenLabs Realtime STT post-commit error (ignored): {data}")
        recording = False
        session_ready.set()  # Unblock any waiter

    def on_close_event():
        nonlocal recording
        logger.info("ElevenLabs Realtime STT: connection closed")
        recording = False
        session_ready.set()  # Unblock any waiter

    # Register ALL event handlers BEFORE anything else
    connection.on(RealtimeEvents.SESSION_STARTED, on_session_started)
    connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial_transcript_event)
    connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed_transcript_event)
    connection.on(RealtimeEvents.ERROR, on_error_event)
    connection.on(RealtimeEvents.CLOSE, on_close_event)

    # Wait for session to actually start before streaming audio
    try:
        await asyncio.wait_for(session_ready.wait(), timeout=SESSION_START_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error("ElevenLabs Realtime STT: session_started event never received")
        try:
            await connection.close()
        except Exception:
            pass
        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": "Session start timed out — server connected but never sent session_started",
        }

    if error_message:
        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": error_message,
        }

    # NOW start mic streaming — session is confirmed ready
    mic_task = asyncio.create_task(_stream_microphone(connection, max_duration, start_time))

    try:
        while recording:
            elapsed = time.perf_counter() - start_time
            if elapsed >= max_duration:
                logger.info("ElevenLabs Realtime STT: max duration reached")
                break
            await asyncio.sleep(0.1)
    finally:
        recording = False
        mic_task.cancel()
        try:
            await mic_task
        except asyncio.CancelledError:
            pass
        try:
            await connection.close()
        except Exception:
            pass

    elapsed_total = time.perf_counter() - start_time

    if error_message:
        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": error_message,
        }

    if committed_text:
        return {
            "text": committed_text,
            "provider": "elevenlabs",
            "endpoint": "scribe_v2_realtime",
            "metrics": {
                "is_local": False,
                "request_time_ms": round(elapsed_total * 1000, 1),
            },
        }
    else:
        return {
            "error_type": "no_speech",
            "provider": "elevenlabs",
            "metrics": {
                "is_local": False,
                "request_time_ms": round(elapsed_total * 1000, 1),
            },
        }


async def _stream_microphone(connection, max_duration: float, start_time: float):
    """Stream microphone audio chunks to the ElevenLabs WebSocket."""
    loop = asyncio.get_event_loop()

    try:
        logger.info(f"ElevenLabs Realtime STT: mic capture at {SCRIBE_SAMPLE_RATE}Hz")

        stream = sd.InputStream(
            samplerate=SCRIBE_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
        )
        stream.start()

        try:
            while True:
                elapsed = time.perf_counter() - start_time
                if elapsed >= max_duration:
                    break

                # Read audio chunk in executor to avoid blocking
                try:
                    data, overflowed = await loop.run_in_executor(
                        None, stream.read, CHUNK_SAMPLES
                    )
                except Exception as e:
                    # PortAudio errors (PaErrorCode -9988 etc) when mic disconnects
                    logger.error(f"ElevenLabs STT: mic read failed: {e}")
                    break
                if overflowed:
                    logger.debug("ElevenLabs STT: audio buffer overflow")

                # Send base64-encoded PCM to WebSocket
                audio_b64 = base64.b64encode(data.tobytes()).decode("utf-8")
                try:
                    await connection.send({"audio_base_64": audio_b64})
                except Exception as e:
                    logger.error(f"ElevenLabs STT: failed to send audio chunk: {e}")
                    break
        finally:
            stream.stop()
            stream.close()

    except asyncio.CancelledError:
        logger.debug("ElevenLabs STT: mic streaming cancelled")
    except Exception as e:
        logger.error(f"ElevenLabs STT: mic streaming error: {e}")
