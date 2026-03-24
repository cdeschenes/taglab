"""Library scan trigger and status endpoints."""
import asyncio

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.config import settings
from app.services import library_cache

router = APIRouter()


@router.post("/api/library/scan")
async def trigger_scan(_: str = Depends(require_auth)):
    """Start a background library scan (no-op if one is already running)."""
    if library_cache.scan_state()["status"] == "scanning":
        return {"ok": False, "detail": "Scan already in progress"}
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, library_cache.run_scan, settings.media_path)
    return {"ok": True}


@router.post("/api/library/scan/reset")
async def reset_and_scan(_: str = Depends(require_auth)):
    """Drop the existing SQLite cache and run a full fresh scan."""
    if library_cache.scan_state()["status"] == "scanning":
        return {"ok": False, "detail": "Scan already in progress"}
    library_cache.drop_db(settings.media_path)
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, library_cache.run_scan, settings.media_path)
    return {"ok": True}


@router.get("/api/library/scan/status")
async def scan_status(_: str = Depends(require_auth)):
    """Return current scan state as JSON for polling."""
    return library_cache.scan_state()


@router.get("/api/library/stats")
async def library_stats(_: str = Depends(require_auth)):
    conn = library_cache.get_db(settings.media_path)
    return library_cache.get_stats(conn)
