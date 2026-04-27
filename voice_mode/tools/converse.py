"""Conversation tools for interactive voice interactions."""

# ruff: noqa: E402

import asyncio
import contextlib
import logging
import os
import time
import traceback
from typing import Optional, Literal, Tuple, Dict, Union
from pathlib import Path

import numpy as np
import sounddevice as sd
from pydub import AudioSegment

# Voice Activity Detection — prefer Silero (neural network, probability scores)
# with WebRTC VAD as fallback (binary signal processing)
SILERO_VAD_AVAILABLE = False
try:
    from voice_mode.silero_vad import (
        get_silero_vad,
        SILERO_SAMPLE_RATE,
        SILERO_CHUNK_SAMPLES,
    )

    # Don't load the model at import time — lazy load on first use
    SILERO_VAD_AVAILABLE = True
except ImportError:
    SILERO_VAD_AVAILABLE = False

try:
    import webrtcvad

    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    webrtcvad = None
    WEBRTC_VAD_AVAILABLE = False

VAD_AVAILABLE = SILERO_VAD_AVAILABLE or WEBRTC_VAD_AVAILABLE

from fastmcp import Context  # noqa: E402

from voice_mode.server import mcp  # noqa: E402
from voice_mode.conch import Conch  # noqa: E402
from voice_mode.conversation_logger import get_conversation_logger  # noqa: E402
from voice_mode.config import (  # noqa: E402
    audio_operation_lock,
    SAMPLE_RATE,
    CHANNELS,
    DEBUG,
    DEBUG_DIR,
    VAD_DEBUG,
    SAVE_AUDIO,
    AUDIO_DIR,
    AUDIO_FEEDBACK_ENABLED,
    save_transcription,
    SAVE_TRANSCRIPTIONS,
    DISABLE_SILENCE_DETECTION,
    VAD_AGGRESSIVENESS,
    SILENCE_THRESHOLD_MS,
    MIN_RECORDING_DURATION,
    SKIP_TTS,
    TTS_SPEED,
    VAD_CHUNK_DURATION_MS,
    INITIAL_SILENCE_GRACE_PERIOD,
    REPEAT_PHRASES,
    WAIT_PHRASES,
    METRICS_LEVEL,
    STT_AUDIO_FORMAT,
    STT_SAVE_FORMAT,
    MP3_BITRATE,
    CONCH_ENABLED,
    CONCH_TIMEOUT,
    CONCH_CHECK_INTERVAL,
)
import voice_mode.config  # noqa: E402
from voice_mode.provider_discovery import provider_registry  # noqa: E402
from voice_mode.silero_vad import StopPolicy, build_stop_policy  # noqa: E402
from voice_mode.core import (  # noqa: E402
    get_debug_filename,
    play_chime_start,
    play_chime_end,
)
from voice_mode.statistics_tracking import track_voice_interaction  # noqa: E402
from voice_mode.utils import (  # noqa: E402
    get_event_logger,
    log_tool_request_start,
    log_tool_request_end,
)
from voice_mode.pronounce import (
    get_manager as get_pronounce_manager,
    is_enabled as pronounce_enabled,
)  # noqa: E402
from voice_mode.elevenlabs_tts_stt import stop_current_playback  # noqa: E402
from voice_mode.runtime_context import get_runtime_context  # noqa: E402
from voice_mode.voice_provider import get_voice_provider  # noqa: E402
from voice_mode.converse_session import ConverseSession, ConverseRequest, ConversePorts  # noqa: E402

logger = logging.getLogger("voicemode")

# Log silence detection config at module load time
logger.info(f"Module loaded with DISABLE_SILENCE_DETECTION={DISABLE_SILENCE_DETECTION}")


# DJ Ducking Configuration
DJ_SOCKET_PATH = "/tmp/voicemode-mpv.sock"
DJ_VOLUME_DUCK_AMOUNT = int(
    os.environ.get("VOICEMODE_DJ_DUCK_AMOUNT", "20")
)  # Volume reduction during TTS


async def _ctx_info(ctx: Optional[Context], message: str) -> None:
    """Send an info-level log message to the MCP client, if Context is available.

    Silently ignores failures — the client may not support logging notifications.
    """
    if ctx is None:
        return
    try:
        await ctx.info(message)
    except Exception:
        pass


async def _ctx_progress(
    ctx: Optional[Context], progress: float, total: float, message: str | None = None
) -> None:
    """Report progress to the MCP client, if Context is available.

    Silently ignores failures — the client may not support progress notifications.
    """
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except Exception:
        pass


async def _watch_client_disconnect(ctx: Optional[Context]) -> None:
    """Block until the HTTP client disconnects, then stop active playback.

    FastMCP cancellation is not guaranteed to interrupt a blocking worker thread
    immediately. This watcher gives HTTP transports a direct path from client
    disconnect to ffplay termination.
    """
    if ctx is None:
        await asyncio.Future()
        return

    request = None
    with contextlib.suppress(Exception):
        request = ctx.request_context.request if ctx.request_context else None
    if request is None:
        with contextlib.suppress(Exception):
            from fastmcp.server.dependencies import get_http_request

            request = get_http_request()

    if request is None or not hasattr(request, "is_disconnected"):
        await asyncio.Future()
        return

    while True:
        if await request.is_disconnected():
            logger.warning("MCP client disconnected — stopping active playback")
            stop_current_playback()
            return
        await asyncio.sleep(0.1)


