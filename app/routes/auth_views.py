import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import make_auth_cookie, _COOKIE_NAME
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: int = 0):
    return templates.TemplateResponse(request, "login.html", {"error": bool(error)})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    valid_user = secrets.compare_digest(
        username.encode("utf-8"), settings.auth_user.encode("utf-8")
    )
    valid_pass = secrets.compare_digest(
        password.encode("utf-8"), settings.auth_password.encode("utf-8")
    )
    if not (valid_user and valid_pass):
        return RedirectResponse("/login?error=1", status_code=303)

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        _COOKIE_NAME,
        make_auth_cookie(username),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(_COOKIE_NAME)
    return response
