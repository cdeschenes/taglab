import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.services import library_cache

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/ui/artist", response_class=HTMLResponse)
async def artist_page(request: Request, artist: str, _: str = Depends(require_auth)):
    conn = library_cache.get_db(settings.media_path)
    all_albums = library_cache.get_all_albums(conn)
    base_albums = [a for a in all_albums if a["artist"] == artist]

    albums = []
    for a in base_albums:
        rows = conn.execute(
            "SELECT path, filename, tags_json FROM tracks"
            " WHERE artist_dir = ? AND album_dir = ? ORDER BY filename",
            (a["artist"], a["album"]),
        ).fetchall()
        tracks = [
            {
                "path": r["path"],
                "filename": r["filename"],
                "tags": json.loads(r["tags_json"] or "{}"),
            }
            for r in rows
        ]
        albums.append({**a, "tracks": tracks})

    return templates.TemplateResponse(request, "partials/artist.html", {
        "artist": artist,
        "albums": albums,
        "artist_path": str(settings.media_path / artist),
        "organize_enabled": settings.organize_target is not None,
    })
