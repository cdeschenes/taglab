import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app import config
from app.config import settings
from app.routes import (
    album, artist, artwork, auth_views, cover_cleanup, explorer,
    lastfm, libraries, library, lyrics, metadata, musicbrainz, navidrome, organizer, player, replaygain, trash,
)
from app.services import library_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, library_cache.run_scan, settings.media_path)
    yield


app = FastAPI(title="TagLab", docs_url=None, redoc_url=None, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

for router in [
    auth_views.router, album.router, artist.router, artwork.router, cover_cleanup.router,
    explorer.router, lastfm.router, libraries.router, library.router, lyrics.router, metadata.router,
    musicbrainz.router, navidrome.router, organizer.router, player.router,
    replaygain.router, trash.router,
]:
    app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, username: str = Depends(require_auth)):
    libs = config.get_libraries()
    active_idx = config.get_active_library_idx()
    return templates.TemplateResponse(request, "index.html", {
        "username": username,
        "allow_delete": settings.allow_delete,
        "navidrome_enabled": bool(settings.navidrome_url),
        "libraries": libs,
        "active_library_idx": active_idx,
    })
