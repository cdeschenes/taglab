"""Multi-library switch endpoints."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_auth
from app import config
from app.services import library_cache

router = APIRouter()


@router.get("/api/libraries")
async def list_libraries(_: str = Depends(require_auth)):
    active_idx = config.get_active_library_idx()
    return [
        {"idx": i, "label": lib["label"], "active": i == active_idx}
        for i, lib in enumerate(config.get_libraries())
    ]


@router.post("/api/libraries/switch")
async def switch_library(idx: int, _: str = Depends(require_auth)):
    libs = config.get_libraries()
    if idx < 0 or idx >= len(libs):
        raise HTTPException(status_code=400, detail="Invalid library index")
    config.set_active_library(idx)
    if library_cache.scan_state()["status"] != "scanning":
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, library_cache.run_scan, config.settings.media_path)
    return {"ok": True, "label": libs[idx]["label"]}
