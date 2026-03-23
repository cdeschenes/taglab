"""Last.fm artist metadata via their public REST API."""
from __future__ import annotations
import re
from urllib.parse import quote
import httpx

LASTFM_API_URL = "http://ws.audioscrobbler.com/2.0/"
LASTFM_IMAGES_URL = "https://www.last.fm/music/{}/+images"

# Last.fm has deprecated artist images; all responses return this placeholder hash.
_LASTFM_NOIMAGE_HASH = "2a96cbd8b46e442fc41c2b86b821562f"


def _strip_html(text: str) -> str:
    """Remove HTML tags and trim whitespace."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _is_placeholder(url: str) -> bool:
    return not url or _LASTFM_NOIMAGE_HASH in url


async def _lastfm_scrape_image(artist: str, client: httpx.AsyncClient) -> str:
    """Scrape first artist photo from Last.fm images page. Returns '' on failure."""
    try:
        url = LASTFM_IMAGES_URL.format(quote(artist.replace(" ", "+"), safe="+"))
        resp = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=8,
        )
        if not resp.is_success:
            return ""
        matches = re.findall(
            r'https://lastfm\.freetls\.fastly\.net/i/u/[^"\'>\s]+',
            resp.text,
        )
        if not matches:
            return ""
        best = re.sub(r"/u/[^/]+/", "/u/770x0/", matches[0])
        return best
    except Exception:
        return ""


async def get_artist_info(artist: str, api_key: str) -> dict | None:
    """Return cleaned artist info dict, or None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(LASTFM_API_URL, params={
                "method": "artist.getinfo",
                "artist": artist,
                "api_key": api_key,
                "format": "json",
            })
            if not resp.is_success:
                return None
            data = resp.json()
            if "error" in data or "artist" not in data:
                return None
            a = data["artist"]

            # Pick largest available image URL, ignoring the known placeholder
            image_url = ""
            for img in reversed(a.get("image", [])):
                url = img.get("#text", "")
                if url and not _is_placeholder(url):
                    image_url = url
                    break

            # Fall back to Last.fm web scrape if API gave us nothing useful
            if not image_url:
                image_url = await _lastfm_scrape_image(a.get("name", artist), client)

    except Exception:
        return None

    # Bio: strip HTML
    raw_bio = a.get("bio", {}).get("summary", "")
    bio = _strip_html(raw_bio).strip()

    # Tags: up to 5
    tags = [t["name"] for t in a.get("tags", {}).get("tag", [])[:5]]

    # Similar artists: up to 5
    similar = [
        {"name": s["name"], "url": s["url"]}
        for s in a.get("similar", {}).get("artist", [])[:5]
    ]

    stats = a.get("stats", {})
    return {
        "name": a.get("name", artist),
        "listeners": stats.get("listeners", ""),
        "playcount": stats.get("playcount", ""),
        "bio": bio,
        "tags": tags,
        "image_url": image_url,
        "url": a.get("url", ""),
        "similar": similar,
    }
