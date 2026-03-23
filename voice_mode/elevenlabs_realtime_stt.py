"""
ElevenLabs Scribe v2 Realtime STT for VoiceMode.

Streams microphone audio to ElevenLabs via WebSocket and returns
committed transcripts. Uses local Silero VAD for silence detection
with manual commit mode — audio streams to ElevenLabs for transcription
while Silero runs locally for instant silence detection.
"""

import asyncio
import base64
import logging
import time
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from elevenlabs.realtime.scribe import AudioFormat
from elevenlabs.realtime.connection import RealtimeEvents

from .silero_vad import get_silero_vad, get_threshold_for_aggressiveness, SILERO_CHUNK_SAMPLES

logger = logging.getLogger("voicemode")

# Scribe v2 Realtime expects 16kHz PCM
SCRIBE_SAMPLE_RATE = 16000
CHUNK_DURATION_MS = 100  # 100ms audio chunks
CHUNK_SAMPLES = int(SCRIBE_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

# Timeout for session to start after WebSocket connects
SESSION_START_TIMEOUT = 10.0

# Silence detection defaults (matching Osaurus behavior)
DEFAULT_SILENCE_THRESHOLD_SECS = 0.8  # Osaurus: 0.3-0.8s depending on sensitivity
DEFAULT_VAD_THRESHOLD = 0.5  # Osaurus medium: 0.75 (inverted — higher = less sensitive)


async def realtime_transcribe(
    api_key: str,
    max_duration: float = 120.0,
    min_duration: float = 3.0,
    language_code: Optional[str] = None,
    on_partial: Optional[Callable[[str], None]] = None,
    vad_silence_threshold: float = 2.0,
    vad_aggressiveness: int = 1,
    disable_silence_detection: bool = False,
    previous_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Stream microphone audio to ElevenLabs Scribe v2 Realtime via WebSocket.

    Uses MANUAL commit mode with local Silero VAD for silence detection.
    Audio streams to ElevenLabs for transcription. Silero runs locally
    to detect when the user stops speaking, then sends a manual commit.
    This gives local-speed silence detection (~50ms) with cloud transcription.
    """
    from elevenlabs.client import ElevenLabs

    # Fresh client every call — no connection reuse between calls
    client = ElevenLabs(api_key=api_key)
    committed_text = ""
    error_message = None
    recording = True
    session_ready = asyncio.Event()
    start_time = time.perf_counter()

    # Use MANUAL commit — we control when to commit via local Silero VAD
    # ElevenLabs docs: "Manual commit is the default strategy"
    connect_options = {
        "model_id": "scribe_v2_realtime",
        "audio_format": AudioFormat.PCM_16000,
        "sample_rate": SCRIBE_SAMPLE_RATE,
        # No commit_strategy = defaults to manual commit
    }

    # Always set language — auto-detect often misidentifies accented English
    connect_options["language_code"] = language_code if (language_code and language_code != "auto") else "en"

    # Calculate silence threshold based on aggressiveness
    # Map 0-3 to Osaurus-like thresholds
    if disable_silence_detection:
        silence_secs = max_duration  # Effectively disabled — record until max_duration
        vad_prob_threshold = 0.3  # Still track VAD but don't act on it
    else:
        # Aggressiveness 0=tolerant (longer silence ok), 3=strict (short silence triggers)
        # Increased from Osaurus values — ElevenLabs realtime needs more buffer
        silence_map = {0: 3.0, 1: 2.0, 2: 1.2, 3: 0.8}
        silence_secs = silence_map.get(vad_aggressiveness, 0.8)
        vad_prob_threshold = get_threshold_for_aggressiveness(vad_aggressiveness)

    logger.info(
        f"ElevenLabs Realtime STT: connecting (max={max_duration}s, min={min_duration}s, "
        f"silence={silence_secs}s, vad_threshold={vad_prob_threshold}, mode=manual_commit+silero)"
    )

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
        logger.info("ElevenLabs Realtime STT: session started (manual commit + local Silero VAD)")
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

    # NOW start mic streaming with local Silero VAD — session is confirmed ready
    mic_task = asyncio.create_task(
        _stream_microphone_with_local_vad(
            connection, max_duration, min_duration, start_time,
            silence_secs, vad_prob_threshold, disable_silence_detection,
            previous_text=previous_text,
        )
    )

    try:
        while recording:
            elapsed = time.perf_counter() - start_time
            if elapsed >= max_duration:
                logger.info("ElevenLabs Realtime STT: max duration reached")
                # Send final commit before closing
                try:
                    await connection.commit()
                    await asyncio.sleep(0.5)  # Give server time to process
                except Exception:
                    pass
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

    if error_message and not committed_text:
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
                "vad_mode": "local_silero",
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


async def _stream_microphone_with_local_vad(
    connection,
    max_duration: float,
    min_duration: float,
    start_time: float,
    silence_threshold_secs: float,
    vad_prob_threshold: float,
    disable_silence_detection: bool,
    previous_text: Optional[str] = None,
):
    """
    Stream microphone audio to ElevenLabs WebSocket while running
    local Silero VAD for silence detection.

    Audio is forked:
    - Full chunks go to ElevenLabs via WebSocket (for transcription)
    - Sub-chunks (512 samples) go through local Silero VAD (for silence detection)

    When Silero detects silence exceeding the threshold, sends a manual
    commit to ElevenLabs to finalize the transcript.
    """
    loop = asyncio.get_event_loop()

    # Load Silero VAD
    vad = get_silero_vad()
    if vad is None:
        logger.warning("Silero VAD not available — falling back to time-based commit")

    # VAD state tracking
    speech_detected_ever = False
    silence_start = None  # When silence began
    first_chunk = True  # Send previous_text with first chunk only
    last_commit_time = time.perf_counter()  # For periodic commits per ElevenLabs docs
    PERIODIC_COMMIT_SECS = 25.0  # ElevenLabs recommends committing every 20-30s

    try:
        logger.info(
            f"ElevenLabs Realtime STT: mic capture at {SCRIBE_SAMPLE_RATE}Hz "
            f"(local Silero VAD, silence_threshold={silence_threshold_secs}s, "
            f"vad_threshold={vad_prob_threshold})"
        )

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

                # Send base64-encoded PCM to ElevenLabs WebSocket (for transcription)
                audio_b64 = base64.b64encode(data.tobytes()).decode("utf-8")
                send_payload = {"audio_base_64": audio_b64}

                # Send previous_text context with the FIRST audio chunk only
                # ElevenLabs docs: "helps the model understand conversation context"
                if first_chunk and previous_text:
                    # Truncate to <50 chars per ElevenLabs recommendation
                    send_payload["previous_text"] = previous_text[:50]
                    first_chunk = False
                elif first_chunk:
                    first_chunk = False

                try:
                    await connection.send(send_payload)
                except Exception as e:
                    logger.error(f"ElevenLabs STT: failed to send audio chunk: {e}")
                    break

                # Periodic commit every 25s for long recordings (ElevenLabs recommends 20-30s)
                now_for_commit = time.perf_counter()
                if (now_for_commit - last_commit_time) >= PERIODIC_COMMIT_SECS:
                    logger.info(f"Periodic commit at {elapsed:.1f}s")
                    try:
                        await connection.commit()
                        last_commit_time = now_for_commit
                    except Exception as e:
                        logger.debug(f"Periodic commit failed (non-fatal): {e}")

                # Run local Silero VAD on sub-chunks (512 samples each)
                if vad is not None and not disable_silence_detection:
                    audio_flat = data.flatten()
                    is_speech = False

                    # Process in 512-sample sub-chunks as Silero requires
                    for offset in range(0, len(audio_flat), SILERO_CHUNK_SAMPLES):
                        sub_chunk = audio_flat[offset:offset + SILERO_CHUNK_SAMPLES]
                        if len(sub_chunk) < SILERO_CHUNK_SAMPLES:
                            # Pad short final chunk
                            sub_chunk = np.pad(sub_chunk, (0, SILERO_CHUNK_SAMPLES - len(sub_chunk)))

                        try:
                            prob = vad(sub_chunk, SCRIBE_SAMPLE_RATE)
                            if prob > vad_prob_threshold:
                                is_speech = True
                                break  # Any speech in this chunk = speech
                        except Exception:
                            pass  # VAD error — skip, don't crash

                    now = time.perf_counter()

                    if is_speech:
                        speech_detected_ever = True
                        silence_start = None
                        last_speech_time = now
                    else:
                        # Silence detected
                        if silence_start is None:
                            silence_start = now

                        silence_duration = now - (silence_start or now)

                        # Only commit after min_duration AND speech was detected AND silence exceeds threshold
                        if (
                            speech_detected_ever
                            and elapsed >= min_duration
                            and silence_duration >= silence_threshold_secs
                        ):
                            logger.info(
                                f"Silero VAD: silence for {silence_duration:.1f}s "
                                f"(threshold={silence_threshold_secs}s) — sending manual commit"
                            )
                            try:
                                await connection.commit()
                            except Exception as e:
                                logger.error(f"Manual commit failed: {e}")
                            # Wait briefly for ElevenLabs to process the commit
                            await asyncio.sleep(0.3)
                            break

        finally:
            stream.stop()
            stream.close()

    except asyncio.CancelledError:
        logger.debug("ElevenLabs STT: mic streaming cancelled")
    except Exception as e:
        logger.error(f"ElevenLabs STT: mic streaming error: {e}")
