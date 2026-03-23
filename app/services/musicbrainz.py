"""MusicBrainz lookup via musicbrainzngs."""
from __future__ import annotations

from typing import Optional

import musicbrainzngs

musicbrainzngs.set_useragent(
    "TagLab", "0.1.0", "https://github.com/cdeschenes/taglab"
)


def search_releases(artist: str, album: str, limit: int = 10) -> list[dict]:
    """Search for releases matching artist + album name."""
    try:
        result = musicbrainzngs.search_releases(
            release=album,
            artist=artist,
            limit=limit,
        )
    except musicbrainzngs.WebServiceError as e:
        raise RuntimeError(f"MusicBrainz search failed: {e}") from e

    releases = []
    for r in result.get("release-list", []):
        artist_credit = r.get("artist-credit", [])
        mb_artist = (
            artist_credit[0]["artist"]["name"]
            if artist_credit and isinstance(artist_credit[0], dict)
            else ""
        )
        medium_list = r.get("medium-list", [])
        releases.append({
            "mbid": r["id"],
            "title": r.get("title", ""),
            "artist": mb_artist,
            "date": r.get("date", ""),
            "country": r.get("country", ""),
            "label": _extract_label(r),
            "track_count": medium_list[0].get("track-count", "?") if medium_list else "?",
            "media": _extract_media(medium_list),
            "score": r.get("ext:score", ""),
        })
    return releases


def get_release(mbid: str) -> dict:
    """
    Fetch full release data including track-level info.
    Returns a dict ready to map to VorbisComment tags.
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            mbid,
            includes=["artists", "recordings", "artist-credits", "release-groups", "labels"],
        )
    except musicbrainzngs.WebServiceError as e:
        raise RuntimeError(f"MusicBrainz lookup failed: {e}") from e

    release = result["release"]
    artist_credit = release.get("artist-credit", [])
    album_artist = _flatten_artist_credit(artist_credit)
    album_artist_mbid = (
        artist_credit[0]["artist"]["id"]
        if artist_credit and isinstance(artist_credit[0], dict)
        else ""
    )
    release_group = release.get("release-group", {})
    label = _extract_label(release)

    shared_tags = {
        "album": release.get("title", ""),
        "albumartist": album_artist,
        "date": release.get("date", ""),
        "country": release.get("country", ""),
        "label": label,
        "musicbrainz_albumid": release["id"],
        "musicbrainz_albumartistid": album_artist_mbid,
        "musicbrainz_releasegroupid": release_group.get("id", ""),
    }

    tracks: list[dict] = []
    medium_list = release.get("medium-list", [])
    for medium in medium_list:
        disc_number = medium.get("position", 1)
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            track_artist_credit = recording.get("artist-credit", artist_credit)
            track_artist = _flatten_artist_credit(track_artist_credit)
            track_artist_mbid = (
                track_artist_credit[0]["artist"]["id"]
                if track_artist_credit and isinstance(track_artist_credit[0], dict)
                else album_artist_mbid
            )
            tracks.append({
                "position": track.get("position", ""),
                "disc": disc_number,
                "title": recording.get("title", track.get("title", "")),
                "artist": track_artist,
                "tags": {
                    "title": recording.get("title", track.get("title", "")),
                    "artist": track_artist,
                    "tracknumber": str(track.get("position", "")),
                    "musicbrainz_trackid": recording.get("id", ""),
                    "musicbrainz_artistid": track_artist_mbid,
                    "musicbrainz_releasetrackid": track.get("id", ""),
                },
            })

    return {
        "mbid": release["id"],
        "title": release.get("title", ""),
        "artist": album_artist,
        "date": release.get("date", ""),
        "shared_tags": shared_tags,
        "tracks": tracks,
    }


def _flatten_artist_credit(credits: list) -> str:
    parts = []
    for c in credits:
        if isinstance(c, dict) and "artist" in c:
            parts.append(c["artist"]["name"])
            if c.get("joinphrase"):
                parts.append(c["joinphrase"])
        elif isinstance(c, str):
            parts.append(c)
    return "".join(parts).strip()


def _extract_media(medium_list: list) -> str:
    """Return a concise media format string, e.g. 'CD', 'Vinyl', '2×CD'."""
    if not medium_list:
        return ""
    formats = [m.get("format", "") for m in medium_list if m.get("format")]
    if not formats:
        return ""
    # Collapse duplicates while preserving order, then show count prefix if >1
    seen: dict[str, int] = {}
    for f in formats:
        seen[f] = seen.get(f, 0) + 1
    parts = [f"{count}×{fmt}" if count > 1 else fmt for fmt, count in seen.items()]
    return " + ".join(parts)


def _extract_label(release: dict) -> str:
    label_info = release.get("label-info-list", [])
    if label_info and isinstance(label_info[0], dict):
        label = label_info[0].get("label", {})
        return label.get("name", "") if isinstance(label, dict) else ""
    return ""
