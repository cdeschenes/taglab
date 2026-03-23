from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.services import library_cache
from app.services.flac import validate_media_path

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _media_dir(rel: str = "") -> Path:
    if not rel:
        return settings.media_path.resolve()
    return validate_media_path(rel, settings.media_path)


@router.get("/ui/explorer", response_class=HTMLResponse)
async def get_explorer(request: Request, _: str = Depends(require_auth)):
    media = settings.media_path
    if not media.exists():
        raise HTTPException(status_code=500, detail=f"Media path {media} does not exist")

    conn = library_cache.get_db(media)
    artists = library_cache.get_artists(conn)

    # Fallback to filesystem scan if cache is not yet populated.
    if not artists:
        artists = sorted(
            [d.name for d in media.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=str.casefold,
        )

    return templates.TemplateResponse(request, "partials/explorer.html", {"artists": artists})


@router.get("/ui/albums", response_class=HTMLResponse)
async def get_albums(request: Request, artist: str, _: str = Depends(require_auth)):
    artist_path = _media_dir(artist)
    if not artist_path.is_dir():
        raise HTTPException(status_code=404, detail="Artist not found")

    conn = library_cache.get_db(settings.media_path)
    albums = library_cache.get_albums_for_artist(conn, artist)

    # Fallback to filesystem scan if cache is not yet populated.
    if not albums:
        albums = sorted(
            [d.name for d in artist_path.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=str.casefold,
        )

    return templates.TemplateResponse(
        request, "partials/albums.html", {"artist": artist, "albums": albums}
    )
