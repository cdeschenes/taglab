import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import settings

security = HTTPBasic(auto_error=False)

_COOKIE_NAME = "taglab_auth"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt="auth")


def make_auth_cookie(username: str) -> str:
    return _serializer().dumps(username)


def _decode_cookie(value: str) -> Optional[str]:
    try:
        return _serializer().loads(value)
    except BadSignature:
        return None


def _verify_basic(credentials: HTTPBasicCredentials) -> bool:
    valid_user = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.auth_user.encode("utf-8"),
    )
    valid_pass = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.auth_password.encode("utf-8"),
    )
    return valid_user and valid_pass


async def require_auth(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:
    # 1. Signed cookie (browser sessions)
    cookie = request.cookies.get(_COOKIE_NAME)
    if cookie:
        user = _decode_cookie(cookie)
        if user:
            return user

    # 2. HTTP Basic (API clients and tests)
    if credentials and _verify_basic(credentials):
        return credentials.username

    # 3. Redirect browsers to login, send 401 to API clients
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
