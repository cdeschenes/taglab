"""FLAC metadata read/write via Mutagen."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from mutagen.flac import FLAC, Picture

# Tags shown as dedicated fields in the UI (order matters for display)
STANDARD_TAGS: list[str] = [
    "title",
    "artist",
    "albumartist",
    "album",
    "date",
    "tracknumber",
    "discnumber",
    "genre",
    "composer",
    "label",
    "country",
    "isrc",
    "barcode",
    "comment",
    "bpm",
    "key",
    "lyrics",
    "mood",
    "performer",
    "musicbrainz_albumid",
    "musicbrainz_albumartistid",
    "musicbrainz_artistid",
    "musicbrainz_trackid",
    "musicbrainz_releasegroupid",
    "musicbrainz_releasetrackid",
    "replaygain_track_gain",
    "replaygain_track_peak",
    "replaygain_album_gain",
    "replaygain_album_peak",
    "replaygain_reference_loudness",
]


def validate_media_path(path: str, media_root: Path) -> Path:
    """
    Resolve and validate that path stays inside media_root.
    Accepts both absolute paths (e.g. /media/Artist/Album/file.flac)
    and paths relative to media_root (e.g. Artist/Album/file.flac).
    """
    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (media_root / path).resolve()

    if not resolved.is_relative_to(media_root.resolve()):
        raise HTTPException(status_code=403, detail="Path outside media directory")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")
    return resolved


def read_tags(path: Path) -> dict:
    audio = FLAC(str(path))
    tags: dict[str, str] = {}
    if audio.tags:
        for key, values in audio.tags.as_dict().items():
            tags[key.lower()] = values[0] if len(values) == 1 else "; ".join(values)

    has_cover = any(pic.type == 3 for pic in audio.pictures)
    has_lrc = path.with_suffix(".lrc").exists()
    has_lyrics_tag = bool(tags.get("lyrics"))

    return {
        "path": str(path),
        "filename": path.name,
        "tags": tags,
        "has_cover": has_cover,
        "has_lrc": has_lrc,
        "has_lyrics_tag": has_lyrics_tag,
        "info": {
            "length": round(audio.info.length, 1),
            "sample_rate": audio.info.sample_rate,
            "bits_per_sample": audio.info.bits_per_sample,
            "channels": audio.info.channels,
        },
    }


def write_tags(path: Path, tags: dict[str, str]) -> None:
    """Write/clear tags. Pass empty string to remove a tag."""
    audio = FLAC(str(path))
    for key, value in tags.items():
        k = key.lower()
        if value is None or str(value).strip() == "":
            if k in audio:
                del audio[k]
        else:
            audio[k] = [str(value)]
    audio.save()


def write_cover(path: Path, image_data: bytes, mime_type: str) -> None:
    import io
    from PIL import Image as _Image
    audio = FLAC(str(path))
    audio.clear_pictures()
    pic = Picture()
    pic.type = 3
    pic.mime = mime_type
    pic.data = image_data
    try:
        img = _Image.open(io.BytesIO(image_data))
        pic.width = img.width
        pic.height = img.height
    except Exception:
        pass
    audio.add_picture(pic)
    audio.save()


def remove_cover(path: Path) -> None:
    audio = FLAC(str(path))
    audio.clear_pictures()
    audio.save()


def get_cover_bytes(path: Path) -> tuple[bytes, str]:
    audio = FLAC(str(path))
    for pic in audio.pictures:
        if pic.type == 3:
            return pic.data, pic.mime
    raise HTTPException(status_code=404, detail="No cover art")


def list_flac_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".flac")


def _compute_album_stats(tracks: list[dict], flac_files: list[Path]) -> dict:
    from collections import Counter

    info = tracks[0]["info"]
    total_secs = sum(t["info"]["length"] for t in tracks)
    mins, secs = divmod(int(total_secs), 60)
    total_bytes = sum(f.stat().st_size for f in flac_files)
    sr = info["sample_rate"]
    sr_str = f"{sr // 1000} kHz" if sr % 1000 == 0 else f"{sr / 1000:.1f} kHz"
    has_rg = any(t["tags"].get("replaygain_album_gain") for t in tracks)
    has_lyrics = all(t.get("has_lyrics_tag") or t.get("has_lrc", False) for t in tracks)

    # Quality analysis
    specs = [
        (t["info"]["bits_per_sample"], t["info"]["sample_rate"], t["info"]["channels"])
        for t in tracks
    ]
    unique_specs = set(specs)
    uniform = len(unique_specs) == 1
    bits0, sr0, ch0 = specs[0]

    if not uniform:
        tier = "mixed"
        counts = Counter(specs)
        breakdown = [
            {
                "bits": b,
                "sample_rate": f"{r // 1000} kHz" if r % 1000 == 0 else f"{r / 1000:.1f} kHz",
                "channels": "Mono" if c == 1 else "Stereo",
                "count": n,
            }
            for (b, r, c), n in sorted(counts.items(), reverse=True)
        ]
    else:
        breakdown = []
        if bits0 >= 24:
            tier = "hires"
        elif bits0 == 16 and sr0 == 44100:
            tier = "cd"
        else:
            tier = "standard"

    return {
        "bits": info["bits_per_sample"],
        "sample_rate": sr_str,
        "channels": "Mono" if info["channels"] == 1 else "Stereo",
        "duration": f"{mins}:{secs:02d}",
        "size_mb": round(total_bytes / 1024 / 1024, 1),
        "track_count": len(tracks),
        "has_replaygain": has_rg,
        "has_lyrics": has_lyrics,
        "quality": {
            "uniform": uniform,
            "tier": tier,
            "breakdown": breakdown,
        },
    }


def build_album_dict(folder: Path, tracks: list[dict]) -> dict:
    """Build the read_album() return dict from an already-loaded list of track dicts."""
    if not tracks:
        return {
            "path": str(folder),
            "name": folder.name,
            "tracks": [],
            "common_tags": {},
            "mixed_tags": {},
            "stats": None,
        }

    all_keys: set[str] = set()
    for t in tracks:
        all_keys.update(t["tags"].keys())

    common: dict[str, str] = {}
    mixed: dict[str, list[str]] = {}
    for key in sorted(all_keys):
        values = [t["tags"].get(key, "") for t in tracks]
        if len(set(values)) == 1:
            common[key] = values[0]
        else:
            mixed[key] = values

    flac_files = [Path(t["path"]) for t in tracks]
    return {
        "path": str(folder),
        "name": folder.name,
        "tracks": tracks,
        "common_tags": common,
        "mixed_tags": mixed,
        "stats": _compute_album_stats(tracks, flac_files),
    }


def read_album(folder: Path) -> dict:
    flac_files = list_flac_files(folder)
    tracks = [read_tags(f) for f in flac_files]
    return build_album_dict(folder, tracks)


def build_preview(
    folder_path: str,
    shared_tags: dict[str, str],
    track_overrides: list[dict],
) -> list[dict]:
    """
    Return a per-file diff of what would change without writing anything.
    track_overrides: [{"path": "...", "tags": {...}}, ...]
    """
    overrides_by_path = {t["path"]: t["tags"] for t in track_overrides}
    previews = []

    for f in list_flac_files(Path(folder_path)):
        current = read_tags(f)["tags"]
        proposed = {**current, **shared_tags}
        if str(f) in overrides_by_path:
            proposed.update(overrides_by_path[str(f)])

        changes = []
        all_keys = set(current) | set(proposed)
        for key in sorted(all_keys):
            old = current.get(key, "")
            new = proposed.get(key, "")
            if old != new:
                changes.append({"field": key, "old": old, "new": new})

        previews.append({
            "path": str(f),
            "filename": f.name,
            "changes": changes,
        })

    return previews