def _dj_command(cmd: str) -> Optional[str]:
    """Send a command to mpv-dj via IPC socket.

    Args:
        cmd: JSON command to send (e.g., '{ "command": ["get_property", "volume"] }')

    Returns:
        Response string from mpv, or None if DJ not running
    """
    import subprocess

    if not os.path.exists(DJ_SOCKET_PATH):
        return None

    try:
        result = subprocess.run(
            ["socat", "-", DJ_SOCKET_PATH],
            input=cmd + "\n",
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_dj_volume() -> Optional[float]:
    """Get current DJ volume level.

    Returns:
        Current volume (0-100) or None if DJ not running
    """
    import json

    response = _dj_command('{ "command": ["get_property", "volume"] }')
    if response:
        try:
            data = json.loads(response)
            if "data" in data:
                return float(data["data"])
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return None


def set_dj_volume(volume: float) -> bool:
    """Set DJ volume level.

    Args:
        volume: Volume level (0-100)

    Returns:
        True if successful, False otherwise
    """
    import json

    volume = max(0, min(100, volume))  # Clamp to valid range
    response = _dj_command(f'{{ "command": ["set_property", "volume", {volume}] }}')
    if response:
        try:
            data = json.loads(response)
            return data.get("error") == "success"
        except json.JSONDecodeError:
            pass
    return False


# DJDucker is now in voice_mode.audio_ducker (media-key based pause/resume).
from voice_mode.audio_ducker import DJDucker  # noqa: E402


def should_repeat(text: str) -> bool:
    """
    Check if the transcribed text ends with a repeat phrase.

    Args:
        text: The transcribed text to check

    Returns:
        True if text ends with a repeat phrase, False otherwise
    """
    if not text:
        return False

    # Normalize text for comparison (lowercase, strip whitespace and punctuation)
    import string

    normalized_text = text.lower().strip().rstrip(string.punctuation).strip()

    # Check if any repeat phrase appears at the end
    for phrase in REPEAT_PHRASES:
        if normalized_text.endswith(phrase.lower().strip()):
            logger.info(f"Repeat phrase detected: '{phrase}' in '{text}'")
            return True

    return False


def should_wait(text: str) -> bool:
    """
    Check if the transcribed text ends with a wait phrase.

    Args:
        text: The transcribed text to check

    Returns:
        True if text ends with a wait phrase, False otherwise
    """
    if not text:
        return False

    # Normalize text for comparison (lowercase, strip whitespace and punctuation)
    import string

    normalized_text = text.lower().strip().rstrip(string.punctuation).strip()

    # Check if any wait phrase appears at the end
    for phrase in WAIT_PHRASES:
        if normalized_text.endswith(phrase.lower().strip()):
            logger.info(f"Wait phrase detected: '{phrase}' in '{text}'")
            return True

    return False


# Track last session end time for measuring AI thinking time
last_session_end_time = None


async def startup_initialization():
    """Initialize services on startup based on configuration."""
    runtime = get_runtime_context()
    if runtime.state().startup_initialized:
        return

    logger.info("Running startup initialization...")
    logger.info("Initializing provider registry...")
    await provider_registry.initialize()
    runtime.state().startup_initialized = True
    logger.info("Service initialization complete")


async def text_to_speech_with_failover(
    message: str,
    voice: Optional[str] = None,
    model: Optional[str] = None,
    instructions: Optional[str] = None,
    audio_format: Optional[str] = None,
    initial_provider: Optional[str] = None,
    speed: Optional[float] = None,
) -> Tuple[bool, Optional[dict], Optional[dict]]:
    """
    Text to speech with automatic failover to next available endpoint.

    Returns:
        Tuple of (success, tts_metrics, tts_config)
    """
    # Apply pronunciation rules if enabled
    if pronounce_enabled():
        pronounce_mgr = get_pronounce_manager()
        message = pronounce_mgr.process_tts(message)

    runtime = get_runtime_context()
    settings = runtime.settings()
    provider = get_voice_provider()
    return await provider.tts(
        text=message,
        voice=voice or settings.tts_voices[0],
        model=model or settings.tts_models[0],
        instructions=instructions,
        audio_format=audio_format,
        debug=DEBUG,
        debug_dir=DEBUG_DIR if DEBUG else None,
        save_audio=SAVE_AUDIO,
        audio_dir=AUDIO_DIR if SAVE_AUDIO else None,
        speed=speed,
    )


def prepare_audio_for_stt(audio_data: np.ndarray, output_format: str = "mp3") -> bytes:
    """
    Prepare audio data for STT upload with optional compression.

    Converts raw audio to the specified format, optionally compressing and
    downsampling to 16kHz (Whisper's native rate) for optimal bandwidth.

    Args:
        audio_data: Raw audio data as numpy array (16-bit PCM)
        output_format: Target format ('mp3', 'wav', 'flac', etc.)

    Returns:
        Compressed audio data as bytes
    """
    import io

    # Create AudioSegment from raw data
    # Audio is recorded at SAMPLE_RATE (24kHz), 16-bit mono
    audio = AudioSegment(
        audio_data.tobytes(),
        frame_rate=SAMPLE_RATE,
        sample_width=2,  # 16-bit = 2 bytes
        channels=CHANNELS,
    )

    # Calculate original size for logging
    original_size = len(audio_data) * 2  # 16-bit = 2 bytes per sample

    # Downsample to 16kHz (Whisper's native rate) for better compression
    # This also reduces size by ~33% even before compression
    whisper_sample_rate = 16000
    if SAMPLE_RATE != whisper_sample_rate:
        audio = audio.set_frame_rate(whisper_sample_rate)

    # Export to target format
    buffer = io.BytesIO()

    if output_format == "mp3":
        # Use configured bitrate for MP3 (default 32k for speech)
        audio.export(buffer, format="mp3", bitrate=MP3_BITRATE)
    elif output_format == "wav":
        # WAV is uncompressed but we still benefit from downsampling
        audio.export(buffer, format="wav")
    elif output_format == "flac":
        # FLAC is lossless compression
        audio.export(buffer, format="flac")
    else:
        # Default to MP3 for unknown formats
        logger.warning(f"Unknown STT format '{output_format}', falling back to MP3")
        audio.export(buffer, format="mp3", bitrate=MP3_BITRATE)

    compressed_data = buffer.getvalue()
    compressed_size = len(compressed_data)

    # Log compression ratio
    compression_ratio = original_size / compressed_size if compressed_size > 0 else 0
    logger.info(
        f"STT audio prepared: {original_size / 1024:.1f}KB -> {compressed_size / 1024:.1f}KB "
        f"({output_format}, {compression_ratio:.1f}x compression)"
    )

    return compressed_data


async def speech_to_text(
    audio_data: np.ndarray,
    save_audio: bool = False,
    audio_dir: Optional[Path] = None,
    transport: str = "local",
) -> Optional[Dict]:
    """
    Convert audio to text with automatic failover.

    Handles audio file preparation (saving permanently or using temp file) and
    delegates to elevenlabs_stt for the actual transcription attempts.

    For remote endpoints: Audio is compressed (MP3 at 32kbps) and downsampled
    to 16kHz to reduce bandwidth usage when uploading.

    For local endpoints: Audio is sent as WAV to skip compression overhead,
    since network bandwidth isn't a bottleneck for localhost/LAN connections.

    Original full-quality WAV is saved separately when save_audio is enabled.

    Args:
        audio_data: Raw audio data as numpy array
        save_audio: Whether to save the audio file permanently
        audio_dir: Directory to save audio files (if save_audio is True)
        transport: Transport method (for logging context)

    Returns:
        Dict with transcription result or error information:
        - Success: {"text": "...", "provider": "...", "endpoint": "..."}
        - No speech: {"error_type": "no_speech", "provider": "..."}
        - All failed: {"error_type": "connection_failed", "attempted_endpoints": [...]}
    """
    from voice_mode.artifacts import AudioArtifactLifecycle
    from voice_mode.conversation_logger import get_conversation_logger
    from voice_mode.elevenlabs_tts_stt import elevenlabs_stt
    from voice_mode.config import STT_BASE_URLS, STT_COMPRESS
    from voice_mode.provider_discovery import is_local_provider

    # Determine compression based on STT_COMPRESS mode
    # Options: auto (default), always, never
    primary_endpoint = (
        STT_BASE_URLS[0] if STT_BASE_URLS else "https://api.openai.com/v1"
    )
    is_local = is_local_provider(primary_endpoint)

    if STT_COMPRESS == "never":
        # Never compress - always use WAV
        stt_format = "wav"
        logger.info("STT: Compression disabled (mode=never), using WAV")
    elif STT_COMPRESS == "always":
        # Always compress regardless of endpoint type
        stt_format = STT_AUDIO_FORMAT if STT_AUDIO_FORMAT != "pcm" else "mp3"
        logger.info(f"STT: Compression forced (mode=always), using {stt_format}")
    else:
        # Auto mode (default): compress for remote, skip for local
        if is_local:
            # Local endpoint: use WAV to skip compression overhead (~200-800ms saved)
            stt_format = "wav"
            logger.info(
                f"STT: Local endpoint detected ({primary_endpoint}), skipping compression"
            )
        else:
            # Remote endpoint: compress to reduce bandwidth (~90% smaller)
            stt_format = STT_AUDIO_FORMAT if STT_AUDIO_FORMAT != "pcm" else "mp3"
            logger.info(
                f"STT: Remote endpoint ({primary_endpoint}), using {stt_format} compression"
            )

    # Prepare audio for upload (compressed for remote, WAV for local)
    compressed_audio = prepare_audio_for_stt(audio_data, stt_format)

    conversation_id = None
    if save_audio and audio_dir:
        conversation_id = get_conversation_logger().conversation_id

    lifecycle = AudioArtifactLifecycle()
    with lifecycle.stage_stt_upload(
        compressed_audio,
        upload_format=stt_format,
        audio_data=audio_data,
        save_audio=save_audio,
        audio_dir=audio_dir,
        save_format=STT_SAVE_FORMAT,
        conversation_id=conversation_id,
        encode_archive=prepare_audio_for_stt,
    ) as upload:
        with upload.open() as audio_file:
            result = await elevenlabs_stt(audio_file=audio_file, model="scribe_v2")

    if isinstance(result, dict) and upload.metadata.archive_path:
        result.setdefault("audio_file", upload.metadata.audio_file)
        result.setdefault("audio_path", str(upload.metadata.archive_path))
        result.setdefault("audio_format", upload.metadata.archive_format)

    return result


async def play_audio_feedback(
    text: str,
    openai_clients: dict = None,
    enabled: Optional[bool] = None,
    style: str = "chime",
    feedback_type: Optional[str] = None,
    voice: str = "default",
    model: str = "default",
    chime_leading_silence: Optional[float] = None,
    chime_trailing_silence: Optional[float] = None,
) -> None:
    """Play an audio feedback chime

    Args:
        text: Which chime to play (either "listening" or "finished")
        openai_clients: Deprecated, ignored
        enabled: Override global audio feedback setting
        style: Deprecated, ignored
        feedback_type: Deprecated, ignored
        voice: Deprecated, ignored
        model: Deprecated, ignored
        chime_leading_silence: Optional override for pre-chime silence duration
        chime_trailing_silence: Optional override for post-chime silence duration
    """
    # Use parameter override if provided, otherwise use global setting
    if enabled is False:
        return

    # If enabled is None, use global setting
    if enabled is None:
        enabled = AUDIO_FEEDBACK_ENABLED

    # Skip if disabled
    if not enabled:
        return

    try:
        # Play appropriate chime with optional delay overrides
        if text == "listening":
            await play_chime_start(
                leading_silence=chime_leading_silence,
                trailing_silence=chime_trailing_silence,
            )
        elif text == "finished":
            await play_chime_end(
                leading_silence=chime_leading_silence,
                trailing_silence=chime_trailing_silence,
            )
    except Exception as e:
        logger.debug(f"Audio feedback failed: {e}")
        # Don't interrupt the main flow if feedback fails


def record_audio(duration: float) -> np.ndarray:
    """Record audio from microphone"""
    logger.info(f"🎤 Recording audio for {duration}s...")
    if DEBUG:
        try:
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            logger.debug(
                f"Default input device: {default_input} - {devices[default_input]['name'] if default_input is not None else 'None'}"
            )
            logger.debug(
                f"Recording config - Sample rate: {SAMPLE_RATE}Hz, Channels: {CHANNELS}, dtype: int16"
            )
        except Exception as dev_e:
            logger.error(f"Error querying audio devices: {dev_e}")

    # Save current stdio state
    import sys

    original_stdin = sys.stdin
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        samples_to_record = int(duration * SAMPLE_RATE)
        logger.debug(f"Recording {samples_to_record} samples...")

        recording = sd.rec(
            samples_to_record, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.int16
        )
        sd.wait()

        flattened = recording.flatten()
        logger.info(f"✓ Recorded {len(flattened)} samples")

        if DEBUG:
            logger.debug(
                f"Recording stats - Min: {flattened.min()}, Max: {flattened.max()}, Mean: {flattened.mean():.2f}"
            )
            # Check if recording contains actual audio (not silence)
            rms = np.sqrt(np.mean(flattened.astype(float) ** 2))
            logger.debug(
                f"RMS level: {rms:.2f} ({'likely silence' if rms < 100 else 'audio detected'})"
            )

        return flattened

    except Exception as e:
        logger.error(f"Recording failed: {e}")
        logger.error(
            f"Audio config when error occurred - Sample rate: {SAMPLE_RATE}, Channels: {CHANNELS}"
        )

        # Check if this is a device error that might be recoverable
        error_str = str(e).lower()
        if any(
            err in error_str
            for err in [
                "device unavailable",
                "device disconnected",
                "invalid device",
                "unanticipated host error",
                "portaudio error",
            ]
        ):
            logger.info(
                "Audio device error detected - attempting to reinitialize audio system"
            )

            # Try to reinitialize sounddevice
            try:
                # Get current default device info before reinit
                try:
                    old_device = sd.query_devices(kind="input")
                    old_device_name = old_device.get("name", "Unknown")
                except Exception:
                    old_device_name = "Previous device"

                sd._terminate()
                sd._initialize()

                # Get new default device info
                try:
                    new_device = sd.query_devices(kind="input")
                    new_device_name = new_device.get("name", "Unknown")
                    logger.info(
                        f"Audio system reinitialized - switched from '{old_device_name}' to '{new_device_name}'"
                    )
                except Exception:
                    logger.info(
                        "Audio system reinitialized - retrying with new default device"
                    )

                # Wait a moment for the system to stabilize
                import time as time_module

                time_module.sleep(0.5)

                # Try recording again with the new device (recursive call)
                logger.info("Retrying recording with new audio device...")
                return record_audio(duration)

            except Exception as reinit_error:
                logger.error(f"Failed to reinitialize audio: {reinit_error}")
                # Fall through to normal error handling

        # Import here to avoid circular imports
        from voice_mode.utils.audio_diagnostics import get_audio_error_help

        # Get helpful error message
        help_message = get_audio_error_help(e)
        logger.error(f"\n{help_message}")

        # Try to get more info about audio devices
        try:
            devices = sd.query_devices()
            logger.error("Available input devices:")
            for i, device in enumerate(devices):
                if device["max_input_channels"] > 0:
                    logger.error(
                        f"  {i}: {device['name']} (inputs: {device['max_input_channels']})"
                    )
        except Exception as dev_e:
            logger.error(f"Cannot query audio devices: {dev_e}")

        return np.array([])
    finally:
        # Restore stdio if it was changed
        if sys.stdin != original_stdin:
            sys.stdin = original_stdin
        if sys.stdout != original_stdout:
            sys.stdout = original_stdout
        if sys.stderr != original_stderr:
            sys.stderr = original_stderr


def record_audio_with_silence_detection(
    max_duration: float,
    disable_silence_detection: bool = False,
    min_duration: float = 0.0,
    vad_aggressiveness: Optional[int] = None,
    *,
    stop_policy: Optional[StopPolicy] = None,
) -> Tuple[np.ndarray, bool]:
    """Record audio from microphone with automatic silence detection.

    Uses Silero VAD (neural network, probability-based) to detect when the user
    stops speaking and automatically stops recording after a configurable silence
    threshold. Falls back to WebRTC VAD if Silero is unavailable.

    Args:
        max_duration: Maximum recording duration in seconds
        disable_silence_detection: If True, disables silence detection and uses fixed duration recording
        min_duration: Minimum recording duration before silence detection can stop (default: 0.0)
        vad_aggressiveness: VAD aggressiveness level (0-3). If None, uses VAD_AGGRESSIVENESS from config.
            Maps to Silero probability thresholds: 0=0.3, 1=0.5, 2=0.7, 3=0.85
        stop_policy: Optional precomputed policy shared with the caller's listening boundary.

    Returns:
        Tuple of (audio_data, speech_detected):
            - audio_data: Numpy array of recorded audio samples
            - speech_detected: Boolean indicating if speech was detected during recording
    """

    if stop_policy is None:
        stop_policy = build_stop_policy(
            max_duration=max_duration,
            min_duration=min_duration,
            disable_silence_detection=disable_silence_detection,
            vad_aggressiveness=vad_aggressiveness,
            local_silence_threshold_ms=SILENCE_THRESHOLD_MS,
        )
    else:
        max_duration = stop_policy.max_duration
        min_duration = stop_policy.min_duration
        disable_silence_detection = stop_policy.disable_silence_detection
        vad_aggressiveness = stop_policy.vad_aggressiveness
    logger.info(
        f"record_audio_with_silence_detection called - VAD_AVAILABLE={VAD_AVAILABLE}, DISABLE_SILENCE_DETECTION={DISABLE_SILENCE_DETECTION}, min_duration={stop_policy.min_duration}"
    )

    if not VAD_AVAILABLE:
        logger.warning(
            "No VAD available (neither Silero nor WebRTC), falling back to fixed duration recording"
        )
        # For fallback, assume speech is present since we can't detect
        return (record_audio(max_duration), True)

    if DISABLE_SILENCE_DETECTION or stop_policy.disable_silence_detection:
        if disable_silence_detection:
            logger.info("Silence detection disabled for this interaction by request")
        else:
            logger.info(
                "Silence detection disabled globally via VOICEMODE_DISABLE_SILENCE_DETECTION"
            )
        # For fallback, assume speech is present since we can't detect
        return (record_audio(max_duration), True)

    logger.info(f"🎤 Recording with silence detection (max {max_duration}s)...")

    try:
        # Initialize VAD — prefer Silero, fallback to WebRTC
        effective_vad_aggressiveness = (
            stop_policy.vad_aggressiveness
        )
        use_silero = False
        silero_vad_instance = None
        silero_threshold = 0.5

        if SILERO_VAD_AVAILABLE:
            silero_vad_instance = get_silero_vad()
            if silero_vad_instance is not None:
                use_silero = True
                silero_threshold = stop_policy.local_vad_probability_threshold
                silero_vad_instance.reset_states()
                logger.info(
                    f"Using Silero VAD (threshold={silero_threshold}, aggressiveness={effective_vad_aggressiveness})"
                )

        if not use_silero and WEBRTC_VAD_AVAILABLE:
            vad = webrtcvad.Vad(effective_vad_aggressiveness)
            logger.info(
                f"Using WebRTC VAD fallback (aggressiveness={effective_vad_aggressiveness})"
            )
        elif not use_silero:
            logger.warning(
                "No VAD backend available, falling back to fixed duration recording"
            )
            return (record_audio(max_duration), True)

        if use_silero:
            # Silero VAD: 512 samples at 16kHz = 32ms per chunk
            vad_sample_rate = SILERO_SAMPLE_RATE
            vad_chunk_samples = SILERO_CHUNK_SAMPLES
            # Calculate recording chunk size at native sample rate to match 32ms
            chunk_duration_s = vad_chunk_samples / vad_sample_rate  # 0.032s
            chunk_samples = int(SAMPLE_RATE * chunk_duration_s)
        else:
            # WebRTC VAD: 10/20/30ms chunks, requires 8/16/32kHz
            chunk_samples = int(SAMPLE_RATE * VAD_CHUNK_DURATION_MS / 1000)
            chunk_duration_s = VAD_CHUNK_DURATION_MS / 1000
            vad_sample_rate = 16000
            vad_chunk_samples = int(vad_sample_rate * VAD_CHUNK_DURATION_MS / 1000)

        # Recording state
        chunks = []
        silence_duration_ms = 0
        recording_duration = 0
        speech_detected = False
        stop_recording = False

        # Use a queue for thread-safe communication
        import queue

        audio_queue = queue.Queue()

        # Save stdio state
        import sys

        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        vad_backend = "Silero" if use_silero else "WebRTC"
        chunk_duration_ms = chunk_duration_s * 1000
        effective_min_duration = stop_policy.min_duration
        logger.debug(
            f"VAD config - Backend: {vad_backend}, Aggressiveness: {effective_vad_aggressiveness} (param: {vad_aggressiveness}, default: {VAD_AGGRESSIVENESS}), "
            f"Silence threshold: {stop_policy.local_silence_threshold_ms}ms, "
            f"Min duration: {effective_min_duration}s, "
            f"Initial grace period: {INITIAL_SILENCE_GRACE_PERIOD}s"
        )

        if VAD_DEBUG:
            logger.info("[VAD_DEBUG] Starting VAD recording with config:")
            logger.info(f"[VAD_DEBUG]   Backend: {vad_backend}")
            if use_silero:
                logger.info(
                    f"[VAD_DEBUG]   Silero threshold: {silero_threshold} (aggressiveness={effective_vad_aggressiveness})"
                )
            logger.info(f"[VAD_DEBUG]   max_duration: {max_duration}s")
            logger.info(f"[VAD_DEBUG]   min_duration: {stop_policy.min_duration}s")
            logger.info(
                f"[VAD_DEBUG]   effective_min_duration: {effective_min_duration}s"
            )
            logger.info(
                f"[VAD_DEBUG]   VAD aggressiveness: {effective_vad_aggressiveness}"
            )
            logger.info(f"[VAD_DEBUG]   Silence threshold: {stop_policy.local_silence_threshold_ms}ms")
            logger.info(
                f"[VAD_DEBUG]   Sample rate: {SAMPLE_RATE}Hz (VAD using {vad_sample_rate}Hz)"
            )
            logger.info(f"[VAD_DEBUG]   Chunk duration: {chunk_duration_ms:.0f}ms")

        def audio_callback(indata, frames, time, status):
            """Callback for continuous audio stream"""
            if status:
                logger.warning(f"Audio stream status: {status}")
                # Check for device-related errors
                status_str = str(status).lower()
                if any(
                    err in status_str
                    for err in [
                        "device unavailable",
                        "device disconnected",
                        "invalid device",
                        "unanticipated host error",
                        "stream is stopped",
                        "portaudio error",
                    ]
                ):
                    # Signal that we should stop recording due to device error
                    audio_queue.put(None)  # Sentinel value to indicate error
                    return
            # Put the audio data in the queue for processing
            audio_queue.put(indata.copy())

        try:
            # Create continuous input stream
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=np.int16,
                callback=audio_callback,
                blocksize=chunk_samples,
            ):
                logger.debug("Started continuous audio stream")

                while recording_duration < max_duration and not stop_recording:
                    try:
                        # Get audio chunk from queue with timeout
                        chunk = audio_queue.get(timeout=0.1)

                        # Check for error sentinel
                        if chunk is None:
                            logger.error(
                                "Audio device error detected - stopping recording"
                            )
                            # Raise an exception to trigger recovery logic
                            raise sd.PortAudioError(
                                "Audio device disconnected or unavailable"
                            )

                        # Flatten for consistency
                        chunk_flat = chunk.flatten()
                        chunks.append(chunk_flat)

                        # Downsample from native rate (e.g. 24kHz) to VAD rate (16kHz)
                        from scipy import signal as sp_signal

                        resampled_length = int(
                            len(chunk_flat) * vad_sample_rate / SAMPLE_RATE
                        )
                        vad_chunk = sp_signal.resample(chunk_flat, resampled_length)
                        # Take exactly the number of samples VAD expects
                        vad_chunk = vad_chunk[:vad_chunk_samples]

                        # Check if chunk contains speech
                        try:
                            if use_silero:
                                # Silero VAD returns probability 0.0-1.0
                                speech_prob = silero_vad_instance(
                                    vad_chunk.astype(np.int16), vad_sample_rate
                                )
                                is_speech = speech_prob >= silero_threshold
                                if VAD_DEBUG:
                                    if (
                                        int(recording_duration * 1000) % 500
                                        < chunk_duration_ms
                                    ):
                                        rms = np.sqrt(np.mean(chunk.astype(float) ** 2))
                                        logger.info(
                                            f"[VAD_DEBUG] t={recording_duration:.1f}s: "
                                            f"prob={speech_prob:.3f} (threshold={silero_threshold}), "
                                            f"speech={is_speech}, RMS={rms:.0f}, "
                                            f"state={'WAITING' if not speech_detected else 'ACTIVE'}"
                                        )
                            else:
                                # WebRTC VAD returns boolean
                                vad_chunk_int16 = vad_chunk.astype(np.int16)
                                chunk_bytes = vad_chunk_int16.tobytes()
                                is_speech = vad.is_speech(chunk_bytes, vad_sample_rate)
                                if VAD_DEBUG:
                                    if (
                                        int(recording_duration * 1000) % 500
                                        < chunk_duration_ms
                                    ):
                                        rms = np.sqrt(np.mean(chunk.astype(float) ** 2))
                                        logger.info(
                                            f"[VAD_DEBUG] t={recording_duration:.1f}s: "
                                            f"speech={is_speech}, RMS={rms:.0f}, "
                                            f"state={'WAITING' if not speech_detected else 'ACTIVE'}"
                                        )
                        except Exception as vad_e:
                            logger.warning(f"VAD error: {vad_e}, treating as speech")
                            is_speech = True

                        # State machine for speech detection
                        if not speech_detected:
                            # WAITING_FOR_SPEECH state
                            if is_speech:
                                logger.info(
                                    "🎤 Speech detected, starting active recording"
                                )
                                if VAD_DEBUG:
                                    logger.info(
                                        f"[VAD_DEBUG] STATE CHANGE: WAITING_FOR_SPEECH -> SPEECH_ACTIVE at t={recording_duration:.1f}s"
                                    )
                                speech_detected = True
                                silence_duration_ms = 0
                            # No timeout in this state - just keep waiting
                            # The only exit is speech detection or max_duration
                        else:
                            # We have detected speech at some point
                            if is_speech:
                                # SPEECH_ACTIVE state - reset silence counter
                                silence_duration_ms = 0
                            else:
                                # SILENCE_AFTER_SPEECH state - accumulate silence
                                silence_duration_ms += chunk_duration_ms
                                if (
                                    VAD_DEBUG
                                    and silence_duration_ms % 100 < chunk_duration_ms
                                ):
                                    logger.info(
                                        f"[VAD_DEBUG] Accumulating silence: {silence_duration_ms:.0f}/{stop_policy.local_silence_threshold_ms}ms, t={recording_duration:.1f}s"
                                    )
                                elif silence_duration_ms % 200 < chunk_duration_ms:
                                    logger.debug(
                                        f"Silence: {silence_duration_ms:.0f}ms"
                                    )

                                # Check if we should stop due to the session stop policy.
                                if (
                                    recording_duration >= effective_min_duration
                                    and silence_duration_ms >= stop_policy.local_silence_threshold_ms
                                ):
                                    logger.info(
                                        f"✓ Silence threshold reached after {recording_duration:.1f}s of recording"
                                    )
                                    if VAD_DEBUG:
                                        logger.info(
                                            f"[VAD_DEBUG] STOP: silence_duration={silence_duration_ms}ms >= threshold={stop_policy.local_silence_threshold_ms}ms"
                                        )
                                        logger.info(
                                            f"[VAD_DEBUG] STOP: recording_duration={recording_duration:.1f}s >= min_duration={effective_min_duration}s"
                                        )
                                    stop_recording = True
                                elif (
                                    VAD_DEBUG
                                    and recording_duration < effective_min_duration
                                ):
                                    if (
                                        int(recording_duration * 1000) % 500
                                        < chunk_duration_ms
                                    ):  # Log every ~500ms
                                        logger.info(
                                            f"[VAD_DEBUG] Min duration not met: {recording_duration:.1f}s < {effective_min_duration}s"
                                        )

                        recording_duration += chunk_duration_s

                    except queue.Empty:
                        # No audio data available, continue waiting
                        continue
                    except Exception as e:
                        logger.error(f"Error processing audio chunk: {e}")
                        break

            # Concatenate all chunks
            if chunks:
                full_recording = np.concatenate(chunks)

                if not speech_detected:
                    logger.info(
                        f"✓ Recording completed ({recording_duration:.1f}s) - No speech detected"
                    )
                    if VAD_DEBUG:
                        logger.info(
                            "[VAD_DEBUG] FINAL STATE: No speech was ever detected during recording"
                        )
                else:
                    logger.info(
                        f"✓ Recorded {len(full_recording)} samples ({recording_duration:.1f}s) with speech"
                    )
                    if VAD_DEBUG:
                        logger.info(
                            "[VAD_DEBUG] FINAL STATE: Speech was detected, recording complete"
                        )

                if DEBUG:
                    # Calculate RMS for debug
                    rms = np.sqrt(np.mean(full_recording.astype(float) ** 2))
                    logger.debug(
                        f"Recording stats - RMS: {rms:.2f}, Speech detected: {speech_detected}"
                    )

                # Return tuple: (audio_data, speech_detected)
                return (full_recording, speech_detected)
            else:
                logger.warning("No audio chunks recorded")
                return (np.array([]), False)

        except Exception as e:
            logger.error(f"Recording with VAD failed: {e}")

            # Import here to avoid circular imports
            from voice_mode.utils.audio_diagnostics import get_audio_error_help

            # Check if this is a device error that might be recoverable
            error_str = str(e).lower()
            if any(
                err in error_str
                for err in [
                    "device unavailable",
                    "device disconnected",
                    "invalid device",
                    "unanticipated host error",
                    "portaudio error",
                ]
            ):
                logger.info(
                    "Audio device error detected - attempting to reinitialize audio system"
                )

                # Try to reinitialize sounddevice
                try:
                    # Get current default device info before reinit
                    try:
                        old_device = sd.query_devices(kind="input")
                        old_device_name = old_device.get("name", "Unknown")
                    except Exception:
                        old_device_name = "Previous device"

                    sd._terminate()
                    sd._initialize()

                    # Get new default device info
                    try:
                        new_device = sd.query_devices(kind="input")
                        new_device_name = new_device.get("name", "Unknown")
                        logger.info(
                            f"Audio system reinitialized - switched from '{old_device_name}' to '{new_device_name}'"
                        )
                    except Exception:
                        logger.info(
                            "Audio system reinitialized - retrying with new default device"
                        )

                    # Wait a moment for the system to stabilize
                    import time as time_module

                    time_module.sleep(0.5)

                    # Try recording again with the new device (recursive call in sync context)
                    logger.info("Retrying recording with new audio device...")
                    return record_audio_with_silence_detection(
                        max_duration,
                        disable_silence_detection,
                        min_duration,
                        vad_aggressiveness,
                    )

                except Exception as reinit_error:
                    logger.error(f"Failed to reinitialize audio: {reinit_error}")
                    # Fall through to normal error handling

            # Get helpful error message
            help_message = get_audio_error_help(e)
            logger.error(f"\n{help_message}")

            logger.info("Falling back to fixed duration recording")
            # For fallback, assume speech is present since we can't detect
            return (record_audio(max_duration), True)

        finally:
            # Restore stdio
            if sys.stdin != original_stdin:
                sys.stdin = original_stdin
            if sys.stdout != original_stdout:
                sys.stdout = original_stdout
            if sys.stderr != original_stderr:
                sys.stderr = original_stderr

    except Exception as e:
        logger.error(f"VAD initialization failed: {e}")
        logger.info("Falling back to fixed duration recording")
        # For fallback, assume speech is present since we can't detect
        return (record_audio(max_duration), True)


