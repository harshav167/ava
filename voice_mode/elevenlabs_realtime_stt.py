"""
ElevenLabs Scribe v2 Realtime STT for VoiceMode.

Streams microphone audio to ElevenLabs via WebSocket and returns
committed transcripts. Uses local Silero VAD for silence detection
with manual commit mode — audio streams to ElevenLabs for transcription
while Silero runs locally for instant silence detection.
"""

import asyncio
import base64
import io
import logging
import time
import wave
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from elevenlabs.realtime.scribe import AudioFormat
from elevenlabs.realtime.connection import RealtimeEvents

from .silero_vad import StopPolicy, build_stop_policy, get_silero_vad, SILERO_CHUNK_SAMPLES

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
CACHE_DIR = Path.home() / ".voicemode" / "cache"
LAST_RECORDING_RAW = CACHE_DIR / "last_recording.raw"
LAST_RECORDING_WAV = CACHE_DIR / "last_recording.wav"


def _cached_audio_to_wav_buffer(cached_audio: np.ndarray):
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SCRIBE_SAMPLE_RATE)
        wf.writeframes(cached_audio.astype(np.int16, copy=False).tobytes())
    wav_buffer.seek(0)
    wav_buffer.name = "cached_recording.wav"
    return wav_buffer


def _write_cached_audio_files(audio_cache: list[np.ndarray]) -> tuple[Path, Path] | None:
    if not audio_cache:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_audio = np.concatenate(audio_cache).astype(np.int16, copy=False)
    all_audio.tofile(str(LAST_RECORDING_RAW))
    with wave.open(str(LAST_RECORDING_WAV), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SCRIBE_SAMPLE_RATE)
        wf.writeframes(all_audio.tobytes())
    logger.info(
        "Audio cached: %s samples (%.1fs) -> %s and %s",
        len(all_audio),
        len(all_audio) / SCRIBE_SAMPLE_RATE,
        LAST_RECORDING_RAW,
        LAST_RECORDING_WAV,
    )
    return LAST_RECORDING_RAW, LAST_RECORDING_WAV


def _read_cached_audio() -> np.ndarray | None:
    if LAST_RECORDING_RAW.exists():
        return np.fromfile(str(LAST_RECORDING_RAW), dtype=np.int16)
    if LAST_RECORDING_WAV.exists():
        with wave.open(str(LAST_RECORDING_WAV), "rb") as wf:
            return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).copy()
    return None


def _clear_cached_audio() -> None:
    LAST_RECORDING_RAW.unlink(missing_ok=True)
    LAST_RECORDING_WAV.unlink(missing_ok=True)


def _cached_audio_duration(cached_audio: np.ndarray | None) -> float:
    if cached_audio is None:
        return 0.0
    return len(cached_audio) / SCRIBE_SAMPLE_RATE


def _looks_truncated(text: str, cached_audio_seconds: float, finalized_by_local_vad: bool) -> bool:
    if not finalized_by_local_vad:
        return False
    normalized = text.strip()
    if not normalized:
        return True
    word_count = len(normalized.split())
    # A long recording with only a few committed words is suspicious; batch STT
    # sees the full cached WAV and can recover from premature local finalization.
    if cached_audio_seconds >= 8.0 and word_count < max(8, cached_audio_seconds * 0.8):
        return True
    if cached_audio_seconds >= 4.0 and not normalized.endswith((".", "?", "!")) and word_count < 8:
        return True
    return False


def _prefer_batch_recovery(committed_text: str, fallback_result: Optional[dict]) -> Optional[dict]:
    if not fallback_result:
        return None
    fallback_text = fallback_result.get("text", "").strip()
    if len(fallback_text.split()) <= len(committed_text.split()):
        return None
    fallback_result.setdefault("metrics", {})["replaced_realtime_partial"] = committed_text
    return fallback_result


def _combine_committed_transcripts(committed_text_history: list[str]) -> str:
    """Combine manual/periodic realtime commits without duplicating overlap."""
    combined = ""
    for text in committed_text_history:
        text = text.strip()
        if not text:
            continue
        if not combined:
            combined = text
            continue
        if text in combined:
            continue
        if combined in text:
            combined = text
            continue
        combined = f"{combined} {text}"
    return combined


async def _batch_transcribe_cached_audio(
    api_key: str,
    elapsed_total: float,
    reason: str,
    *,
    clear_cache_on_success: bool = False,
) -> Optional[dict]:
    cached_audio = _read_cached_audio()
    if cached_audio is None or len(cached_audio) == 0:
        return None

    try:
        logger.info("Realtime STT %s — attempting batch transcription from cached audio", reason)
        from .elevenlabs_client import elevenlabs_stt_batch

        batch_result = elevenlabs_stt_batch(
            audio_file=_cached_audio_to_wav_buffer(cached_audio),
            model_id="scribe_v2",
            language_code="en",
            api_key=api_key,
        )
        text = batch_result.get("text", "").strip()
        if not text:
            return None
        logger.info("Batch fallback succeeded: '%s'", text[:80])
        if clear_cache_on_success:
            _clear_cached_audio()
        return {
            "text": text,
            "provider": "elevenlabs",
            "endpoint": "scribe_v2_batch_fallback",
            "audio_file": str(LAST_RECORDING_WAV),
            "audio_format": "wav",
            "metrics": {
                "is_local": False,
                "request_time_ms": round(elapsed_total * 1000, 1),
                "vad_mode": "batch_fallback_from_cache",
                "fallback_reason": reason,
                "cached_audio_seconds": round(_cached_audio_duration(cached_audio), 1),
            },
        }
    except Exception as e:
        logger.error("Batch fallback from cache failed: %s", e)
        return None


