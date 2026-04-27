"""Tests for STT audio artifact lifecycle handling."""

from datetime import datetime

import numpy as np

from voice_mode.artifacts import (
    AUDIO_ARTIFACT_ARCHIVE_FORMATS,
    AudioArtifactLifecycle,
    AudioArtifactStore,
    discover_audio_artifacts,
)


def test_stage_stt_upload_removes_temp_file_after_context():
    lifecycle = AudioArtifactLifecycle()

    with lifecycle.stage_stt_upload(b"upload", upload_format="wav") as upload:
        upload_path = upload.path
        assert upload_path.exists()
        assert upload_path.read_bytes() == b"upload"
        assert upload.metadata.archive_path is None

    assert not upload_path.exists()


def test_stage_stt_upload_saves_archive_and_updates_symlinks(tmp_path):
    audio_dir = tmp_path / "audio"
    symlink_calls = []

    def filename_factory(prefix, extension, conversation_id):
        return f"20260425_170300_123_{conversation_id}_{prefix}.{extension}"

    def symlink_updater(path, audio_type):
        symlink_calls.append((path, audio_type))
        type_symlink = audio_dir / "latest-STT.wav"
        latest_symlink = audio_dir / "latest.wav"
        return type_symlink, latest_symlink

    store = AudioArtifactStore(
        filename_factory=filename_factory,
        symlink_updater=symlink_updater,
        now=lambda: datetime(2026, 4, 25, 17, 3),
    )
    lifecycle = AudioArtifactLifecycle(store)
    audio_data = np.zeros(240, dtype=np.int16)

    with lifecycle.stage_stt_upload(
        b"upload",
        upload_format="mp3",
        audio_data=audio_data,
        save_audio=True,
        audio_dir=audio_dir,
        save_format="wav",
        conversation_id="abc123",
    ) as upload:
        metadata = upload.metadata
        assert metadata.upload_path.exists()
        assert metadata.archive_path == audio_dir / "2026" / "04" / "20260425_170300_123_abc123_stt.wav"
        assert metadata.archive_path.exists()
        assert metadata.audio_file == "2026/04/20260425_170300_123_abc123_stt.wav"
        assert metadata.archive_format == "wav"
        assert metadata.upload_format == "mp3"
        assert metadata.type_symlink == audio_dir / "latest-STT.wav"
        assert metadata.latest_symlink == audio_dir / "latest.wav"

    assert symlink_calls == [(metadata.archive_path, "stt")]
    assert not metadata.upload_path.exists()


def test_stage_stt_upload_can_save_compressed_archive(tmp_path):
    store = AudioArtifactStore(
        filename_factory=lambda prefix, extension, conversation_id: f"clip_{prefix}.{extension}",
        symlink_updater=lambda path, audio_type: (None, None),
        now=lambda: datetime(2026, 4, 25),
    )
    lifecycle = AudioArtifactLifecycle(store)
    audio_data = np.zeros(10, dtype=np.int16)

    with lifecycle.stage_stt_upload(
        b"upload",
        upload_format="wav",
        audio_data=audio_data,
        save_audio=True,
        audio_dir=tmp_path,
        save_format="mp3",
        conversation_id="conv",
        encode_archive=lambda data, fmt: b"encoded-" + fmt.encode(),
    ) as upload:
        assert upload.metadata.archive_path.read_bytes() == b"encoded-mp3"
        assert upload.metadata.archive_format == "mp3"


def test_discover_audio_artifacts_includes_all_archive_formats_and_layouts(tmp_path):
    flat_wav = tmp_path / "flat.wav"
    dated_mp3 = tmp_path / "2026" / "04" / "dated.mp3"
    dated_flac = tmp_path / "2026" / "05" / "dated.flac"
    for path in (flat_wav, dated_mp3, dated_flac):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

    discovered = discover_audio_artifacts(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in discovered] == [
        "2026/04/dated.mp3",
        "2026/05/dated.flac",
        "flat.wav",
    ]
    assert set(AUDIO_ARTIFACT_ARCHIVE_FORMATS) == {"wav", "mp3", "flac"}


def test_discover_audio_artifacts_skips_symlinks_duplicates_and_invalid_files(tmp_path):
    saved = tmp_path / "2026" / "04" / "clip.wav"
    duplicate = tmp_path / "duplicate.wav"
    symlink = tmp_path / "latest.wav"
    invalid = tmp_path / "notes.txt"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"audio")
    duplicate.hardlink_to(saved)
    symlink.symlink_to(saved.relative_to(tmp_path))
    invalid.write_text("not audio")

    discovered = discover_audio_artifacts(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in discovered] == [
        "2026/04/clip.wav"
    ]
