"""Resources for saved audio files."""

import os
from pathlib import Path
from typing import Optional
from voice_mode.server import mcp
from voice_mode.artifacts import discover_audio_artifacts
from voice_mode.config import SAVE_AUDIO, AUDIO_DIR


def _resolve_audio_file(filename: str) -> Path | None:
    """Resolve an audio file name while enforcing AUDIO_DIR containment."""
    requested = Path(filename)
    if requested.is_absolute() or ".." in requested.parts:
        return None
    audio_dir = Path(AUDIO_DIR).resolve()
    file_path = (audio_dir / requested).resolve()
    try:
        file_path.relative_to(audio_dir)
    except ValueError:
        return None
    return file_path


@mcp.resource("audio://files/{directory}")
async def list_audio_files(directory: str = "all") -> Optional[str]:
    """List saved audio files if audio saving is enabled.
    
    Returns a list of audio files in the audio directory with their
    creation times and sizes.
    """
    if not SAVE_AUDIO:
        return "Audio saving is not enabled. Set VOICE_MODE_SAVE_AUDIO=1 to enable."
    
    if not os.path.exists(AUDIO_DIR):
        return "No audio files found - directory does not exist."
    
    audio_files = []
    audio_dir = Path(AUDIO_DIR)
    for file in discover_audio_artifacts(audio_dir):
        stat = file.stat()
        size_kb = stat.st_size / 1024
        display_name = file.relative_to(audio_dir).as_posix()
        audio_files.append(f"- {display_name} ({size_kb:.1f} KB)")
    
    if not audio_files:
        return "No audio files found."
    
    return f"Saved audio files in {AUDIO_DIR}:\n" + "\n".join(audio_files)

@mcp.resource("audio://file/{filename}")
async def get_audio_file(filename: str) -> Optional[str]:
    """Get metadata about a specific audio file.
    
    Args:
        filename: Name of the audio file to get metadata for
        
    Returns:
        File metadata including size and creation time.
    """
    if not SAVE_AUDIO:
        return "Audio saving is not enabled. Set VOICE_MODE_SAVE_AUDIO=1 to enable."
    file_path = _resolve_audio_file(filename)
    if file_path is None or not file_path.exists():
        return "Audio file not found."

    stat = file_path.stat()
    size_kb = stat.st_size / 1024
    
    return f"""Audio file: {filename}
Size: {size_kb:.1f} KB
Created: {stat.st_ctime}
Path: {file_path.relative_to(Path(AUDIO_DIR).resolve()).as_posix()}"""