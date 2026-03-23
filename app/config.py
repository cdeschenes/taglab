from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_libraries(raw: str, default_path: Path) -> list[dict]:
    """Parse LIBRARIES env var: '/path1:Label1,/path2:Label2'."""
    if not raw.strip():
        return [{"path": default_path, "label": "Library"}]
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        sep = part.rfind(":")
        if sep > 0:
            path_str = part[:sep].strip()
            label = part[sep + 1:].strip() or Path(part[:sep]).name
        else:
            path_str = part
            label = Path(part).name or "Library"
        result.append({"path": Path(path_str), "label": label})
    return result or [{"path": default_path, "label": "Library"}]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    media_path: Path = Path("/media")
    cache_path: Path = Path("/cache")

    auth_user: str = "admin"
    auth_password: str = "changeme"
    secret_key: str = "changeme-set-SECRET_KEY-in-env"

    organize_target: Optional[Path] = None
    organize_pattern: str = "{album_artist_first}/{year} - {album}/{track:02d} - {title}.flac"

    navidrome_url: Optional[str] = None
    navidrome_user: Optional[str] = None
    navidrome_password: Optional[str] = None

    lastfm_api_key: Optional[str] = None

    allow_delete: bool = False

    libraries_raw: str = Field(default="", alias="LIBRARIES")
    organize_cleanup_patterns_raw: str = Field(
        default="._*,*.bak,.DS_Store,Thumbs.db",
        alias="ORGANIZE_CLEANUP_PATTERNS",
    )


settings = Settings()

# Active library state (mutated on switch; resets to index 0 on restart).
_libraries: list[dict] = _parse_libraries(settings.libraries_raw, settings.media_path)

# Parse cleanup patterns from comma-separated string.
organize_cleanup_patterns: list[str] = [
    p.strip() for p in settings.organize_cleanup_patterns_raw.split(",") if p.strip()
]
_active_library_idx: int = 0

# Initialise settings.media_path to the first library.
settings.media_path = _libraries[0]["path"]


def get_libraries() -> list[dict]:
    return _libraries


def get_active_library_idx() -> int:
    return _active_library_idx


def set_active_library(idx: int) -> None:
    global _active_library_idx
    _active_library_idx = idx
    settings.media_path = _libraries[idx]["path"]
