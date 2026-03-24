"""Navidrome API integration via the Subsonic API."""
from __future__ import annotations

import datetime
import json
import logging
import sqlite3

import httpx

log = logging.getLogger(__name__)

from app.config import settings

# Shared mutable sync state — single-user app, no concurrency concerns.
_navi_sync_state: dict = {"status": "idle", "done": 0, "total": 0}


def navi_sync_state() -> dict:
    return dict(_navi_sync_state)


def _subsonic_params() -> dict:
    return {
        "u": settings.navidrome_user,
        "p": settings.navidrome_password,
        "c": "TagLab",
        "v": "1.16.1",
        "f": "json",
    }


def _base() -> str:
    return settings.navidrome_url.rstrip("/")


def _ok(data: dict) -> bool:
    return data.get("subsonic-response", {}).get("status", "") == "ok"


async def trigger_scan(full: bool = False) -> dict:
    """
    Trigger a Navidrome library scan.
    Navidrome uses the Subsonic API; scanner is triggered via /rest/startScan.
    Returns {"ok": bool, "message": str}.
    """
    if not settings.navidrome_url:
        return {"ok": False, "message": "Navidrome not configured"}

    base = settings.navidrome_url.rstrip("/")
    params = {
        "u": settings.navidrome_user,
        "p": settings.navidrome_password,
        "c": "TagLab",
        "v": "1.16.1",
        "f": "json",
        "fullScan": "true" if full else "false",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/rest/startScan", params=params)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("subsonic-response", {}).get("status", "")
            if status == "ok":
                return {"ok": True, "message": "Navidrome scan triggered"}
            return {"ok": False, "message": f"Navidrome returned: {status}"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"HTTP error: {e}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def search_album(albumartist: str, album: str) -> str | None:
    """
    Search for an album in Navidrome by artist + title.
    Returns the Navidrome albumId, or None if not found.
    """
    if not settings.navidrome_url:
        return None
    params = {**_subsonic_params(), "query": album, "albumCount": "10", "songCount": "0", "artistCount": "0"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{_base()}/rest/search3", params=params)
            resp.raise_for_status()
            data = resp.json()
            if not _ok(data):
                return None
            albums = data.get("subsonic-response", {}).get("searchResult3", {}).get("album", [])
    except Exception:
        return None

    a_lower = albumartist.lower().strip()
    t_lower = album.lower().strip()

    def _strip_article(s: str) -> str:
        for art in ("the ", "a ", "an "):
            if s.startswith(art):
                return s[len(art):]
        return s

    a_norm = _strip_article(a_lower)
    t_norm = _strip_article(t_lower)

    # Pass 1: exact match on both name and artist
    for alb in albums:
        na = alb.get("artist", "").lower().strip()
        nt = alb.get("name", "").lower().strip()
        if na == a_lower and nt == t_lower:
            return alb["id"]

    # Pass 2: fuzzy — album name contains/is-contained, artist is substring match
    for alb in albums:
        na = _strip_article(alb.get("artist", "").lower().strip())
        nt = _strip_article(alb.get("name", "").lower().strip())
        title_match = nt == t_norm or nt in t_norm or t_norm in nt
        artist_match = na == a_norm or na in a_norm or a_norm in na
        if title_match and artist_match:
            return alb["id"]

    # Pass 3: single result fallback
    if len(albums) == 1:
        return albums[0]["id"]

    return None


def _parse_navi_created(raw: str | None) -> float | None:
    """Parse a Navidrome ISO 8601 created timestamp to a Unix float, or None."""
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


async def get_album_tracks(album_id: str) -> list[dict]:
    """
    Fetch all tracks for a Navidrome album.
    Returns list of {id, track, disc_number, play_count, starred, user_rating, navi_created}.
    """
    params = {**_subsonic_params(), "id": album_id}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{_base()}/rest/getAlbum", params=params)
            resp.raise_for_status()
            data = resp.json()
            if not _ok(data):
                return []
            songs = data.get("subsonic-response", {}).get("album", {}).get("song", [])
    except Exception:
        return []

    result = []
    for s in songs:
        result.append({
            "id": s["id"],
            "track": s.get("track", 0),
            "disc_number": s.get("discNumber", 1),
            "play_count": s.get("playCount", 0),
            "starred": "starred" in s and bool(s["starred"]),
            "user_rating": s.get("userRating", 0),
            "navi_created": _parse_navi_created(s.get("created")),
        })
    return result


async def set_star(song_id: str, star: bool) -> dict:
    """Star or unstar a song. Returns {"ok": bool, "message": str}."""
    endpoint = "star" if star else "unstar"
    params = {**_subsonic_params(), "id": song_id}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{_base()}/rest/{endpoint}", params=params)
            resp.raise_for_status()
            data = resp.json()
            if _ok(data):
                return {"ok": True, "message": "OK"}
            return {"ok": False, "message": f"Navidrome error: {data.get('subsonic-response', {}).get('status', '')}"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"HTTP error: {e}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def set_rating(song_id: str, rating: int) -> dict:
    """Set star rating (0–5) for a song. Rating 0 removes the rating."""
    params = {**_subsonic_params(), "id": song_id, "rating": str(rating)}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{_base()}/rest/setRating", params=params)
            resp.raise_for_status()
            data = resp.json()
            if _ok(data):
                return {"ok": True, "message": "OK"}
            return {"ok": False, "message": f"Navidrome error: {data.get('subsonic-response', {}).get('status', '')}"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"HTTP error: {e}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def run_navi_sync(conn: sqlite3.Connection) -> None:
    """
    Walk every album in the library cache, fetch Navidrome data for each, and
    persist favorites/ratings/play-counts to the navidrome_tracks table.
    Mirrors the pattern of library_cache.run_scan().
    """
    from app.services import library_cache

    albums = library_cache.get_all_albums(conn)
    _navi_sync_state.update({"status": "scanning", "done": 0, "total": len(albums)})

    for i, album in enumerate(albums):
        try:
            # Use FLAC tags from first track for a more accurate Navidrome search.
            first_row = conn.execute(
                "SELECT tags_json FROM tracks WHERE artist_dir = ? AND album_dir = ? ORDER BY filename LIMIT 1",
                (album["artist"], album["album"]),
            ).fetchone()
            tags = json.loads(first_row["tags_json"] or "{}") if first_row else {}
            search_artist = tags.get("albumartist") or tags.get("artist") or album["artist"]
            search_title = tags.get("album") or album["album"]

            album_id = await search_album(search_artist, search_title)
            if not album_id:
                continue

            navi_tracks = await get_album_tracks(album_id)
            if not navi_tracks:
                continue

            # Build a disc:track → navi track lookup.
            by_disc_track: dict[str, dict] = {}
            for nt in navi_tracks:
                key = f"{nt['disc_number']}:{nt['track']}"
                by_disc_track[key] = nt

            # Match local tracks by disc:track number.
            local_rows = conn.execute(
                "SELECT path, tags_json FROM tracks WHERE artist_dir = ? AND album_dir = ? ORDER BY filename",
                (album["artist"], album["album"]),
            ).fetchall()

            for lt in local_rows:
                lt_tags = json.loads(lt["tags_json"] or "{}")
                disc = int(lt_tags.get("discnumber", "1") or "1")
                track_num = int(lt_tags.get("tracknumber", "0") or "0")
                if track_num == 0:
                    continue
                nt = by_disc_track.get(f"{disc}:{track_num}")
                if nt:
                    library_cache.upsert_navidrome_track(
                        conn,
                        lt["path"],
                        nt["id"],
                        nt["play_count"],
                        nt["starred"],
                        nt["user_rating"],
                        nt.get("navi_created"),
                    )
        except Exception as exc:
            log.warning("Navidrome sync failed for %s / %s: %s", album["artist"], album["album"], exc)

        _navi_sync_state["done"] = i + 1

    _navi_sync_state["status"] = "idle"
