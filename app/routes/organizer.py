from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.config import get_libraries, organize_cleanup_patterns, settings
from app.services import flac as flac_svc
from app.services import library_cache
from app.services import organizer as org_svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_organizer():
    if not settings.organize_target:
        raise HTTPException(status_code=400, detail="File organizer is not configured (ORGANIZE_TARGET is not set)")


class OrganizerPreviewPayload(BaseModel):
    paths: list[str]
    pattern: Optional[str] = None
    target: Optional[str] = None


class OrganizerApplyPayload(BaseModel):
    moves: list[dict]  # [{"source": str, "target": str}, ...]


@router.post("/api/organizer/preview", response_class=HTMLResponse)
async def preview_organize(
    request: Request,
    payload: OrganizerPreviewPayload,
    _: str = Depends(require_auth),
):
    current_pattern = payload.pattern if payload.pattern is not None else settings.organize_pattern
    _target = payload.target if payload.target is not None else settings.organize_target

    if not _target:
        raise HTTPException(status_code=400, detail="File organizer is not configured (ORGANIZE_TARGET is not set)")

    current_target = Path(_target).resolve()

    files: list[Path] = []
    tags_by_path: dict[str, dict] = {}
    for p in payload.paths:
        f = flac_svc.validate_media_path(p, settings.media_path)
        files.append(f)
        tags_by_path[str(f)] = flac_svc.read_tags(f)["tags"]

    previews = org_svc.preview_organize(
        files,
        tags_by_path,
        current_pattern,
        current_target,
    )
    return templates.TemplateResponse(
        request,
        "partials/organize_preview.html",
        {
            "previews": previews,
            "paths": payload.paths,
            "current_pattern": current_pattern,
            "current_target": str(current_target),
        },
    )


@router.post("/api/organizer/apply")
async def apply_organize(payload: OrganizerApplyPayload, _: str = Depends(require_auth)):
    _require_organizer()

    known_roots = [Path(lib["path"]).resolve() for lib in get_libraries()]
    if settings.organize_target:
        known_roots.append(Path(settings.organize_target).resolve())

    # Validate sources are within active library; targets must be within any registered library
    for move in payload.moves:
        flac_svc.validate_media_path(move["source"], settings.media_path)
        target = Path(move["target"]).resolve()
        if not any(str(target).startswith(str(root)) for root in known_roots):
            raise HTTPException(
                status_code=400,
                detail=f"Target path is outside all registered libraries: {target}",
            )

    results = org_svc.apply_organize(payload.moves, organize_cleanup_patterns)

    # Immediately remove moved tracks from the source library cache so the
    # explorer reflects the change without waiting for a full background scan.
    moved_sources = [r["source"] for r in results if r.get("ok") and r.get("target")]
    if moved_sources:
        conn = library_cache.get_db(settings.media_path)
        for src in moved_sources:
            library_cache.delete_tracks_under(conn, src)

    return {"ok": True, "results": results}
