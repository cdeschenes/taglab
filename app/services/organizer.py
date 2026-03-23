"""File organizer: rename/move FLAC files according to their tags."""
from __future__ import annotations

import fnmatch
import re
import shutil
from pathlib import Path
from typing import Optional


def _sanitize(value: str) -> str:
    """Strip filesystem-unsafe characters from a tag value."""
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"_+", "_", value)
    return value[:200]  # cap segment length


def _first_value(value: str) -> str:
    """Return the first component of a multi-artist string.

    Splits on common delimiters: ' / ', '|', ';', ' & ', ', ', ' feat. ', ' featuring '
    Returns the whole string if no delimiter is found.
    """
    parts = re.split(r"\s*/\s*|\s*\|\s*|;\s*|\s+&\s+|,\s+|\s+feat(?:uring)?\.?\s+", value, flags=re.IGNORECASE)
    return parts[0].strip()


def build_target_path(
    tags: dict[str, str],
    pattern: str,
    organize_target: Path,
) -> Optional[Path]:
    """
    Resolve the destination path for a file given its tags and the pattern.
    Returns None if required tags are missing.
    """
    album_artist = tags.get("albumartist") or tags.get("artist") or ""
    album = tags.get("album") or ""
    title = tags.get("title") or ""
    track_raw = tags.get("tracknumber", "0")
    disc_raw = tags.get("discnumber", "1")
    date_full = tags.get("date") or tags.get("year") or ""
    genre = tags.get("genre") or ""
    artist = tags.get("artist") or ""
    artistsort = tags.get("artistsort") or ""
    albumartistsort = tags.get("albumartistsort") or ""
    label = tags.get("label") or ""
    composer = tags.get("composer") or ""
    key = tags.get("key") or ""
    original_date = (
        tags.get("originaldate") or tags.get("originalyear") or tags.get("original_year") or ""
    )

    album_artist_first = _first_value(album_artist) if album_artist else ""

    if not (album_artist and album and title):
        return None

    try:
        track = int(re.match(r"\d+", track_raw).group()) if track_raw else 0  # type: ignore[union-attr]
        disc = int(re.match(r"\d+", disc_raw).group()) if disc_raw else 1  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        track, disc = 0, 1

    try:
        rel_path = pattern.format(
            album_artist=_sanitize(album_artist),
            album_artist_first=_sanitize(album_artist_first),
            artist=_sanitize(artist),
            artistsort=_sanitize(artistsort),
            albumartistsort=_sanitize(albumartistsort),
            album=_sanitize(album),
            title=_sanitize(title),
            track=track,
            disc=disc,
            year=_sanitize(date_full[:4]) if date_full else "",
            date=_sanitize(date_full),
            genre=_sanitize(genre),
            label=_sanitize(label),
            composer=_sanitize(composer),
            key=_sanitize(key),
            originalyear=_sanitize(original_date[:4]) if original_date else "",
        )
    except (KeyError, ValueError):
        return None

    return organize_target / rel_path


def preview_organize(
    files: list[Path],
    tags_by_path: dict[str, dict],
    pattern: str,
    organize_target: Path,
) -> list[dict]:
    """
    Return a preview of what moves would occur, without touching the filesystem.
    """
    previews = []
    for f in files:
        tags = tags_by_path.get(str(f), {})
        target = build_target_path(tags, pattern, organize_target)
        conflict = (
            target is not None
            and target.exists()
            and target.resolve() != f.resolve()
        )
        previews.append({
            "source": str(f),
            "filename": f.name,
            "target": str(target) if target else None,
            "error": "Missing required tags (albumartist, album, title)" if not target else None,
            "conflict": conflict,
        })
    return previews


def apply_organize(
    moves: list[dict],
    cleanup_patterns: list[str] | None = None,
) -> list[dict]:
    """
    Execute the file moves from a confirmed preview list.
    Each item: {"source": str, "target": str}
    Also moves all companion files (lyrics, covers, booklets, etc.) alongside the FLACs
    and removes empty source dirs.
    Returns results with "ok" or "error" per file.
    """
    results = []
    src_to_tgt_dir: dict[Path, Path] = {}

    for move in moves:
        source = Path(move["source"])
        target = Path(move["target"])

        if not source.exists():
            results.append({"source": str(source), "ok": False, "error": "Source not found"})
            continue
        if target.exists() and target.resolve() != source.resolve():
            results.append({"source": str(source), "ok": False, "error": f"Target already exists: {target}"})
            continue
        if target.resolve() == source.resolve():
            results.append({"source": str(source), "ok": True, "note": "Already in place"})
            src_to_tgt_dir[source.parent] = target.parent
            continue

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            results.append({"source": str(source), "target": str(target), "ok": True})
            src_to_tgt_dir[source.parent] = target.parent
        except OSError as e:
            results.append({"source": str(source), "ok": False, "error": str(e)})

    def _is_trash(name: str) -> bool:
        return cleanup_patterns is not None and any(
            fnmatch.fnmatch(name, pat) for pat in cleanup_patterns
        )

    # Move all companion files (except trash) from album-level dirs; collect artist dirs
    artist_dir_map: dict[Path, Path] = {}
    for src_dir, tgt_dir in src_to_tgt_dir.items():
        if src_dir == tgt_dir or not src_dir.exists():
            continue
        for companion in src_dir.iterdir():
            if not companion.is_file():
                continue
            if _is_trash(companion.name):
                continue
            dest = tgt_dir / companion.name
            if dest.exists():
                try:
                    companion.unlink()
                except OSError:
                    pass
            else:
                try:
                    shutil.move(str(companion), str(dest))
                except OSError:
                    pass
        artist_dir_map[src_dir.parent] = tgt_dir.parent

    # Move all companion files (except trash) from artist-level dirs
    for src_artist_dir, tgt_artist_dir in artist_dir_map.items():
        if src_artist_dir == tgt_artist_dir or not src_artist_dir.exists():
            continue
        for companion in src_artist_dir.iterdir():
            if not companion.is_file():
                continue
            if _is_trash(companion.name):
                continue
            dest = tgt_artist_dir / companion.name
            if dest.exists():
                try:
                    companion.unlink()
                except OSError:
                    pass
            else:
                try:
                    tgt_artist_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(companion), str(dest))
                except OSError:
                    pass

    # Delete remaining trash files so dirs can be rmdir'd
    if cleanup_patterns:
        for src_dir in list(src_to_tgt_dir) + list(artist_dir_map):
            if not src_dir.exists():
                continue
            for f in list(src_dir.iterdir()):
                if f.is_file() and _is_trash(f.name):
                    try:
                        f.unlink()
                    except OSError:
                        pass

    # Remove empty source album dirs, then empty artist dirs
    for src_dir in src_to_tgt_dir:
        try:
            src_dir.rmdir()
        except OSError:
            pass
    for src_artist_dir in artist_dir_map:
        try:
            src_artist_dir.rmdir()
        except OSError:
            pass

    return results
