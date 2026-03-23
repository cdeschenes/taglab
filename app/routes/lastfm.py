from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.services import lastfm as lastfm_svc
from app.services import library_cache

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_ARTIST_IMAGE_NAMES = ("artist.jpg", "artist.png", "artist.jpeg", "artist.webp")


def _find_local_artist_image(folder: Path) -> Path | None:
    for name in _ARTIST_IMAGE_NAMES:
        p = folder / name
        if p.exists():
            return p
    return None


def _resolve_artist_folder(artist: str, media_path: str) -> Path | None:
    conn = library_cache.get_db(Path(media_path))
    row = conn.execute(
        "SELECT path FROM tracks WHERE artist_dir = ? LIMIT 1", (artist,)
    ).fetchone()
    if not row:
        return None
    return Path(row["path"]).parent.parent


async def _download_artist_image(url: str, dest: Path) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "TagLab/1.0"},
                follow_redirects=True,
            )
            if resp.is_success:
                dest.write_bytes(resp.content)
                return True
    except Exception:
        pass
    return False


@router.get("/api/lastfm/artist", response_class=HTMLResponse)
async def lastfm_artist(request: Request, artist: str, _: str = Depends(require_auth)):
    info = None
    if settings.lastfm_api_key:
        info = await lastfm_svc.get_artist_info(artist, settings.lastfm_api_key)

    folder = _resolve_artist_folder(artist, settings.media_path)
    if info and info.get("image_url") and folder:
        local = _find_local_artist_image(folder)
        if not local:
            dest = folder / "artist.jpg"
            ok = await _download_artist_image(info["image_url"], dest)
            if ok:
                local = dest
        if local:
            info = {**info, "image_url": f"/api/artwork/artist-photo?folder={folder}"}

    return templates.TemplateResponse(request, "partials/artist_info.html", {
        "info": info,
        "artist": artist,
        "folder": str(folder) if folder else "",
    })
