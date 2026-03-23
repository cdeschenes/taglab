from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth import require_auth
from app.config import settings
from app.services.flac import validate_media_path

router = APIRouter()


@router.get("/api/stream")
async def stream_track(path: str, _: str = Depends(require_auth)):
    resolved = validate_media_path(path, settings.media_path)
    if not resolved.is_file() or resolved.suffix.lower() != ".flac":
        raise HTTPException(status_code=404, detail="FLAC file not found")
    return FileResponse(str(resolved), media_type="audio/flac")
