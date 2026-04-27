"""
Core functionality for voice-mode.

This module contains the main functions used by the voice-mode script,
extracted to allow for easier testing and reuse.
"""

import logging
import os
import tempfile
import gc
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from pydub import AudioSegment

from .config import SAMPLE_RATE
from .utils import (
    get_event_logger,
    update_latest_symlinks
)
from .audio_player import NonBlockingAudioPlayer

logger = logging.getLogger("voicemode")


def get_audio_path(filename: str, base_dir: Path, timestamp: Optional[datetime] = None) -> Path:
    """Get full audio path with year/month structure for a given filename.
    
    Args:
        filename: Just the filename (e.g., "20250728_123456_789_abc123_tts.wav")
        base_dir: Base audio directory
        timestamp: Optional timestamp to determine year/month. If not provided, 
                   will be extracted from filename or use current date.
        
    Returns:
        Full path with year/month structure
    """
    # Try to extract date from filename if timestamp not provided
    if timestamp is None:
        try:
            # Extract YYYYMMDD from filename like "20250728_123456_789_abc123_tts.wav"
            date_str = filename.split('_')[0]
            if len(date_str) == 8 and date_str.isdigit():
                year = int(date_str[:4])
                month = int(date_str[4:6])
                timestamp = datetime(year, month, 1)
        except (IndexError, ValueError):
            pass
    
    # Fall back to current date if still no timestamp
    if timestamp is None:
        timestamp = datetime.now()
    
    # Build path with year/month structure
    year_dir = base_dir / str(timestamp.year)
    month_dir = year_dir / f"{timestamp.month:02d}"
    
    return month_dir / filename