# VM-742: task=True disabled — Docket in-memory worker causes connection failures
# when clients (Osaurus) don't support the task protocol. Re-enable after configuring
# Docket properly or when all clients support background tasks.
# @mcp.tool(task=True)
def _build_converse_request(
    *,
    message: str,
    wait_for_response: bool,
    should_skip_tts: bool,
    voice: Optional[str],
    tts_model: Optional[str],
    tts_provider: Optional[str],
    tts_instructions: Optional[str],
    audio_format: Optional[str],
    speed: Optional[float],
    listen_duration_max: float,
    listen_duration_min: float,
    disable_silence_detection: bool,
    vad_aggressiveness: Optional[int],
    chime_enabled: Optional[bool],
    chime_leading_silence: Optional[float],
    chime_trailing_silence: Optional[float],
    settings,
    metrics_level: str,
    transport: str,
) -> ConverseRequest:
    return ConverseRequest(
        message=message,
        wait_for_response=wait_for_response,
        should_skip_tts=should_skip_tts,
        voice=voice,
        tts_model=tts_model,
        tts_provider=tts_provider,
        tts_instructions=tts_instructions,
        audio_format=audio_format,
        speed=speed,
        listen_duration_max=listen_duration_max,
        listen_duration_min=listen_duration_min,
        disable_silence_detection=disable_silence_detection,
        vad_aggressiveness=vad_aggressiveness,
        chime_enabled=chime_enabled,
        chime_leading_silence=chime_leading_silence,
        chime_trailing_silence=chime_trailing_silence,
        save_audio=SAVE_AUDIO,
        audio_dir=str(AUDIO_DIR) if SAVE_AUDIO and AUDIO_DIR else None,
        debug=DEBUG,
        debug_dir=str(DEBUG_DIR) if DEBUG and DEBUG_DIR else None,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        use_realtime_stt=bool(
            settings.elevenlabs_api_key
            and getattr(voice_mode.config, "ELEVENLABS_USE_REALTIME_STT", False)
        ),
        stt_language=settings.stt_language
        if settings.stt_language and settings.stt_language != "auto"
        else None,
        metrics_level=metrics_level,
        transport=transport,
        save_transcriptions=SAVE_TRANSCRIPTIONS,
        global_disable_silence_detection=DISABLE_SILENCE_DETECTION,
        default_vad_aggressiveness=VAD_AGGRESSIVENESS,
        silence_threshold_ms=SILENCE_THRESHOLD_MS,
    )


