"""Server-side persistence for organizer patterns."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings

router = APIRouter()


def _patterns_file() -> Path:
    return settings.cache_path / "organizer_patterns.json"


def _load() -> list[dict]:
    p = _patterns_file()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return []
    return []


def _save(patterns: list[dict]) -> None:
    p = _patterns_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(patterns))


class PatternPayload(BaseModel):
    name: str
    pattern: str


@router.get("/api/patterns")
async def list_patterns(_: str = Depends(require_auth)):
    return _load()


@router.post("/api/patterns")
async def save_pattern(payload: PatternPayload, _: str = Depends(require_auth)):
    patterns = [p for p in _load() if p["name"] != payload.name]
    patterns.append({"name": payload.name, "pattern": payload.pattern})
    _save(patterns)
    return {"ok": True}


@router.delete("/api/patterns/{name}")
async def delete_pattern(name: str, _: str = Depends(require_auth)):
    _save([p for p in _load() if p["name"] != name])
    return {"ok": True}
