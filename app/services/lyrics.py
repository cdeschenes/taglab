"""LRCLib lyrics fetch service."""
import asyncio

import httpx

LRCLIB_BASE = "https://lrclib.net/api"


async def fetch_lyrics(artist: str, track: str, album: str = "") -> dict:
    """
    Returns {"plain": str|None, "synced": str|None}.
    Raises RuntimeError if the request fails after retrying.
    """
    params = {"artist_name": artist, "track_name": track}
    if album:
        params["album_name"] = album

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{LRCLIB_BASE}/get", params=params)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc

        if resp.status_code == 404:
            return {"plain": None, "synced": None}
        if resp.status_code == 429:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            raise RuntimeError("LRCLib rate limit (429) — try again later")
        if resp.status_code != 200:
            raise RuntimeError(f"LRCLib error {resp.status_code}")

        data = resp.json()
        return {
            "plain": data.get("plainLyrics"),
            "synced": data.get("syncedLyrics"),
        }

    raise RuntimeError("LRCLib request failed after retry")
