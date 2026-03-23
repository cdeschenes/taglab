"""Tests for app/services/flac.py"""
from pathlib import Path

import pytest
from fastapi import HTTPException
from mutagen.flac import FLAC

from app.services.flac import (
    build_preview,
    get_cover_bytes,
    list_flac_files,
    read_album,
    read_tags,
    remove_cover,
    validate_media_path,
    write_cover,
    write_tags,
)
from tests.conftest import make_flac


# ── validate_media_path ────────────────────────────────────────────────────────

class TestValidateMediaPath:
    def test_relative_path_resolves(self, tmp_path):
        (tmp_path / "artist").mkdir()
        result = validate_media_path("artist", tmp_path)
        assert result == tmp_path / "artist"

    def test_absolute_path_within_root(self, tmp_path):
        sub = tmp_path / "artist"
        sub.mkdir()
        result = validate_media_path(str(sub), tmp_path)
        assert result == sub

    def test_path_traversal_raises_403(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            validate_media_path("../outside", tmp_path)
        assert exc.value.status_code == 403

    def test_absolute_traversal_raises_403(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            validate_media_path("/etc/passwd", tmp_path)
        assert exc.value.status_code == 403

    def test_missing_path_raises_404(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            validate_media_path("nonexistent", tmp_path)
        assert exc.value.status_code == 404


# ── read_tags ──────────────────────────────────────────────────────────────────

class TestReadTags:
    def test_empty_flac_has_no_music_tags(self, tmp_flac):
        result = read_tags(tmp_flac)
        # ffmpeg may add an ENCODER VorbisComment; music tags should be absent
        assert result["tags"].get("title") is None
        assert result["tags"].get("artist") is None
        assert result["tags"].get("album") is None
        assert result["has_cover"] is False

    def test_reads_written_tags(self, tagged_flac):
        result = read_tags(tagged_flac)
        assert result["tags"]["title"] == "Song"
        assert result["tags"]["artist"] == "Artist"
        assert result["tags"]["album"] == "Record"
        assert result["tags"]["tracknumber"] == "1"
        assert result["tags"]["date"] == "2024"

    def test_includes_audio_info(self, tmp_flac):
        result = read_tags(tmp_flac)
        info = result["info"]
        assert info["sample_rate"] > 0
        assert info["channels"] >= 1
        assert info["bits_per_sample"] > 0
        assert info["length"] > 0

    def test_filename_and_path_returned(self, tmp_flac):
        result = read_tags(tmp_flac)
        assert result["filename"] == tmp_flac.name
        assert result["path"] == str(tmp_flac)


# ── write_tags ─────────────────────────────────────────────────────────────────

class TestWriteTags:
    def test_writes_and_reads_back(self, tmp_flac):
        write_tags(tmp_flac, {"title": "Hello", "artist": "World"})
        result = read_tags(tmp_flac)
        assert result["tags"]["title"] == "Hello"
        assert result["tags"]["artist"] == "World"

    def test_empty_string_clears_tag(self, tagged_flac):
        write_tags(tagged_flac, {"genre": ""})
        result = read_tags(tagged_flac)
        assert "genre" not in result["tags"]

    def test_none_value_clears_tag(self, tagged_flac):
        write_tags(tagged_flac, {"genre": None})
        result = read_tags(tagged_flac)
        assert "genre" not in result["tags"]

    def test_overwrites_existing_tag(self, tagged_flac):
        write_tags(tagged_flac, {"title": "New Title"})
        result = read_tags(tagged_flac)
        assert result["tags"]["title"] == "New Title"

    def test_preserves_unrelated_tags(self, tagged_flac):
        write_tags(tagged_flac, {"title": "Changed"})
        result = read_tags(tagged_flac)
        assert result["tags"]["artist"] == "Artist"  # untouched


# ── cover art ─────────────────────────────────────────────────────────────────

class TestCoverArt:
    JPEG_HEADER = b"\xff\xd8\xff"  # minimal JPEG magic bytes

    def _fake_jpeg(self) -> bytes:
        # Minimal 1x1 white JPEG (53 bytes)
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
            b"\xff\xd9"
        )

    def test_write_and_read_cover(self, tmp_flac):
        data = self._fake_jpeg()
        write_cover(tmp_flac, data, "image/jpeg")
        result = read_tags(tmp_flac)
        assert result["has_cover"] is True

    def test_get_cover_bytes(self, tmp_flac):
        data = self._fake_jpeg()
        write_cover(tmp_flac, data, "image/jpeg")
        out_data, out_mime = get_cover_bytes(tmp_flac)
        assert out_data == data
        assert out_mime == "image/jpeg"

    def test_remove_cover(self, tmp_flac):
        write_cover(tmp_flac, self._fake_jpeg(), "image/jpeg")
        remove_cover(tmp_flac)
        result = read_tags(tmp_flac)
        assert result["has_cover"] is False

    def test_get_cover_raises_404_when_none(self, tmp_flac):
        with pytest.raises(HTTPException) as exc:
            get_cover_bytes(tmp_flac)
        assert exc.value.status_code == 404


# ── list_flac_files ────────────────────────────────────────────────────────────

class TestListFlacFiles:
    def test_returns_only_flac(self, tmp_path):
        make_flac(tmp_path / "a.flac")
        (tmp_path / "cover.jpg").touch()
        (tmp_path / "info.txt").touch()
        result = list_flac_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "a.flac"

    def test_sorted_alphabetically(self, tmp_path):
        make_flac(tmp_path / "03.flac")
        make_flac(tmp_path / "01.flac")
        make_flac(tmp_path / "02.flac")
        result = list_flac_files(tmp_path)
        assert [f.name for f in result] == ["01.flac", "02.flac", "03.flac"]

    def test_empty_folder(self, tmp_path):
        assert list_flac_files(tmp_path) == []


# ── read_album ─────────────────────────────────────────────────────────────────

class TestReadAlbum:
    def test_returns_all_tracks(self, album_dir):
        result = read_album(album_dir)
        assert len(result["tracks"]) == 2

    def test_common_tags_identified(self, album_dir):
        result = read_album(album_dir)
        assert result["common_tags"]["album"] == "Test Album"
        assert result["common_tags"]["albumartist"] == "Test Artist"
        assert result["common_tags"]["date"] == "2024"

    def test_mixed_tags_identified(self, album_dir):
        result = read_album(album_dir)
        # tracknumber and title differ per track
        assert "tracknumber" in result["mixed_tags"]
        assert "title" in result["mixed_tags"]

    def test_empty_folder_returns_empty(self, tmp_path):
        result = read_album(tmp_path)
        assert result["tracks"] == []
        assert result["common_tags"] == {}


# ── build_preview ──────────────────────────────────────────────────────────────

class TestBuildPreview:
    def test_detects_changes(self, album_dir):
        previews = build_preview(
            str(album_dir),
            shared_tags={"genre": "Jazz"},
            track_overrides=[],
        )
        # Both tracks should show genre changing from "Rock" to "Jazz"
        for p in previews:
            genre_change = next((c for c in p["changes"] if c["field"] == "genre"), None)
            assert genre_change is not None
            assert genre_change["old"] == "Rock"
            assert genre_change["new"] == "Jazz"

    def test_no_changes_when_identical(self, album_dir):
        previews = build_preview(
            str(album_dir),
            shared_tags={"album": "Test Album"},
            track_overrides=[],
        )
        for p in previews:
            album_change = next((c for c in p["changes"] if c["field"] == "album"), None)
            assert album_change is None

    def test_track_override_applied(self, album_dir):
        tracks = list_flac_files(album_dir)
        first = str(tracks[0])
        previews = build_preview(
            str(album_dir),
            shared_tags={},
            track_overrides=[{"path": first, "tags": {"title": "Override"}}],
        )
        first_preview = next(p for p in previews if p["path"] == first)
        title_change = next(c for c in first_preview["changes"] if c["field"] == "title")
        assert title_change["new"] == "Override"
