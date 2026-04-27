"""Tests for audio MCP resources."""

from pathlib import Path

import pytest

from voice_mode.resources import audio_files


def test_resolve_audio_file_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    assert audio_files._resolve_audio_file("../secret.wav") is None


def test_resolve_audio_file_returns_contained_path(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    resolved = audio_files._resolve_audio_file("clip.wav")
    assert resolved == (tmp_path / "clip.wav").resolve()


def test_resolve_audio_file_allows_year_month_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    resolved = audio_files._resolve_audio_file("2026/04/clip.wav")
    assert resolved == (tmp_path / "2026" / "04" / "clip.wav").resolve()


@pytest.mark.asyncio
async def test_list_audio_files_includes_supported_archive_formats(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "SAVE_AUDIO", True)
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    files = [
        tmp_path / "2026" / "04" / "clip.wav",
        tmp_path / "2026" / "04" / "clip.mp3",
        tmp_path / "flat.flac",
    ]
    for saved in files:
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(b"audio")

    result = await audio_files.list_audio_files()

    assert "2026/04/clip.wav" in result
    assert "2026/04/clip.mp3" in result
    assert "flat.flac" in result


@pytest.mark.asyncio
async def test_list_audio_files_excludes_symlinks_and_invalid_files(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "SAVE_AUDIO", True)
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    saved = tmp_path / "2026" / "04" / "clip.wav"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"audio")
    (tmp_path / "latest.wav").symlink_to(saved.relative_to(tmp_path))
    (tmp_path / "notes.txt").write_text("not audio")

    result = await audio_files.list_audio_files()

    assert "2026/04/clip.wav" in result
    assert "latest.wav" not in result
    assert "notes.txt" not in result


@pytest.mark.asyncio
async def test_get_audio_file_returns_nested_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_files, "SAVE_AUDIO", True)
    monkeypatch.setattr(audio_files, "AUDIO_DIR", str(tmp_path))
    saved = tmp_path / "2026" / "04" / "clip.wav"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"audio")

    result = await audio_files.get_audio_file("2026/04/clip.wav")

    assert "Audio file: 2026/04/clip.wav" in result
    assert "Path: 2026/04/clip.wav" in result
