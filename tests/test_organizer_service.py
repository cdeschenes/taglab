"""Tests for app/services/organizer.py"""
from pathlib import Path

import pytest

from app.services.organizer import apply_organize, build_target_path, preview_organize
from tests.conftest import make_flac

DEFAULT_PATTERN = "{album_artist}/{album}/{track:02d} - {title}.flac"

BASE_TAGS = {
    "albumartist": "Pink Floyd",
    "album": "The Wall",
    "title": "In the Flesh",
    "tracknumber": "1",
    "date": "1979",
    "genre": "Rock",
}


# ── build_target_path ──────────────────────────────────────────────────────────

class TestBuildTargetPath:
    def test_basic_path(self, tmp_path):
        result = build_target_path(BASE_TAGS, DEFAULT_PATTERN, tmp_path)
        assert result == tmp_path / "Pink Floyd" / "The Wall" / "01 - In the Flesh.flac"

    def test_uses_albumartist_over_artist(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Various Artists", "artist": "Guest"}
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert "Various Artists" in str(result)
        assert "Guest" not in str(result)

    def test_falls_back_to_artist_when_no_albumartist(self, tmp_path):
        tags = {k: v for k, v in BASE_TAGS.items() if k != "albumartist"}
        tags["artist"] = "Fallback Artist"
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert "Fallback Artist" in str(result)

    def test_returns_none_when_album_missing(self, tmp_path):
        tags = {**BASE_TAGS}
        del tags["album"]
        assert build_target_path(tags, DEFAULT_PATTERN, tmp_path) is None

    def test_returns_none_when_title_missing(self, tmp_path):
        tags = {**BASE_TAGS}
        del tags["title"]
        assert build_target_path(tags, DEFAULT_PATTERN, tmp_path) is None

    def test_returns_none_when_all_artist_fields_missing(self, tmp_path):
        tags = {k: v for k, v in BASE_TAGS.items() if k not in ("albumartist", "artist")}
        assert build_target_path(tags, DEFAULT_PATTERN, tmp_path) is None

    def test_track_number_zero_padded(self, tmp_path):
        tags = {**BASE_TAGS, "tracknumber": "3"}
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert result.name.startswith("03 -")

    def test_track_number_fraction_stripped(self, tmp_path):
        # e.g. "1/12" format used by some taggers
        tags = {**BASE_TAGS, "tracknumber": "5/12"}
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert result.name.startswith("05 -")

    def test_sanitizes_slashes_in_tags(self, tmp_path):
        tags = {**BASE_TAGS, "album": "AC/DC Live"}
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert "/" not in result.parent.name  # slash stripped from album folder

    def test_sanitizes_colons_in_tags(self, tmp_path):
        tags = {**BASE_TAGS, "title": "Side A: Opening"}
        result = build_target_path(tags, DEFAULT_PATTERN, tmp_path)
        assert ":" not in result.name

    # ── New token tests ────────────────────────────────────────────────────────

    def test_artist_token_resolves_independently(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Pink Floyd", "artist": "Roger Waters"}
        result = build_target_path(tags, "{artist}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "Roger Waters" in str(result)
        assert "Pink Floyd" not in str(result)

    def test_artistsort_token(self, tmp_path):
        tags = {**BASE_TAGS, "artistsort": "Young, Neil"}
        result = build_target_path(tags, "{artistsort}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "Young, Neil" in str(result)

    def test_albumartistsort_token(self, tmp_path):
        tags = {**BASE_TAGS, "albumartistsort": "Floyd, Pink"}
        result = build_target_path(tags, "{albumartistsort}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "Floyd, Pink" in str(result)

    def test_label_token(self, tmp_path):
        tags = {**BASE_TAGS, "label": "Columbia"}
        result = build_target_path(tags, "{label}/{album_artist}/{track:02d} - {title}.flac", tmp_path)
        assert "Columbia" in str(result)

    def test_composer_token(self, tmp_path):
        tags = {**BASE_TAGS, "composer": "Bach"}
        result = build_target_path(tags, "{composer}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "Bach" in str(result)

    def test_key_token(self, tmp_path):
        tags = {**BASE_TAGS, "key": "Am"}
        result = build_target_path(tags, "{album_artist}/{key}/{track:02d} - {title}.flac", tmp_path)
        assert "Am" in str(result)

    def test_originalyear_from_originaldate(self, tmp_path):
        tags = {**BASE_TAGS, "originaldate": "1973-03-01"}
        result = build_target_path(tags, "{originalyear}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "1973" in str(result)

    def test_originalyear_fallback_to_originalyear_tag(self, tmp_path):
        tags = {**BASE_TAGS, "originalyear": "1979"}
        result = build_target_path(tags, "{originalyear}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "1979" in str(result)

    def test_originalyear_fallback_to_original_year_tag(self, tmp_path):
        tags = {**BASE_TAGS, "original_year": "1980"}
        result = build_target_path(tags, "{originalyear}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "1980" in str(result)

    def test_date_token_full_string(self, tmp_path):
        tags = {**BASE_TAGS, "date": "2001-09-10"}
        result = build_target_path(tags, "{album_artist}/{date}/{track:02d} - {title}.flac", tmp_path)
        assert "2001-09-10" in str(result)

    def test_date_token_not_truncated_to_4_chars(self, tmp_path):
        tags = {**BASE_TAGS, "date": "2001-09-10"}
        result = build_target_path(tags, "{date}/{album}/{track:02d} - {title}.flac", tmp_path)
        # {date} should be the full string, not just "2001"
        assert "2001-09-10" in str(result)
        assert result.parts[-3] == "2001-09-10"

    def test_album_artist_first_comma_separated(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Loscil, Lawrence English"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert "Loscil" in str(result)
        assert "Lawrence English" not in str(result)

    def test_album_artist_first_slash_separated(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Artist A / Artist B"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "Artist A"

    def test_album_artist_first_semicolon_separated(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Artist A;Artist B"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "Artist A"

    def test_album_artist_first_pipe_separated(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "loscil | Fieldhead"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "loscil"

    def test_album_artist_first_featuring(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "loscil featuring Kelly James Wyse"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "loscil"

    def test_album_artist_first_feat_dot(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "loscil feat. Kelly James Wyse"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "loscil"

    def test_album_artist_first_single_artist_unchanged(self, tmp_path):
        tags = {**BASE_TAGS, "albumartist": "Pink Floyd"}
        result = build_target_path(tags, "{album_artist_first}/{album}/{track:02d} - {title}.flac", tmp_path)
        assert result.parts[-3] == "Pink Floyd"

    def test_missing_optional_tokens_produce_empty_string(self, tmp_path):
        # Tags have no label, composer, key, originalyear, artistsort, etc.
        tags = {**BASE_TAGS}
        result = build_target_path(
            tags,
            "{album_artist}/{label}/{composer}/{key}/{originalyear}/{album}/{track:02d} - {title}.flac",
            tmp_path,
        )
        assert result is not None
        # Empty segments are empty strings, not crashes
        assert "None" not in str(result)


# ── preview_organize ───────────────────────────────────────────────────────────

class TestPreviewOrganize:
    def test_returns_preview_for_each_file(self, tmp_path):
        f = make_flac(tmp_path / "track.flac")
        target = tmp_path / "out"
        result = preview_organize(
            [f],
            {str(f): BASE_TAGS},
            DEFAULT_PATTERN,
            target,
        )
        assert len(result) == 1
        assert result[0]["source"] == str(f)
        assert result[0]["filename"] == "track.flac"
        assert result[0]["target"] is not None
        assert result[0]["error"] is None

    def test_marks_files_with_missing_tags(self, tmp_path):
        f = make_flac(tmp_path / "track.flac")
        target = tmp_path / "out"
        result = preview_organize(
            [f],
            {str(f): {"tracknumber": "1"}},  # missing album, albumartist, title
            DEFAULT_PATTERN,
            target,
        )
        assert result[0]["target"] is None
        assert result[0]["error"] is not None

    def test_conflict_when_target_already_exists(self, tmp_path):
        f = make_flac(tmp_path / "track.flac")
        out = tmp_path / "out"
        # Run once to determine the target path
        result = preview_organize([f], {str(f): BASE_TAGS}, DEFAULT_PATTERN, out)
        target_path = result[0]["target"]
        # Create a different file at the target location to simulate a conflict
        from pathlib import Path
        p = Path(target_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"existing")
        # Now preview should detect the conflict
        result2 = preview_organize([f], {str(f): BASE_TAGS}, DEFAULT_PATTERN, out)
        assert result2[0]["conflict"] is True
        assert result2[0]["target"] == target_path
        assert result2[0]["error"] is None

    def test_no_conflict_when_target_does_not_exist(self, tmp_path):
        f = make_flac(tmp_path / "track.flac")
        result = preview_organize([f], {str(f): BASE_TAGS}, DEFAULT_PATTERN, tmp_path / "out")
        assert result[0]["conflict"] is False


# ── apply_organize ─────────────────────────────────────────────────────────────

class TestApplyOrganize:
    def test_moves_file(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        results = apply_organize([{"source": str(src), "target": str(dst)}])
        assert results[0]["ok"] is True
        assert not src.exists()
        assert dst.exists()

    def test_creates_parent_directories(self, tmp_path):
        src = make_flac(tmp_path / "track.flac")
        dst = tmp_path / "deep" / "nested" / "path" / "file.flac"
        apply_organize([{"source": str(src), "target": str(dst)}])
        assert dst.exists()

    def test_no_op_when_source_equals_target(self, tmp_path):
        src = make_flac(tmp_path / "track.flac")
        results = apply_organize([{"source": str(src), "target": str(src)}])
        assert results[0]["ok"] is True
        assert src.exists()

    def test_error_when_source_missing(self, tmp_path):
        src = tmp_path / "nonexistent.flac"
        dst = tmp_path / "out.flac"
        results = apply_organize([{"source": str(src), "target": str(dst)}])
        assert results[0]["ok"] is False
        assert "not found" in results[0]["error"].lower()

    def test_error_when_target_already_exists(self, tmp_path):
        src = make_flac(tmp_path / "src.flac")
        dst = make_flac(tmp_path / "dst.flac")  # already exists, different file
        results = apply_organize([{"source": str(src), "target": str(dst)}])
        assert results[0]["ok"] is False

    def test_multiple_moves(self, tmp_path):
        srcs = [make_flac(tmp_path / f"track{i}.flac") for i in range(3)]
        moves = [
            {"source": str(s), "target": str(tmp_path / "out" / s.name)}
            for s in srcs
        ]
        results = apply_organize(moves)
        assert all(r["ok"] for r in results)
        assert all((tmp_path / "out" / s.name).exists() for s in srcs)

    def test_moves_lrc_file_alongside_flac(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        lrc = tmp_path / "src" / "track.lrc"
        lrc.write_text("[00:00.00] lyrics")
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        apply_organize([{"source": str(src), "target": str(dst)}])
        assert (dst.parent / "track.lrc").exists()

    def test_moves_cover_image_alongside_flac(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        cover = tmp_path / "src" / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff")  # minimal JPEG header
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        apply_organize([{"source": str(src), "target": str(dst)}])
        assert (dst.parent / "cover.jpg").exists()

    def test_does_not_move_trash_files(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        trash = tmp_path / "src" / "._cover.jpg"
        trash.write_bytes(b"trash")
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        apply_organize([{"source": str(src), "target": str(dst)}], cleanup_patterns=["._*"])
        assert not (dst.parent / "._cover.jpg").exists()

    def test_does_not_overwrite_existing_companion(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        lrc_src = tmp_path / "src" / "track.lrc"
        lrc_src.write_text("source lyrics")
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        dst.parent.mkdir(parents=True, exist_ok=True)
        lrc_dst = dst.parent / "track.lrc"
        lrc_dst.write_text("existing lyrics")
        apply_organize([{"source": str(src), "target": str(dst)}])
        assert lrc_dst.read_text() == "existing lyrics"

    def test_deletes_source_companion_when_destination_exists(self, tmp_path):
        src = make_flac(tmp_path / "src" / "track.flac")
        lrc_src = tmp_path / "src" / "track.lrc"
        lrc_src.write_text("source lyrics")
        dst = tmp_path / "dst" / "Artist" / "Album" / "01 - Track.flac"
        dst.parent.mkdir(parents=True, exist_ok=True)
        lrc_dst = dst.parent / "track.lrc"
        lrc_dst.write_text("existing lyrics")
        apply_organize([{"source": str(src), "target": str(dst)}])
        assert not lrc_src.exists()