def _build_converse_ports(*, event_logger, session_id: Optional[str]) -> ConversePorts:
    def _log_conversation_stt(**kwargs) -> None:
        get_conversation_logger().log_stt(**kwargs)

    def _end_event_session() -> None:
        if event_logger and session_id:
            event_logger.end_session()

    return ConversePorts(
        progress=_ctx_progress,
        info=_ctx_info,
        tts_with_failover=text_to_speech_with_failover,
        play_audio_feedback=play_audio_feedback,
        record_audio_with_silence_detection=record_audio_with_silence_detection,
        speech_to_text=speech_to_text,
        provider_realtime_stt=get_voice_provider().realtime_stt,
        log_conversation_stt=_log_conversation_stt,
        track_voice_interaction=track_voice_interaction,
        save_transcription=save_transcription,
        log_error=logger.error,
        end_event_session=_end_event_session,
    )



@mcp.tool()
async def converse(
    message: str,
    wait_for_response: Union[bool, str] = True,
    listen_duration_max: float = 300.0,
    listen_duration_min: float = 5.0,
    timeout: float = 300.0,
    voice: Optional[str] = None,
    tts_provider: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_instructions: Optional[str] = None,
    chime_enabled: Optional[Union[bool, str]] = None,
    audio_format: Optional[str] = None,
    disable_silence_detection: Union[bool, str] = False,
    speed: Optional[float] = None,
    vad_aggressiveness: Optional[Union[int, str]] = None,
    skip_tts: Optional[Union[bool, str]] = None,
    chime_leading_silence: Optional[float] = None,
    chime_trailing_silence: Optional[float] = None,
    metrics_level: Optional[Literal["minimal", "summary", "verbose"]] = None,
    wait_for_conch: Union[bool, str] = True,
    ctx: Optional[Context] = None,
) -> str:
    """Have a voice conversation — speak a message and listen for the user's response.

    Uses ElevenLabs for both TTS (text-to-speech) and STT (speech-to-text).
    TTS uses the eleven_v3 model with a configured voice. STT uses Scribe v2 Realtime
    for low-latency streaming transcription with server-side VAD.

    KEY PARAMETERS:
    • message (required): Text to speak to the user
    • wait_for_response (bool, default: true): Listen after speaking. Set false for announcements.
    • speed (0.7-1.2): Speech rate. Default 1.2 (max). ElevenLabs range is 0.7-1.2.
    • disable_silence_detection (bool, default: false): Set true to record for full listen_duration_max
    • vad_aggressiveness (0-3, default: 1): Voice detection strictness. 0=most tolerant of pauses, 3=most strict
    • listen_duration_max (number, default: 300): Max listen time in SECONDS (300 = 5 minutes)
    • listen_duration_min (number, default: 5.0): Min recording in SECONDS before silence detection kicks in
    • timeout (number, default: 300): MCP call timeout in SECONDS. MUST be >= listen_duration_max.
    • metrics_level ("minimal"|"summary"|"verbose"): Output detail level
    • wait_for_conch (bool, default: true): Auto-queues behind another speaker. No need to set this.

    CRITICAL — TIMEOUT MUST MATCH LISTEN DURATION:
    The timeout parameter controls when the MCP call times out. If timeout < listen_duration_max,
    the call will time out before the user finishes speaking. ALWAYS set timeout >= listen_duration_max.
    Both are in SECONDS. Default is 300 seconds (5 minutes) for both.

    WHEN USER GETS CUT OFF:
    Increase listen_duration_min to 10, lower vad_aggressiveness to 0, or set disable_silence_detection=true.

    PARALLEL PATTERN (zero dead air):
    Call converse(msg, wait_for_response=false) alongside other tools in the same turn.

    CONCH: Only one agent can use the mic at a time. If you get "User is currently speaking",
    set wait_for_conch=true to queue, or try again later.

    CLAUDE DESKTOP (60s TIMEOUT):
    Claude Desktop enforces a hardcoded 60-second MCP timeout. Split speak+listen into two calls:
    1. converse(message="...", wait_for_response=false) — speak only
    2. converse(message="", skip_tts=true, listen_duration_max=50, timeout=55) — listen only
    Keep each call under 60s total. See /converse-cowork command for full pattern.
    """
    # Convert string booleans to actual booleans
    if isinstance(wait_for_response, str):
        wait_for_response = wait_for_response.lower() in ("true", "1", "yes", "on")
    if isinstance(disable_silence_detection, str):
        disable_silence_detection = disable_silence_detection.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
    if isinstance(chime_enabled, str):
        chime_enabled = chime_enabled.lower() in ("true", "1", "yes", "on")
    if skip_tts is not None and isinstance(skip_tts, str):
        skip_tts = skip_tts.lower() in ("true", "1", "yes", "on")
    if isinstance(wait_for_conch, str):
        wait_for_conch = wait_for_conch.lower() in ("true", "1", "yes", "on")

    # Convert vad_aggressiveness to integer if provided as string
    if vad_aggressiveness is not None and isinstance(vad_aggressiveness, str):
        try:
            vad_aggressiveness = int(vad_aggressiveness)
            # Validation will happen later in the function
        except ValueError:
            logger.warning(
                f"Invalid VAD aggressiveness value '{vad_aggressiveness}', using default"
            )
            vad_aggressiveness = None

    # Determine whether to skip TTS
    if skip_tts is not None:
        # Parameter explicitly set, use it
        should_skip_tts = skip_tts
    else:
        # Use global setting
        should_skip_tts = SKIP_TTS

    # Convert string speed to float
    if speed is not None and isinstance(speed, str):
        try:
            speed = float(speed)
        except ValueError:
            return f"❌ Error: speed must be a number (got '{speed}')"

    # Apply default speed from config if not provided
    speed_from_config = False
    if speed is None:
        speed = TTS_SPEED
        speed_from_config = True

    # Validate speed parameter range (ElevenLabs supports 0.7-1.2)
    if speed is not None:
        if not (0.7 <= speed <= 1.2):
            source = (
                " from VOICEMODE_TTS_SPEED environment variable"
                if speed_from_config
                else ""
            )
            return f"❌ Error: speed must be between 0.7 and 1.2 (got {speed}{source})"

    # Determine effective metrics level (parameter overrides config)
    effective_metrics_level = metrics_level if metrics_level else METRICS_LEVEL

    logger.info(
        f"Converse: '{message[:50]}{'...' if len(message) > 50 else ''}' (wait_for_response: {wait_for_response})"
    )

    # Validate vad_aggressiveness parameter
    if vad_aggressiveness is not None:
        if (
            not isinstance(vad_aggressiveness, int)
            or vad_aggressiveness < 0
            or vad_aggressiveness > 3
        ):
            return f"Error: vad_aggressiveness must be an integer between 0 and 3 (got {vad_aggressiveness})"

    # Validate duration parameters
    if wait_for_response:
        if listen_duration_min < 0:
            return "❌ Error: listen_duration_min cannot be negative"
        if listen_duration_max <= 0:
            return "❌ Error: listen_duration_max must be positive"
        if listen_duration_min > listen_duration_max:
            logger.warning(
                f"listen_duration_min ({listen_duration_min}s) is greater than listen_duration_max ({listen_duration_max}s), using listen_duration_max as minimum"
            )
            listen_duration_min = listen_duration_max

    # Check if FFmpeg is available
    ffmpeg_available = getattr(
        voice_mode.config, "FFMPEG_AVAILABLE", True
    )  # Default to True if not set
    if not ffmpeg_available:
        from ..utils.ffmpeg_check import get_install_instructions

        error_msg = (
            "FFmpeg is required for voice features but is not installed.\n\n"
            f"{get_install_instructions()}\n\n"
            "Voice features cannot work without FFmpeg."
        )
        logger.error(error_msg)
        return f"❌ Error: {error_msg}"

    # Run startup initialization if needed
    await startup_initialization()

    # Refresh audio device cache to pick up any device changes (AirPods, etc.)
    # This takes ~1ms and ensures we use the current default device
    import sounddevice as sd

    sd._terminate()
    sd._initialize()

    # Get event logger and start session
    event_logger = get_event_logger()
    session_id = None

    # Check time since last session for AI thinking time
    global last_session_end_time
    current_time = time.time()

    if last_session_end_time and wait_for_response:
        time_since_last = current_time - last_session_end_time
        logger.info(
            f"Time since last session: {time_since_last:.1f}s (AI thinking time)"
        )

    # For conversations with responses, create a session
    if event_logger and wait_for_response:
        session_id = event_logger.start_session()
        # Log the time since last session as an event
        if last_session_end_time:
            event_logger.log_event(
                "TIME_SINCE_LAST_SESSION", {"seconds": time_since_last}
            )

    # Log tool request start (after session is created)
    if event_logger:
        # If we have a session, the event will be associated with it
        log_tool_request_start(
            "converse",
            {
                "wait_for_response": wait_for_response,
                "listen_duration_max": listen_duration_max
                if wait_for_response
                else None,
            },
        )

    # Track execution time and resources
    start_time = time.time()
    if DEBUG:
        import resource

        start_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        logger.debug(f"Starting converse - Memory: {start_memory} KB")

    result = None
    success = False
    conch = Conch(agent_name="converse")  # Named for event logging

    try:
        # Try to acquire conch atomically (no race condition)
        if CONCH_ENABLED:
            acquired = conch.try_acquire()

            if not acquired:
                # Another agent has the conch
                holder = Conch.get_holder()
                holder_agent = holder.get("agent", "unknown") if holder else "unknown"

                if event_logger:
                    event_logger.log_event(
                        "CONCH_BLOCKED",
                        {
                            "pid": os.getpid(),
                            "holder_pid": holder.get("pid") if holder else None,
                            "holder_agent": holder_agent,
                            "wait_for_conch": wait_for_conch,
                        },
                    )

                if not wait_for_conch:
                    # Default: return immediately with status info
                    return (
                        f"User is currently speaking with {holder_agent}. "
                        "Use wait_for_conch=true to queue, or try again later."
                    )

                # Wait mode - poll with atomic retry
                if event_logger:
                    event_logger.log_event(
                        "CONCH_WAIT_START",
                        {
                            "pid": os.getpid(),
                            "holder_agent": holder_agent,
                            "timeout": CONCH_TIMEOUT,
                        },
                    )

                waited = 0.0
                while not conch.try_acquire() and waited < CONCH_TIMEOUT:
                    await asyncio.sleep(CONCH_CHECK_INTERVAL)
                    waited += CONCH_CHECK_INTERVAL

                if event_logger:
                    event_logger.log_event(
                        "CONCH_WAIT_END",
                        {
                            "pid": os.getpid(),
                            "waited_seconds": waited,
                            "result": "acquired" if conch._acquired else "timeout",
                        },
                    )

                if not conch._acquired:
                    return f"Timed out waiting for conch ({CONCH_TIMEOUT}s). {holder_agent} is still speaking."

            # Successfully acquired
            if event_logger:
                event_logger.log_event(
                    "CONCH_ACQUIRE", {"pid": os.getpid(), "agent": "converse"}
                )

        # Local microphone approach with timing
        transport = "local"
        timings = {}
        try:
            runtime = get_runtime_context()
            settings = runtime.settings()
            session = ConverseSession(
                audio_operation_lock=audio_operation_lock,
                dj_ducker_factory=DJDucker,
                event_logger=event_logger,
            )
            disconnect_watcher = None
            session_task = None
            disconnect_watcher = asyncio.create_task(_watch_client_disconnect(ctx))
            session_task = asyncio.create_task(
                session.run(
                    _build_converse_request(
                        message=message,
                        wait_for_response=wait_for_response,
                        should_skip_tts=should_skip_tts,
                        voice=voice,
                        tts_model=tts_model,
                        tts_provider=tts_provider,
                        tts_instructions=tts_instructions,
                        audio_format=audio_format,
                        speed=speed,
                        listen_duration_max=listen_duration_max,
                        listen_duration_min=listen_duration_min,
                        disable_silence_detection=disable_silence_detection,
                        vad_aggressiveness=vad_aggressiveness,
                        chime_enabled=chime_enabled,
                        chime_leading_silence=chime_leading_silence,
                        chime_trailing_silence=chime_trailing_silence,
                        settings=settings,
                        metrics_level=effective_metrics_level,
                        transport=transport,
                    ),
                    _build_converse_ports(event_logger=event_logger, session_id=session_id),
                    ctx=ctx,
                )
            )
            try:
                done, _ = await asyncio.wait(
                    {session_task, disconnect_watcher},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_watcher in done and not session_task.done():
                    stop_current_playback()
                    session_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await session_task
                    raise asyncio.CancelledError()

                session_result = await session_task
            except asyncio.CancelledError:
                stop_current_playback()
                if session_task is not None and not session_task.done():
                    session_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await session_task
                raise
            finally:
                if disconnect_watcher is not None:
                    disconnect_watcher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await disconnect_watcher
            result = session_result.result
            success = session_result.mcp_success
            return result or ""

        except Exception as e:
            logger.error(f"Local voice error: {e}")
            if DEBUG:
                logger.error(f"Traceback: {traceback.format_exc()}")


            result = f"Error: {str(e)}"
            return result

    except asyncio.CancelledError:
        logger.warning("Converse cancelled (client disconnected or timeout)")
        stop_current_playback()
        raise

    except Exception as e:
        logger.error(f"Unexpected error in converse: {e}")
        if DEBUG:
            logger.error(f"Full traceback: {traceback.format_exc()}")
        result = f"Unexpected error: {str(e)}"
        return result

    finally:
        # Release the conch to signal voice conversation has ended
        if CONCH_ENABLED and conch._acquired:
            held_seconds = conch.release()
            if event_logger:
                event_logger.log_event(
                    "CONCH_RELEASE", {"pid": os.getpid(), "held_seconds": held_seconds}
                )
        else:
            # Don't call release() when not acquired — it would delete the lock
            # file belonging to the agent that IS holding the conch, defeating
            # the flock coordination (they'd end up locking different inodes).
            pass

        # Log tool request end
        if event_logger:
            log_tool_request_end("converse", success=success)

        # Update last session end time for tracking AI thinking time
        if wait_for_response:
            last_session_end_time = time.time()

        # Log execution metrics
        elapsed = time.time() - start_time
        logger.info(f"Converse completed in {elapsed:.2f}s")

        if DEBUG:
            import resource
            import gc

            end_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            memory_delta = end_memory - start_memory
            logger.debug(
                f"Memory delta: {memory_delta} KB (start: {start_memory}, end: {end_memory})"
            )

            # Force garbage collection
            collected = gc.collect()
            logger.debug(f"Garbage collected {collected} objects")
