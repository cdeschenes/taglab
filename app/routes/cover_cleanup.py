from fastapi import APIRouter, Depends, Query
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.services import library_cache

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/ui/cover-cleanup", response_class=HTMLResponse)
async def cover_cleanup_view(
    request: Request,
    _: str = Depends(require_auth),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=10, le=500),
    sort: str = Query(default="name", pattern="^(name|recently_added|cover_size)$"),
    min_rating: int = Query(default=0, ge=0, le=5),
    starred_only: bool = Query(default=False),
):
    conn = library_cache.get_db(settings.media_path)
    all_albums = library_cache.get_all_albums_filtered(
        conn, sort=sort, min_rating=min_rating, starred_only=starred_only
    )

    total = len(all_albums)
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)
    offset = (page - 1) * limit
    albums = all_albums[offset : offset + limit]

    return templates.TemplateResponse(
        request,
        "partials/cover_cleanup.html",
        {
            "albums": albums,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "sort": sort,
            "min_rating": min_rating,
            "starred_only": starred_only,
            "navidrome_enabled": bool(settings.navidrome_url),
        },
    )
