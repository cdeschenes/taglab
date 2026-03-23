from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _flac_file(path: str) -> Path:
    f = flac_svc.validate_media_path(path, settings.media_path)
    if not f.is_file() or f.suffix.lower() != ".flac":
        raise HTTPException(status_code=400, detail="Not a FLAC file")
    return f


# ─── UI fragment ──────────────────────────────────────────────────────────────

@router.get("/ui/track", response_class=HTMLResponse)
async def track_editor(request: Request, path: str, _: str = Depends(require_auth)):
    f = _flac_file(path)
    track = flac_svc.read_tags(f)
    return templates.TemplateResponse(request, "partials/track_editor.html", {"track": track, "standard_tags": flac_svc.STANDARD_TAGS})


# ─── API ──────────────────────────────────────────────────────────────────────

@router.get("/api/track")
async def get_track(path: str, _: str = Depends(require_auth)):
    return flac_svc.read_tags(_flac_file(path))


class TrackSavePayload(BaseModel):
    path: str
    tags: dict[str, str]


@router.post("/api/track/save")
async def save_track(payload: TrackSavePayload, _: str = Depends(require_auth)):
    f = _flac_file(payload.path)
    flac_svc.write_tags(f, payload.tags)
    return {"ok": True, "filename": f.name}
