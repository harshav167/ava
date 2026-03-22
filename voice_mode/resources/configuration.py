"""MCP resources for voice mode configuration."""

import os
from typing import Dict, Any
from pathlib import Path

from ..server import mcp
from ..config import (
    logger,
    # Core settings
    BASE_DIR, DEBUG, SAVE_ALL, SAVE_AUDIO, SAVE_TRANSCRIPTIONS,
    AUDIO_FEEDBACK_ENABLED,
    # Service settings
    OPENAI_API_KEY, TTS_BASE_URLS, STT_BASE_URLS, TTS_VOICES, TTS_MODELS,
    # ElevenLabs settings
    ELEVENLABS_API_KEY, ELEVENLABS_TTS_MODEL, ELEVENLABS_TTS_VOICE,
    ELEVENLABS_STT_MODEL, STT_LANGUAGE,
    # Audio settings
    AUDIO_FORMAT, TTS_AUDIO_FORMAT, STT_AUDIO_FORMAT,
    SAMPLE_RATE, CHANNELS,
    # Silence detection
    DISABLE_SILENCE_DETECTION, VAD_AGGRESSIVENESS, SILENCE_THRESHOLD_MS,
    MIN_RECORDING_DURATION, INITIAL_SILENCE_GRACE_PERIOD, DEFAULT_LISTEN_DURATION,
    # Streaming
    STREAMING_ENABLED, STREAM_CHUNK_SIZE, STREAM_BUFFER_MS, STREAM_MAX_BUFFER,
    # Event logging
    EVENT_LOG_ENABLED, EVENT_LOG_DIR, EVENT_LOG_ROTATION
)


def mask_sensitive(value: Any, key: str) -> Any:
    """Mask sensitive values like API keys."""
    if key.lower().endswith('_key') or key.lower().endswith('_secret'):
        if value and isinstance(value, str):
            return f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
    return value


@mcp.resource("voice://config/all")
async def all_configuration() -> str:
    """
    Complete voice mode configuration.

    Shows all current configuration settings including:
    - Core settings (directories, saving options)
    - ElevenLabs provider settings
    - Audio settings (formats, quality)
    - Silence detection parameters
    - Streaming configuration
    - Event logging settings

    Sensitive values like API keys are masked for security.
    """
    lines = []
    lines.append("Voice Mode Configuration")
    lines.append("=" * 80)
    lines.append("")

    # Core Settings
    lines.append("Core Settings:")
    lines.append(f"  Base Directory: {BASE_DIR}")
    lines.append(f"  Debug Mode: {DEBUG}")
    lines.append(f"  Save All: {SAVE_ALL}")
    lines.append(f"  Save Audio: {SAVE_AUDIO}")
    lines.append(f"  Save Transcriptions: {SAVE_TRANSCRIPTIONS}")
    lines.append(f"  Audio Feedback: {AUDIO_FEEDBACK_ENABLED}")
    lines.append("")

    # Provider Settings
    lines.append("Provider Settings (ElevenLabs):")
    lines.append(f"  TTS Endpoints: {', '.join(TTS_BASE_URLS)}")
    lines.append(f"  STT Endpoints: {', '.join(STT_BASE_URLS)}")
    lines.append(f"  TTS Voices: {', '.join(TTS_VOICES)}")
    lines.append(f"  TTS Models: {', '.join(TTS_MODELS)}")
    if ELEVENLABS_API_KEY:
        lines.append(f"  ElevenLabs API Key: {mask_sensitive(ELEVENLABS_API_KEY, 'api_key')}")
    lines.append(f"  ElevenLabs TTS Model: {ELEVENLABS_TTS_MODEL}")
    lines.append(f"  ElevenLabs TTS Voice: {ELEVENLABS_TTS_VOICE}")
    lines.append(f"  ElevenLabs STT Model: {ELEVENLABS_STT_MODEL}")
    lines.append(f"  STT Language: {STT_LANGUAGE}")
    lines.append("")

    # Audio Settings
    lines.append("Audio Settings:")
    lines.append(f"  Format: {AUDIO_FORMAT}")
    lines.append(f"  TTS Format: {TTS_AUDIO_FORMAT}")
    lines.append(f"  STT Format: {STT_AUDIO_FORMAT}")
    lines.append(f"  Sample Rate: {SAMPLE_RATE} Hz")
    lines.append(f"  Channels: {CHANNELS}")
    lines.append("")

    # Silence Detection
    lines.append("Silence Detection:")
    lines.append(f"  Disabled: {DISABLE_SILENCE_DETECTION}")
    lines.append(f"  VAD Aggressiveness: {VAD_AGGRESSIVENESS}")
    lines.append(f"  Silence Threshold: {SILENCE_THRESHOLD_MS} ms")
    lines.append(f"  Min Recording Duration: {MIN_RECORDING_DURATION} s")
    lines.append(f"  Initial Silence Grace: {INITIAL_SILENCE_GRACE_PERIOD} s")
    lines.append(f"  Default Listen Duration: {DEFAULT_LISTEN_DURATION} s")
    lines.append("")

    # Streaming
    lines.append("Streaming:")
    lines.append(f"  Enabled: {STREAMING_ENABLED}")
    lines.append(f"  Chunk Size: {STREAM_CHUNK_SIZE} bytes")
    lines.append(f"  Buffer: {STREAM_BUFFER_MS} ms")
    lines.append(f"  Max Buffer: {STREAM_MAX_BUFFER} s")
    lines.append("")

    # Event Logging
    lines.append("Event Logging:")
    lines.append(f"  Enabled: {EVENT_LOG_ENABLED}")
    lines.append(f"  Directory: {EVENT_LOG_DIR}")
    lines.append(f"  Rotation: {EVENT_LOG_ROTATION}")

    return "\n".join(lines)