def get_debug_filename(prefix: str, extension: str, conversation_id: Optional[str] = None) -> str:
    """Generate debug filename with timestamp and optional conversation ID.
    
    Args:
        prefix: File prefix (e.g., 'tts', 'stt')
        extension: File extension (e.g., 'mp3', 'wav')
        conversation_id: Optional conversation ID to include in filename
        
    Returns:
        Filename in format: timestamp_conv_id_prefix.extension
        or timestamp_prefix.extension if no conversation ID
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # milliseconds
    
    if conversation_id:
        # Extract just the suffix part of conversation ID for brevity
        # conv_20250628_233802_4t8u0f -> 4t8u0f
        conv_suffix = conversation_id.split('_')[-1] if '_' in conversation_id else conversation_id
        return f"{timestamp}_{conv_suffix}_{prefix}.{extension}"
    else:
        return f"{timestamp}-{prefix}.{extension}"


def save_debug_file(data: bytes, prefix: str, extension: str, debug_dir: Path, debug: bool = False, conversation_id: Optional[str] = None) -> Optional[str]:
    """Save debug file if debug mode is enabled.
    
    Args:
        data: File data to save
        prefix: File prefix (e.g., 'tts', 'stt')
        extension: File extension
        debug_dir: Directory to save files in
        debug: Whether to save the file
        conversation_id: Optional conversation ID to include in filename
        
    Returns:
        Path to saved file or None
    """
    if not debug:
        return None
    
    try:
        # Get current date for directory structure
        now = datetime.now()
        year_dir = debug_dir / str(now.year)
        month_dir = year_dir / f"{now.month:02d}"
        
        # Create year/month directory structure
        month_dir.mkdir(parents=True, exist_ok=True)
        
        filename = get_debug_filename(prefix, extension, conversation_id)
        filepath = month_dir / filename
        
        with open(filepath, 'wb') as f:
            f.write(data)
        
        logger.debug(f"Debug file saved: {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"Failed to save debug file: {e}")
        return None


def get_openai_clients(api_key: str = "", stt_base_url: Optional[str] = None, tts_base_url: Optional[str] = None) -> dict:
    """Deprecated stub — OpenAI clients are no longer used. Returns empty dict."""
    return {}


async def text_to_speech(
    text: str,
    openai_clients: dict,
    tts_model: str,
    tts_voice: str,
    tts_base_url: str,
    debug: bool = False,
    debug_dir: Optional[Path] = None,
    save_audio: bool = False,
    audio_dir: Optional[Path] = None,
    client_key: str = 'tts',
    instructions: Optional[str] = None,
    audio_format: Optional[str] = None,
    conversation_id: Optional[str] = None,
    speed: Optional[float] = None
) -> tuple[bool, Optional[dict]]:
    """Convert text to speech and play it through the deep TTS orchestrator boundary."""
    from .tts_orchestrator import TTSOrchestrator, TTSRequest

    del openai_clients, client_key, conversation_id

    orchestrator = TTSOrchestrator()
    return await orchestrator.speak(
        TTSRequest(
            text=text,
            voice=tts_voice,
            model=tts_model,
            base_url=tts_base_url,
            instructions=instructions,
            audio_format=audio_format,
            speed=speed,
            debug=debug,
            debug_dir=debug_dir,
            save_audio=save_audio,
            audio_dir=audio_dir,
        )
    )


def generate_chime(
    frequencies: list, 
    duration: float = 0.1, 
    sample_rate: int = SAMPLE_RATE,
    leading_silence: Optional[float] = None,
    trailing_silence: Optional[float] = None
) -> np.ndarray:
    """Generate a chime sound with given frequencies.
    
    Args:
        frequencies: List of frequencies to play in sequence
        duration: Duration of each tone in seconds
        sample_rate: Sample rate for audio generation
        leading_silence: Optional override for leading silence duration (seconds)
        trailing_silence: Optional override for trailing silence duration (seconds)
        
    Returns:
        Numpy array of audio samples
    """
    samples_per_tone = int(sample_rate * duration)
    fade_samples = int(sample_rate * 0.01)  # 10ms fade
    
    # Determine amplitude based on output device
    amplitude = 0.0375  # Default (very quiet)
    try:
        import sounddevice as sd
        default_output = sd.default.device[1]
        if default_output is not None:
            devices = sd.query_devices()
            device_name = devices[default_output]['name'].lower()
            # Check for Bluetooth devices (AirPods, Bluetooth headphones, etc)
            if 'airpod' in device_name or 'bluetooth' in device_name or 'bt' in device_name:
                amplitude = 0.15  # Higher amplitude for Bluetooth devices
                logger.debug(f"Bluetooth device detected ({devices[default_output]['name']}), using amplitude {amplitude}")
            else:
                amplitude = 0.075  # Moderate amplitude for built-in speakers
                logger.debug(f"Built-in speaker detected ({devices[default_output]['name']}), using amplitude {amplitude}")
    except Exception as e:
        logger.debug(f"Could not detect output device type: {e}, using default amplitude {amplitude}")
    
    all_samples = []
    
    for freq in frequencies:
        # Generate sine wave
        t = np.linspace(0, duration, samples_per_tone, False)
        tone = amplitude * np.sin(2 * np.pi * freq * t)
        
        # Apply fade in/out to prevent clicks
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)
        
        tone[:fade_samples] *= fade_in
        tone[-fade_samples:] *= fade_out
        
        all_samples.append(tone)
    
    # Concatenate all tones
    chime = np.concatenate(all_samples)
    
    # Import config values if not overridden
    from .config import CHIME_LEADING_SILENCE, CHIME_TRAILING_SILENCE

    # Use parameter overrides or fall back to config
    actual_leading_silence = leading_silence if leading_silence is not None else CHIME_LEADING_SILENCE
    actual_trailing_silence = trailing_silence if trailing_silence is not None else CHIME_TRAILING_SILENCE
    
    # Add leading silence for Bluetooth wake-up time
    # This prevents the beginning of the chime from being cut off
    silence_samples = int(sample_rate * actual_leading_silence)
    silence = np.zeros(silence_samples)
    
    # Add trailing silence to prevent end cutoff
    trailing_silence_samples = int(sample_rate * actual_trailing_silence)
    trailing_silence = np.zeros(trailing_silence_samples)
    
    # Combine: leading silence + chime + trailing silence
    chime_with_buffer = np.concatenate([silence, chime, trailing_silence])
    
    # Convert to 16-bit integer
    chime_int16 = (chime_with_buffer * 32767).astype(np.int16)
    
    return chime_int16


async def play_chime_start(
    sample_rate: int = SAMPLE_RATE,
    leading_silence: Optional[float] = None,
    trailing_silence: Optional[float] = None
) -> bool:
    """Play the recording start chime (ascending tones).

    Args:
        sample_rate: Sample rate for audio
        leading_silence: Optional override for leading silence duration (seconds)
        trailing_silence: Optional override for trailing silence duration (seconds)

    Returns:
        True if chime played successfully, False otherwise
    """
    try:
        chime = generate_chime(
            [800, 1000],
            duration=0.1,
            sample_rate=sample_rate,
            leading_silence=leading_silence,
            trailing_silence=trailing_silence
        )
        # Convert int16 to float32 normalized to [-1, 1] for NonBlockingAudioPlayer
        chime_float = chime.astype(np.float32) / 32768.0
        # Use non-blocking audio player to avoid interference with concurrent playback
        player = NonBlockingAudioPlayer()
        player.play(chime_float, sample_rate, blocking=True)
        return True
    except Exception as e:
        logger.debug(f"Could not play start chime: {e}")
        return False


async def play_chime_end(
    sample_rate: int = SAMPLE_RATE,
    leading_silence: Optional[float] = None,
    trailing_silence: Optional[float] = None
) -> bool:
    """Play the recording end chime (descending tones).

    Args:
        sample_rate: Sample rate for audio
        leading_silence: Optional override for leading silence duration (seconds)
        trailing_silence: Optional override for trailing silence duration (seconds)

    Returns:
        True if chime played successfully, False otherwise
    """
    try:
        chime = generate_chime(
            [1000, 800],
            duration=0.1,
            sample_rate=sample_rate,
            leading_silence=leading_silence,
            trailing_silence=trailing_silence
        )
        # Convert int16 to float32 normalized to [-1, 1] for NonBlockingAudioPlayer
        chime_float = chime.astype(np.float32) / 32768.0
        # Use non-blocking audio player to avoid interference with concurrent playback
        player = NonBlockingAudioPlayer()
        player.play(chime_float, sample_rate, blocking=True)
        return True
    except Exception as e:
        logger.debug(f"Could not play end chime: {e}")
        return False


async def play_system_audio(message_key: str, fallback_text: Optional[str] = None, soundfont: str = "default") -> bool:
    """Play a pre-recorded system audio message with fallback to TTS.

    System audio files should be stored in voice_mode/data/soundfonts/{soundfont}/system-messages/
    with the naming pattern: {message_key}.mp3 (or .wav, .opus, .opus, etc.)

    Args:
        message_key: Key for the system message (e.g., "waiting-1-minute", "ready-to-listen", "repeating")
        fallback_text: Text to speak if audio file doesn't exist (falls back to TTS)
        soundfont: Name of the soundfont to use (default: "default")

    Returns:
        True if audio was played successfully, False otherwise
    """
    from pathlib import Path
    from pydub import AudioSegment
    import numpy as np

    # Get path to system messages directory in soundfonts
    system_audio_dir = Path(__file__).parent / "data" / "soundfonts" / soundfont / "system-messages"

    # Try to find the audio file (support multiple formats)
    audio_file = None
    for ext in ['.mp3', '.wav', '.opus', '.m4a']:
        candidate = system_audio_dir / f"{message_key}{ext}"
        if candidate.exists():
            audio_file = candidate
            break

    if audio_file:
        try:
            logger.info(f"🔊 Playing system audio: {audio_file}")
            audio = AudioSegment.from_file(str(audio_file))
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
            samples = samples / (2**15)  # Normalize to [-1, 1]

            # Use non-blocking audio player to avoid interference with concurrent playback
            player = NonBlockingAudioPlayer()
            player.play(samples, audio.frame_rate, blocking=True)

            logger.info(f"✓ System audio played successfully: {message_key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to play system audio {audio_file}: {e}")
            # Fall through to TTS fallback

    # If no audio file or playback failed, use TTS fallback
    if fallback_text:
        logger.info(f"Using TTS fallback for system message '{message_key}': {fallback_text}")
        # Import here to avoid circular dependency
        from voice_mode.elevenlabs_tts_stt import elevenlabs_tts
        success, metrics, config = await elevenlabs_tts(
            text=fallback_text,
            voice="af_sky",  # Use AF Sky for system messages
            model="tts-1"  # Use standard TTS model for system messages
        )
        return success

    return False


async def cleanup(openai_clients: dict = None):
    """Cleanup function — no-op since OpenAI clients are no longer used."""
    logger.info("Shutting down Voice Mode Server...")
    gc.collect()
    logger.info("Cleanup completed")
