from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc, library_cache

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _album_dir(path: str) -> Path:
    folder = flac_svc.validate_media_path(path, settings.media_path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    return folder


# ─── UI fragment ──────────────────────────────────────────────────────────────

@router.get("/ui/album", response_class=HTMLResponse)
async def album_editor(request: Request, path: str, _: str = Depends(require_auth)):
    folder = _album_dir(path)

    # Serve from SQLite cache when available to avoid per-track CIFS reads.
    conn = library_cache.get_db(settings.media_path)
    cached = library_cache.get_album_tracks_cached(conn, folder.parent.name, folder.name)
    if cached is not None:
        album = flac_svc.build_album_dict(folder, cached)
    else:
        album = flac_svc.read_album(folder)

    if not album["tracks"]:
        return HTMLResponse(
            f'<div class="empty-state"><p>No FLAC files found in<br><code>{folder}</code></p></div>'
        )

    return templates.TemplateResponse(request, "partials/album_editor.html", {
        "album": album,
        "organize_enabled": settings.organize_target is not None,
        "navidrome_enabled": bool(settings.navidrome_url),
        "standard_tags": flac_svc.STANDARD_TAGS,
    })


# ─── API ──────────────────────────────────────────────────────────────────────

class TrackPayload(BaseModel):
    path: str
    tags: dict[str, Any]


class AlbumSavePayload(BaseModel):
    path: str
    shared_tags: dict[str, Any]
    tracks: list[TrackPayload]
    cover_pending: bool = False


class BulkAlbumPayload(BaseModel):
    album_folders: list[str]
    shared_tags: dict[str, Any]


@router.post("/api/album/preview", response_class=HTMLResponse)
async def preview_album(
    request: Request,
    payload: AlbumSavePayload,
    _: str = Depends(require_auth),
):
    folder = _album_dir(payload.path)
    previews = flac_svc.build_preview(
        str(folder),
        {k: str(v) for k, v in payload.shared_tags.items()},
        [{"path": t.path, "tags": {k: str(v) for k, v in t.tags.items()}} for t in payload.tracks],
    )
    return templates.TemplateResponse(request, "partials/preview_modal.html", {
        "previews": previews,
        "payload": payload.model_dump(),
        "cover_pending": payload.cover_pending,
    })


@router.post("/api/album/bulk-preview", response_class=HTMLResponse)
async def bulk_preview_albums(
    request: Request,
    payload: BulkAlbumPayload,
    _: str = Depends(require_auth),
):
    filtered = {k: str(v) for k, v in payload.shared_tags.items() if str(v).strip()}
    all_previews: list[dict] = []
    for folder_path in payload.album_folders:
        folder = _album_dir(folder_path)
        previews = flac_svc.build_preview(str(folder), filtered, [])
        for p in previews:
            p["album"] = folder.name
        all_previews.extend(previews)
    return templates.TemplateResponse(request, "partials/bulk_preview_modal.html", {
        "previews": all_previews,
        "payload": payload.model_dump(),
    })


@router.post("/api/album/bulk-save")
async def bulk_save_albums(payload: BulkAlbumPayload, _: str = Depends(require_auth)):
    filtered = {k: str(v) for k, v in payload.shared_tags.items() if str(v).strip()}
    conn = library_cache.get_db(settings.media_path)
    saved = 0
    for folder_path in payload.album_folders:
        folder = _album_dir(folder_path)
        for f in flac_svc.list_flac_files(folder):
            flac_svc.write_tags(f, filtered)
            library_cache.invalidate_path(conn, str(f))
            saved += 1
    return {"ok": True, "saved": saved}


@router.post("/api/album/save")
async def save_album(payload: AlbumSavePayload, _: str = Depends(require_auth)):
    folder = _album_dir(payload.path)
    overrides = {t.path: t.tags for t in payload.tracks}
    shared = {k: str(v) for k, v in payload.shared_tags.items()}

    conn = library_cache.get_db(settings.media_path)
    saved: list[str] = []
    for f in flac_svc.list_flac_files(folder):
        # Track overrides applied first (per-track title, tracknumber, etc.)
        # then shared_tags applied on top so album-level edits always win.
        merged: dict[str, str] = {}
        if str(f) in overrides:
            merged.update({k: str(v) for k, v in overrides[str(f)].items()})
        merged.update(shared)
        flac_svc.write_tags(f, merged)
        library_cache.invalidate_path(conn, str(f))
        saved.append(f.name)

    return {"ok": True, "saved": saved}