def parse_env_file(file_path: Path) -> Dict[str, str]:
    """Parse an environment file and return a dictionary of key-value pairs."""
    config = {}
    if not file_path.exists():
        return config

    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE format
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    config[key] = value
    except Exception as e:
        logger.error(f"Error parsing {file_path}: {e}")

    return config


@mcp.resource("voice://config/env-vars")
async def environment_variables() -> str:
    """
    All voice mode environment variables with current values.

    Shows each configuration variable with:
    - Name: The environment variable name
    - Environment Value: Current value from environment
    - Config File Value: Value from ~/.voicemode/voicemode.env (if exists)
    - Description: What the variable controls

    This helps identify configuration sources and troubleshoot settings.
    """
    # Parse config file - try new path first, fall back to old
    user_config_path = Path.home() / ".voicemode" / "voicemode.env"
    if not user_config_path.exists():
        old_path = Path.home() / ".voicemode" / ".voicemode.env"
        if old_path.exists():
            user_config_path = old_path
    file_config = parse_env_file(user_config_path)

    # Define all configuration variables with descriptions
    config_vars = [
        # Core Settings
        ("VOICEMODE_BASE_DIR", "Base directory for all voicemode data"),
        ("VOICEMODE_MODELS_DIR", "Directory for all models (defaults to $VOICEMODE_BASE_DIR/models)"),
        ("VOICEMODE_DEBUG", "Enable debug mode (true/false)"),
        ("VOICEMODE_SAVE_ALL", "Save all audio and transcriptions (true/false)"),
        ("VOICEMODE_SAVE_AUDIO", "Save audio files (true/false)"),
        ("VOICEMODE_SAVE_TRANSCRIPTIONS", "Save transcription files (true/false)"),
        ("VOICEMODE_AUDIO_FEEDBACK", "Enable audio feedback (true/false)"),
        # Provider Settings
        ("VOICEMODE_TTS_BASE_URLS", "Comma-separated list of TTS endpoints"),
        ("VOICEMODE_STT_BASE_URLS", "Comma-separated list of STT endpoints"),
        ("VOICEMODE_VOICES", "Comma-separated list of preferred voices"),
        ("VOICEMODE_TTS_MODELS", "Comma-separated list of preferred models"),
        # Audio Settings
        ("VOICEMODE_AUDIO_FORMAT", "Audio format for recording (pcm/mp3/wav/flac/aac/opus)"),
        ("VOICEMODE_TTS_AUDIO_FORMAT", "Audio format for TTS output"),
        ("VOICEMODE_STT_AUDIO_FORMAT", "Audio format for STT input"),
        # STT Prompt for vocabulary biasing
        ("VOICEMODE_STT_PROMPT", "Vocabulary hints for STT (names, technical terms)"),
        # STT Language
        ("VOICEMODE_STT_LANGUAGE", "Language for transcription (default: auto)"),
        # ElevenLabs Configuration
        ("ELEVENLABS_API_KEY", "ElevenLabs API key for TTS/STT"),
        ("VOICEMODE_ELEVENLABS_TTS_MODEL", "ElevenLabs TTS model (e.g., eleven_v3)"),
        ("VOICEMODE_ELEVENLABS_TTS_VOICE", "ElevenLabs voice ID"),
        ("VOICEMODE_ELEVENLABS_STT_MODEL", "ElevenLabs STT model (e.g., scribe_v2_realtime)"),
        ("VOICEMODE_ELEVENLABS_REALTIME_STT", "Use realtime streaming STT (true/false)"),
        # Silence Detection
        ("VOICEMODE_DISABLE_SILENCE_DETECTION", "Disable silence detection (true/false)"),
        ("VOICEMODE_VAD_AGGRESSIVENESS", "Voice activity detection aggressiveness (0-3)"),
        ("VOICEMODE_SILENCE_THRESHOLD_MS", "Silence threshold in milliseconds"),
        ("VOICEMODE_MIN_RECORDING_DURATION", "Minimum recording duration in seconds"),
        ("VOICEMODE_INITIAL_SILENCE_GRACE_PERIOD", "Initial silence grace period in seconds"),
        ("VOICEMODE_DEFAULT_LISTEN_DURATION", "Default listen duration in seconds"),
        # Streaming
        ("VOICEMODE_STREAMING_ENABLED", "Enable audio streaming (true/false)"),
        ("VOICEMODE_STREAM_CHUNK_SIZE", "Stream chunk size in bytes"),
        ("VOICEMODE_STREAM_BUFFER_MS", "Stream buffer in milliseconds"),
        ("VOICEMODE_STREAM_MAX_BUFFER", "Maximum stream buffer in seconds"),
        # Event Logging
        ("VOICEMODE_EVENT_LOG_ENABLED", "Enable event logging (true/false)"),
        ("VOICEMODE_EVENT_LOG_DIR", "Directory for event logs"),
        ("VOICEMODE_EVENT_LOG_ROTATION", "Log rotation policy (daily/weekly/monthly)"),
    ]

    result = []
    result.append("Voice Mode Environment Variables")
    result.append("=" * 80)
    result.append("")

    for var_name, description in config_vars:
        env_value = os.getenv(var_name)
        config_value = file_config.get(var_name)

        # Mask sensitive values
        if 'KEY' in var_name or 'SECRET' in var_name:
            if env_value:
                env_value = mask_sensitive(env_value, var_name)
            if config_value:
                config_value = mask_sensitive(config_value, var_name)

        result.append(f"{var_name}")
        result.append(f"  Environment: {env_value or '[not set]'}")
        result.append(f"  Config File: {config_value or '[not set]'}")
        result.append(f"  Description: {description}")
        result.append("")

    return "\n".join(result)


