from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.version import __version__

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/ui/help", response_class=HTMLResponse)
async def help_view(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "partials/help.html", {
        "navidrome_enabled": bool(settings.navidrome_url),
        "allow_delete": settings.allow_delete,
        "version": __version__,
    })
