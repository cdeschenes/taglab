import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app import config
from app.config import settings
from app.routes import (
    album, artist, artwork, auth_views, cover_cleanup, explorer,
    help, lastfm, libraries, library, lyrics, metadata, musicbrainz, navidrome, organizer, patterns, player, replaygain, trash,
)
from app.services import library_cache


def _setup_file_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s  %(message)s"
    ))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logging.getLogger(name).addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_file_logging(settings.cache_path / "taglab.log")
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, library_cache.run_scan, settings.media_path)
    yield


app = FastAPI(title="TagLab", docs_url=None, redoc_url=None, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

for router in [
    auth_views.router, album.router, artist.router, artwork.router, cover_cleanup.router,
    explorer.router, help.router, lastfm.router, libraries.router, library.router, lyrics.router,
    metadata.router, musicbrainz.router, navidrome.router, organizer.router, patterns.router,
    player.router, replaygain.router, trash.router,
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
