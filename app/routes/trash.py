from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc
from app.services import library_cache
from app.services import trash as trash_svc
from mutagen.flac import FLAC

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_delete_enabled():
    if not settings.allow_delete:
        raise HTTPException(status_code=403, detail="Delete is not enabled")


class TrashPayload(BaseModel):
    path: str


class RestoreAlbumPayload(BaseModel):
    artist: str
    album: str


class RestoreArtistPayload(BaseModel):
    artist: str


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


@router.get("/ui/trash", response_class=HTMLResponse)
async def trash_view(request: Request, _: str = Depends(require_auth)):
    items = trash_svc.list_trash(settings.media_path)
    total_tracks = sum(
        t["track_count"] for artist in items for t in artist["albums"]
    )
    return templates.TemplateResponse(
        request,
        "partials/trash.html",
        {
            "items": items,
            "allow_delete": settings.allow_delete,
            "total_tracks": total_tracks,
        },
    )


def _reindex_track(conn, restored_path: Path) -> None:
    """Read FLAC metadata and upsert into library cache."""
    try:
        audio = FLAC(str(restored_path))
        mtime = restored_path.stat().st_mtime
        tags: dict[str, str] = {}
        if audio.tags:
            for key, values in audio.tags.as_dict().items():
                tags[key.lower()] = values[0] if len(values) == 1 else "; ".join(values)
        cover_pic = next((pic for pic in audio.pictures if pic.type == 3), None)
        library_cache.upsert_track(conn, str(restored_path), {
            "mtime": mtime,
            "artist_dir": restored_path.parent.parent.name,
            "album_dir": restored_path.parent.name,
            "filename": restored_path.name,
            "has_cover": cover_pic is not None,
            "cover_w": cover_pic.width if cover_pic else None,
            "cover_h": cover_pic.height if cover_pic else None,
            "sample_rate": audio.info.sample_rate,
            "bits": audio.info.bits_per_sample,
            "channels": audio.info.channels,
            "duration": audio.info.length,
            "tags": tags,
        })
    except Exception:
        pass


def _validate_trash_path(path: str) -> Path:
    """Ensure path is a real file inside .trash under media_root."""
    trash_dir = settings.media_path / ".trash"
    p = Path(path).resolve()
    try:
        p.relative_to(trash_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path is not inside trash")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found in trash")
    return p


@router.post("/api/trash/restore/track")
async def restore_track(payload: TrashPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    src = _validate_trash_path(payload.path)
    try:
        dest = trash_svc.restore_path(str(src), settings.media_path)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    conn = library_cache.get_db(settings.media_path)
    _reindex_track(conn, dest)
    return {"ok": True, "restored_to": str(dest)}


@router.post("/api/trash/restore/album")
async def restore_album(payload: RestoreAlbumPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    trash_dir = settings.media_path / ".trash"
    album_dir = trash_dir / payload.artist / payload.album
    if not album_dir.is_dir():
        raise HTTPException(status_code=404, detail="Album not found in trash")
    conn = library_cache.get_db(settings.media_path)
    restored = 0
    errors = []
    for f in sorted(album_dir.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            dest = trash_svc.restore_path(str(f), settings.media_path)
            _reindex_track(conn, dest)
            restored += 1
        except FileExistsError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(str(e))
    return {"ok": True, "count": restored, "errors": errors}


@router.post("/api/trash/restore/artist")
async def restore_artist(payload: RestoreArtistPayload, _: str = Depends(require_auth)):
    _require_delete_enabled()
    trash_dir = settings.media_path / ".trash"
    artist_dir = trash_dir / payload.artist
    if not artist_dir.is_dir():
        raise HTTPException(status_code=404, detail="Artist not found in trash")
    conn = library_cache.get_db(settings.media_path)
    restored = 0
    errors = []
    for f in sorted(artist_dir.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            dest = trash_svc.restore_path(str(f), settings.media_path)
            _reindex_track(conn, dest)
            restored += 1
        except FileExistsError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(str(e))
    return {"ok": True, "count": restored, "errors": errors}
