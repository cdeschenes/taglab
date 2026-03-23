import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from app.services.flac import validate_media_path, write_tags
from app.services import library_cache
from app.services.lyrics import fetch_lyrics

router = APIRouter()


@router.get("/api/lyrics")
async def get_lyrics(
    artist: str,
    track: str,
    album: str = "",
    _: str = Depends(require_auth),
):
    try:
        result = await fetch_lyrics(artist, track, album)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if result["plain"] is None and result["synced"] is None:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    return result


class WriteLrcPayload(BaseModel):
    path: str
    content: str


@router.post("/api/lyrics/write-lrc")
async def write_lrc(payload: WriteLrcPayload, _: str = Depends(require_auth)):
    f = validate_media_path(payload.path, settings.media_path)
    if f.suffix.lower() != ".flac":
        raise HTTPException(status_code=400, detail="Not a FLAC file")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="No content to write")
    lrc_path = f.with_suffix(".lrc")
    if lrc_path.exists():
        return {"ok": False, "exists": True, "message": ".lrc file already exists"}
    try:
        lrc_path.write_text(payload.content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write .lrc: {exc}")
    return {"ok": True, "exists": False, "lrc_path": str(lrc_path)}


class BatchTrack(BaseModel):
    path: str
    artist: str
    track: str
    album: str = ""
    has_lyrics_tag: bool = False


class FetchBatchPayload(BaseModel):
    tracks: List[BatchTrack]


@router.post("/api/lyrics/fetch-batch")
async def fetch_lyrics_batch(payload: FetchBatchPayload, _: str = Depends(require_auth)):
    # Sequential with a small delay — LRCLib rate-limits concurrent requests.
    sem = asyncio.Semaphore(1)

    async def process(item: BatchTrack) -> dict:
        try:
            f = validate_media_path(item.path, settings.media_path)
        except HTTPException as exc:
            return {"path": item.path, "status": "error", "message": exc.detail}

        # Skip tracks that already have lyrics — don't burn LRCLib quota on them.
        lrc_path = f.with_suffix(".lrc")
        if lrc_path.exists():
            return {"path": item.path, "status": "skipped", "reason": "lrc_exists"}
        if item.has_lyrics_tag:
            return {"path": item.path, "status": "skipped", "reason": "has_lyrics_tag"}

        async with sem:
            try:
                result = await fetch_lyrics(item.artist, item.track, item.album)
            except Exception as exc:
                return {"path": item.path, "status": "error", "message": str(exc)}
            finally:
                await asyncio.sleep(0.3)

        if result["synced"]:
            try:
                lrc_path.write_text(result["synced"], encoding="utf-8")
            except OSError as exc:
                return {"path": item.path, "status": "error", "message": f"Failed to write .lrc: {exc}"}
            return {"path": item.path, "status": "synced", "lrc_existed": False}
        elif result["plain"]:
            try:
                write_tags(f, {"lyrics": result["plain"]})
                conn = library_cache.get_db(settings.media_path)
                library_cache.invalidate_path(conn, str(f))
            except OSError as exc:
                return {"path": item.path, "status": "error", "message": f"Failed to write lyrics tag: {exc}"}
            return {"path": item.path, "status": "plain"}
        else:
            return {"path": item.path, "status": "not_found"}

    results = await asyncio.gather(*[process(t) for t in payload.tracks])
    return {"results": list(results)}