async def realtime_transcribe(
    api_key: str,
    max_duration: float = 120.0,
    min_duration: float = 3.0,
    language_code: Optional[str] = None,
    on_partial: Optional[Callable[[str], None]] = None,
    vad_silence_threshold: float = 2.0,
    vad_aggressiveness: Optional[int] = None,
    disable_silence_detection: bool = False,
    previous_text: Optional[str] = None,
    stop_policy: Optional[StopPolicy] = None,
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
    committed_text_history: list[str] = []
    error_message = None
    recording = True
    force_finalize = False
    final_commit_requested = False
    stop_reason = "unknown"
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

    stop_policy = stop_policy or build_stop_policy(
        max_duration=max_duration,
        min_duration=min_duration,
        disable_silence_detection=disable_silence_detection,
        vad_aggressiveness=vad_aggressiveness,
    )
    max_duration = stop_policy.max_duration
    min_duration = stop_policy.min_duration
    disable_silence_detection = stop_policy.disable_silence_detection
    silence_secs = stop_policy.realtime_silence_threshold_secs
    vad_prob_threshold = stop_policy.vad_probability_threshold

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
            committed_text_history.append(committed_text)
            elapsed = time.perf_counter() - start_time
            logger.info(f"ElevenLabs STT committed ({elapsed:.1f}s): {committed_text[:80]}")
            if final_commit_requested and elapsed >= min_duration:
                recording = False

    def on_error_event(data):
        nonlocal error_message, recording, stop_reason
        # Don't overwrite a successful transcript with a close-related error
        if not committed_text:
            error_message = str(data)
            logger.error(f"ElevenLabs Realtime STT error: {data}")
        else:
            logger.debug(f"ElevenLabs Realtime STT post-commit error (ignored): {data}")
        stop_reason = "error"
        recording = False
        session_ready.set()  # Unblock any waiter

    def on_close_event():
        nonlocal recording, stop_reason
        logger.info("ElevenLabs Realtime STT: connection closed")
        if stop_reason == "unknown":
            stop_reason = "connection_closed"
        recording = False
        session_ready.set()  # Unblock any waiter

    def _mark_force_finalize():
        nonlocal force_finalize, stop_reason
        force_finalize = True
        stop_reason = "local_vad_silence"

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
            on_local_finalize=_mark_force_finalize,
        )
    )

    try:
        while recording:
            elapsed = time.perf_counter() - start_time
            if elapsed >= max_duration:
                logger.info("ElevenLabs Realtime STT: max duration reached")
                stop_reason = "max_duration"
                final_commit_requested = True
                # Send final commit before closing
                try:
                    await connection.commit()
                    await asyncio.sleep(0.5)  # Give server time to process
                except Exception:
                    pass
                break
            if force_finalize:
                logger.info("ElevenLabs Realtime STT: local VAD requested finalize")
                final_commit_requested = True
                try:
                    await connection.commit()
                    await asyncio.sleep(0.5)  # Give server time to process
                except Exception:
                    pass
                break
            if mic_task.done():
                if stop_reason == "unknown":
                    stop_reason = "mic_stream_ended"
                if not final_commit_requested:
                    final_commit_requested = True
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
        fallback_result = await _batch_transcribe_cached_audio(api_key, elapsed_total, "failed")
        if fallback_result:
            return fallback_result

        return {
            "error_type": "connection_failed",
            "provider": "elevenlabs",
            "error": error_message,
        }

    if committed_text:
        committed_text = _combine_committed_transcripts(committed_text_history)
        cached_audio = _read_cached_audio()
        cached_audio_seconds = _cached_audio_duration(cached_audio)
        if _looks_truncated(
            committed_text,
            cached_audio_seconds,
            stop_reason in {"local_vad_silence", "max_duration"},
        ):
            fallback_result = await _batch_transcribe_cached_audio(
                api_key, elapsed_total, "suspected_truncated_realtime_commit"
            )
            recovered = _prefer_batch_recovery(committed_text, fallback_result)
            if recovered:
                return recovered
        return {
            "text": committed_text,
            "provider": "elevenlabs",
            "endpoint": "scribe_v2_realtime",
            "audio_file": str(LAST_RECORDING_WAV) if LAST_RECORDING_WAV.exists() else None,
            "audio_format": "wav" if LAST_RECORDING_WAV.exists() else None,
            "metrics": {
                "is_local": False,
                "request_time_ms": round(elapsed_total * 1000, 1),
                "vad_mode": "local_silero",
                "stop_reason": stop_reason,
                "cached_audio_seconds": round(cached_audio_seconds, 1),
            },
        }
    else:
        fallback_result = await _batch_transcribe_cached_audio(api_key, elapsed_total, "no_committed_transcript")
        if fallback_result:
            return fallback_result
        return {
            "error_type": "no_speech",
            "provider": "elevenlabs",
            "audio_file": str(LAST_RECORDING_WAV) if LAST_RECORDING_WAV.exists() else None,
            "audio_format": "wav" if LAST_RECORDING_WAV.exists() else None,
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
    on_local_finalize: Optional[Callable[[], None]] = None,
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

    # Audio cache — save all PCM chunks so speech is NEVER lost
    # If ElevenLabs connection dies, we can batch-transcribe the cached audio
    audio_cache: list = []

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

                # Cache audio for crash resilience — if ElevenLabs dies, we can batch-transcribe
                audio_cache.append(data.copy())

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
                                if on_local_finalize:
                                    on_local_finalize()
                                else:
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

    # Save cached audio to disk for crash resilience
    if audio_cache:
        try:
            _write_cached_audio_files(audio_cache)
        except Exception as e:
            logger.error(f"Failed to cache audio: {e}")