@mcp.resource("voice://config/env-template")
async def environment_template() -> str:
    """
    Environment variable template for voice mode configuration.

    Provides a ready-to-use template of all available environment variables
    with their current values. This can be saved to ~/.voicemode/voicemode.env and
    customized as needed.

    Sensitive values like API keys are masked for security.
    """
    template_lines = [
        "#!/usr/bin/env bash",
        "# Voice Mode Environment Configuration",
        "# Generated from current settings",
        "",
        "# Core Settings",
        f"export VOICEMODE_BASE_DIR=\"{BASE_DIR}\"",
        f"export VOICEMODE_DEBUG=\"{str(DEBUG).lower()}\"",
        f"export VOICEMODE_SAVE_ALL=\"{str(SAVE_ALL).lower()}\"",
        f"export VOICEMODE_SAVE_AUDIO=\"{str(SAVE_AUDIO).lower()}\"",
        f"export VOICEMODE_SAVE_TRANSCRIPTIONS=\"{str(SAVE_TRANSCRIPTIONS).lower()}\"",
        f"export VOICEMODE_AUDIO_FEEDBACK=\"{str(AUDIO_FEEDBACK_ENABLED).lower()}\"",
        "",
        "# ElevenLabs Provider Settings",
        f"export VOICEMODE_TTS_BASE_URLS=\"{','.join(TTS_BASE_URLS)}\"",
        f"export VOICEMODE_STT_BASE_URLS=\"{','.join(STT_BASE_URLS)}\"",
        f"export VOICEMODE_VOICES=\"{','.join(TTS_VOICES)}\"",
        f"export VOICEMODE_TTS_MODELS=\"{','.join(TTS_MODELS)}\"",
        f"export VOICEMODE_STT_LANGUAGE=\"{STT_LANGUAGE}\"",
        "",
        "# Audio Settings",
        f"export VOICEMODE_AUDIO_FORMAT=\"{AUDIO_FORMAT}\"",
        f"export VOICEMODE_TTS_AUDIO_FORMAT=\"{TTS_AUDIO_FORMAT}\"",
        f"export VOICEMODE_STT_AUDIO_FORMAT=\"{STT_AUDIO_FORMAT}\"",
        "",
        "# Silence Detection",
        f"export VOICEMODE_DISABLE_SILENCE_DETECTION=\"{str(DISABLE_SILENCE_DETECTION).lower()}\"",
        f"export VOICEMODE_VAD_AGGRESSIVENESS=\"{VAD_AGGRESSIVENESS}\"",
        f"export VOICEMODE_SILENCE_THRESHOLD_MS=\"{SILENCE_THRESHOLD_MS}\"",
        f"export VOICEMODE_MIN_RECORDING_DURATION=\"{MIN_RECORDING_DURATION}\"",
        f"export VOICEMODE_INITIAL_SILENCE_GRACE_PERIOD=\"{INITIAL_SILENCE_GRACE_PERIOD}\"",
        f"export VOICEMODE_DEFAULT_LISTEN_DURATION=\"{DEFAULT_LISTEN_DURATION}\"",
        "",
        "# Streaming",
        f"export VOICEMODE_STREAMING_ENABLED=\"{str(STREAMING_ENABLED).lower()}\"",
        f"export VOICEMODE_STREAM_CHUNK_SIZE=\"{STREAM_CHUNK_SIZE}\"",
        f"export VOICEMODE_STREAM_BUFFER_MS=\"{STREAM_BUFFER_MS}\"",
        f"export VOICEMODE_STREAM_MAX_BUFFER=\"{STREAM_MAX_BUFFER}\"",
        "",
        "# Event Logging",
        f"export VOICEMODE_EVENT_LOG_ENABLED=\"{str(EVENT_LOG_ENABLED).lower()}\"",
        f"export VOICEMODE_EVENT_LOG_DIR=\"{EVENT_LOG_DIR}\"",
        f"export VOICEMODE_EVENT_LOG_ROTATION=\"{EVENT_LOG_ROTATION}\"",
        "",
        "# API Keys (masked for security)",
        f"# export ELEVENLABS_API_KEY=\"{mask_sensitive(ELEVENLABS_API_KEY, 'api_key')}\"",
    ]

    return "\n".join(template_lines)
