import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.config import settings
from app.services import library_cache, navidrome as navi_svc

router = APIRouter()


class ScanPayload(BaseModel):
    full: bool = False


class StarPayload(BaseModel):
    song_id: str
    star: bool


class RatingPayload(BaseModel):
    song_id: str
    rating: int = Field(ge=0, le=5)


def _require_navidrome():
    if not settings.navidrome_url:
        raise HTTPException(status_code=400, detail="Navidrome is not configured (NAVIDROME_URL is not set)")


@router.post("/api/navidrome/scan")
async def trigger_scan(payload: ScanPayload, _: str = Depends(require_auth)):
    _require_navidrome()
    result = await navi_svc.trigger_scan(full=payload.full)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["message"])
    # Also kick off a background Navidrome data sync.
    conn = library_cache.get_db(settings.media_path)
    asyncio.create_task(navi_svc.run_navi_sync(conn))
    return result


@router.get("/api/navidrome/scan/status")
async def navi_sync_status(_: str = Depends(require_auth)):
    """Return current Navidrome sync state for polling."""
    return navi_svc.navi_sync_state()


@router.get("/api/navidrome/album")
async def get_album_info(albumartist: str, album: str, _: str = Depends(require_auth)):
    _require_navidrome()
    album_id = await navi_svc.search_album(albumartist, album)
    if not album_id:
        raise HTTPException(status_code=404, detail="Album not found in Navidrome")
    tracks = await navi_svc.get_album_tracks(album_id)
    return {"album_id": album_id, "tracks": tracks}


@router.post("/api/navidrome/star")
async def star_song(payload: StarPayload, _: str = Depends(require_auth)):
    _require_navidrome()
    result = await navi_svc.set_star(payload.song_id, payload.star)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["message"])
    # Keep cache in sync.
    conn = library_cache.get_db(settings.media_path)
    path = library_cache.get_path_by_navi_id(conn, payload.song_id)
    if path:
        library_cache.update_navidrome_star(conn, path, payload.star)
    return {"ok": True}


@router.post("/api/navidrome/rating")
async def rate_song(payload: RatingPayload, _: str = Depends(require_auth)):
    _require_navidrome()
    result = await navi_svc.set_rating(payload.song_id, payload.rating)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["message"])
    # Keep cache in sync.
    conn = library_cache.get_db(settings.media_path)
    path = library_cache.get_path_by_navi_id(conn, payload.song_id)
    if path:
        library_cache.update_navidrome_rating(conn, path, payload.rating)
    return {"ok": True}
