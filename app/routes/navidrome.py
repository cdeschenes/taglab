from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services import navidrome as navi_svc

router = APIRouter()


class ScanPayload(BaseModel):
    full: bool = False


@router.post("/api/navidrome/scan")
async def trigger_scan(payload: ScanPayload, _: str = Depends(require_auth)):
    if not settings.navidrome_url:
        raise HTTPException(status_code=400, detail="Navidrome is not configured (NAVIDROME_URL is not set)")
    result = await navi_svc.trigger_scan(full=payload.full)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result
