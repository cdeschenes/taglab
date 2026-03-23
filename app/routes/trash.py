from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc
from app.services import library_cache
from app.services import trash as trash_svc

router = APIRouter()


def _require_delete_enabled():
    if not settings.allow_delete:
        raise HTTPException(status_code=403, detail="Delete is not enabled")


class TrashPayload(BaseModel):
    path: str


@router.post("/api/trash/artist")
async def trash_artist(payload: TrashPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    folder = flac_svc.validate_media_path(payload.path, settings.media_path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    dest = trash_svc.move_to_trash(folder, settings.media_path)
    conn = library_cache.get_db(settings.media_path)
    library_cache.delete_tracks_under(conn, str(folder))
    return {"ok": True, "trashed": str(dest)}


@router.post("/api/trash/album")
async def trash_album(payload: TrashPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    folder = flac_svc.validate_media_path(payload.path, settings.media_path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    dest = trash_svc.move_to_trash(folder, settings.media_path)
    conn = library_cache.get_db(settings.media_path)
    library_cache.delete_tracks_under(conn, str(folder))
    return {"ok": True, "trashed": str(dest)}


@router.post("/api/trash/empty")
async def empty_trash(_: str = Depends(require_auth)):
    _require_delete_enabled()
    count = trash_svc.empty_trash(settings.media_path)
    return {"ok": True, "removed": count}


@router.post("/api/trash/track")
async def trash_track(payload: TrashPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    f = flac_svc.validate_media_path(payload.path, settings.media_path)
    if not f.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    dest = trash_svc.move_to_trash(f, settings.media_path)
    conn = library_cache.get_db(settings.media_path)
    library_cache.invalidate_path(conn, str(f))
    return {"ok": True, "trashed": str(dest)}
