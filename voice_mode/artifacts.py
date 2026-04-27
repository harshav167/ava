"""Audio artifact lifecycle helpers for VoiceMode."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from scipy.io.wavfile import write

from voice_mode.config import SAMPLE_RATE, SUPPORTED_SAVE_FORMATS
from voice_mode.core import get_debug_filename
from voice_mode.utils import update_latest_symlinks

logger = logging.getLogger("voicemode")


@dataclass(frozen=True)
class AudioArtifactMetadata:
    """Paths and formats produced while preparing one STT upload."""

    upload_path: Path
    upload_format: str
    upload_size_bytes: int
    archive_path: Optional[Path] = None
    archive_format: Optional[str] = None
    audio_root: Optional[Path] = None
    type_symlink: Optional[Path] = None
    latest_symlink: Optional[Path] = None

    @property
    def audio_file(self) -> Optional[str]:
        """Return the resource-compatible saved-audio path."""
        if self.archive_path is None:
            return None
        if self.audio_root is None:
            return self.archive_path.name
        try:
            return self.archive_path.relative_to(self.audio_root).as_posix()
        except ValueError:
            return self.archive_path.name


AUDIO_ARTIFACT_ARCHIVE_FORMATS = tuple(SUPPORTED_SAVE_FORMATS)


def _archive_suffixes(archive_formats: Iterable[str] | None = None) -> tuple[str, ...]:
    formats = archive_formats or AUDIO_ARTIFACT_ARCHIVE_FORMATS
    return tuple(f".{format_name.lstrip('.').lower()}" for format_name in formats)


def discover_audio_artifacts(
    audio_root: Path | str,
    *,
    archive_formats: Iterable[str] | None = None,
) -> list[Path]:
    """Return saved audio artifact files under an artifact root.

    Discovery is intentionally shared by MCP resources and artifact tests so archive
    layout and format support stays aligned with artifact lifecycle behavior.
    """
    root = Path(audio_root)
    if not root.exists():
        return []

    suffixes = _archive_suffixes(archive_formats)
    discovered: list[Path] = []
    seen: set[tuple[int, int]] = set()
    candidates = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())

    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        discovered.append(path)

    return discovered


class StagedAudioUpload:
    """Context manager for a temporary upload file plus artifact metadata."""

    def __init__(self, path: Path, metadata: AudioArtifactMetadata):
        self.path = path
        self.metadata = metadata

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def open(self):
        """Open the staged upload for provider APIs that require a file object."""
        return open(self.path, "rb")

    def cleanup(self) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("Failed to clean up staged STT upload: %s", self.path, exc_info=True)


class AudioArtifactStore:
    """Local filesystem store for STT audio artifacts."""

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        filename_factory: Callable[[str, str, Optional[str]], str] = get_debug_filename,
        symlink_updater: Callable[[Path, str], tuple[Optional[Path], Optional[Path]]] = update_latest_symlinks,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.sample_rate = sample_rate
        self.filename_factory = filename_factory
        self.symlink_updater = symlink_updater
        self.now = now

    def stage_stt_upload(
        self,
        upload_audio: bytes,
        *,
        upload_format: str,
        audio_data: Optional[np.ndarray] = None,
        save_audio: bool = False,
        audio_dir: Optional[Path | str] = None,
        save_format: str = "wav",
        conversation_id: Optional[str] = None,
        encode_archive: Optional[Callable[[np.ndarray, str], bytes]] = None,
    ) -> StagedAudioUpload:
        archive_path = None
        archive_root = Path(audio_dir) if audio_dir else None
        type_symlink = None
        latest_symlink = None

        if save_audio and audio_dir and audio_data is not None:
            archive_path = self.save_stt_archive(
                audio_data,
                audio_dir=audio_dir,
                save_format=save_format,
                conversation_id=conversation_id,
                encode_archive=encode_archive,
            )
            type_symlink, latest_symlink = self.symlink_updater(archive_path, "stt")

        upload_path = self._write_temp_upload(upload_audio, upload_format)
        metadata = AudioArtifactMetadata(
            upload_path=upload_path,
            upload_format=upload_format,
            upload_size_bytes=len(upload_audio),
            archive_path=archive_path,
            archive_format=save_format if archive_path else None,
            audio_root=archive_root,
            type_symlink=type_symlink,
            latest_symlink=latest_symlink,
        )
        return StagedAudioUpload(upload_path, metadata)

    def save_stt_archive(
        self,
        audio_data: np.ndarray,
        *,
        audio_dir: Path | str,
        save_format: str,
        conversation_id: Optional[str],
        encode_archive: Optional[Callable[[np.ndarray, str], bytes]] = None,
    ) -> Path:
        now = self.now()
        month_dir = Path(audio_dir) / str(now.year) / f"{now.month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)

        filename = self.filename_factory("stt", save_format, conversation_id)
        archive_path = month_dir / filename

        if save_format == "wav":
            write(str(archive_path), self.sample_rate, audio_data)
        else:
            if encode_archive is None:
                raise ValueError("encode_archive is required for non-wav STT archives")
            archive_path.write_bytes(encode_archive(audio_data, save_format))

        logger.info("STT audio saved to: %s (format: %s)", archive_path, save_format)
        return archive_path

    def _write_temp_upload(self, upload_audio: bytes, upload_format: str) -> Path:
        extension = upload_format if upload_format in {"mp3", "wav", "flac", "m4a", "ogg"} else "mp3"
        tmp_file = tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=False)
        tmp_path = Path(tmp_file.name)
        try:
            tmp_file.write(upload_audio)
            tmp_file.flush()
            tmp_file.close()
        except Exception:
            tmp_file.close()
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
        return tmp_path


class AudioArtifactLifecycle:
    """Coordinates STT upload staging, archival save, and latest symlinks."""

    def __init__(self, store: Optional[AudioArtifactStore] = None):
        self.store = store or AudioArtifactStore()

    def stage_stt_upload(self, *args, **kwargs) -> StagedAudioUpload:
        return self.store.stage_stt_upload(*args, **kwargs)
