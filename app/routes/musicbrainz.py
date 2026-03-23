from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.auth import require_auth
from app.services import musicbrainz as mb_svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/ui/musicbrainz/search", response_class=HTMLResponse)
async def mb_search_ui(
    request: Request,
    artist: str = "",
    album: str = "",
    _: str = Depends(require_auth),
):
    results: list[dict] = []
    error: str = ""
    if artist or album:
        try:
            results = mb_svc.search_releases(artist=artist, album=album)
        except RuntimeError as e:
            error = str(e)

    return templates.TemplateResponse(request, "partials/mb_results.html", {"results": results, "error": error})


@router.get("/api/musicbrainz/release/{mbid}")
async def get_release(mbid: str, _: str = Depends(require_auth)):
    try:
        return mb_svc.get_release(mbid)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
