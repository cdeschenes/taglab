from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc
from app.services import replaygain as rg_svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class RGCalculatePayload(BaseModel):
    paths: list[str]
    album_mode: bool = True


class RGApplyPayload(BaseModel):
    results: list[dict]  # list of {path, tags}


@router.post("/api/replaygain/calculate", response_class=HTMLResponse)
async def calculate_rg(
    request: Request,
    payload: RGCalculatePayload,
    _: str = Depends(require_auth),
):
    """Calculate ReplayGain (no writes). Returns an HTML preview modal."""
    validated: list[Path] = []
    for p in payload.paths:
        f = flac_svc.validate_media_path(p, settings.media_path)
        if not f.is_file():
            raise HTTPException(status_code=400, detail=f"Not a file: {p}")
        validated.append(f)

    if not validated:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        results = rg_svc.calculate_replaygain(validated, album_mode=payload.album_mode)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return templates.TemplateResponse(request, "partials/rg_preview.html", {"results": results, "album_mode": payload.album_mode})


@router.post("/api/replaygain/apply")
async def apply_rg(payload: RGApplyPayload, _: str = Depends(require_auth)):
    """Write calculated ReplayGain tags to disk."""
    updated: list[str] = []
    for item in payload.results:
        f = flac_svc.validate_media_path(item["path"], settings.media_path)
        flac_svc.write_tags(f, item["tags"])
        updated.append(f.name)
    return {"ok": True, "updated": updated}


@router.post("/api/replaygain/calculate-apply")
async def calculate_apply_rg(
    payload: RGCalculatePayload,
    _: str = Depends(require_auth),
):
    """Calculate ReplayGain and immediately write tags (no preview step)."""
    validated: list[Path] = []
    for p in payload.paths:
        f = flac_svc.validate_media_path(p, settings.media_path)
        if not f.is_file():
            raise HTTPException(status_code=400, detail=f"Not a file: {p}")
        validated.append(f)

    if not validated:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        results = rg_svc.calculate_replaygain(validated, album_mode=payload.album_mode)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    for item in results:
        f = flac_svc.validate_media_path(item["path"], settings.media_path)
        flac_svc.write_tags(f, item["tags"])

    return {"ok": True, "updated": [r["filename"] for r in results], "count": len(results)}
