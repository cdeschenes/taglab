# Set env vars before any app module is imported (pydantic-settings reads at import time)
import os
os.environ.setdefault("AUTH_USER", "admin")
os.environ.setdefault("AUTH_PASSWORD", "testpass")
os.environ.setdefault("MEDIA_PATH", "/tmp/taglab_tests")

import subprocess
from pathlib import Path

import pytest
from mutagen.flac import FLAC


# ── FLAC file factory ──────────────────────────────────────────────────────────

def make_flac(path: Path, tags: dict | None = None) -> Path:
    """Create a minimal valid 0.5-second FLAC file with optional tags."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "quiet",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:a", "flac", str(path),
        ],
        check=True,
    )
    if tags:
        audio = FLAC(str(path))
        for k, v in tags.items():
            audio[k] = [str(v)]
        audio.save()
    return path


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_flac(tmp_path) -> Path:
    """Single FLAC file with no tags."""
    return make_flac(tmp_path / "test.flac")


@pytest.fixture
def tagged_flac(tmp_path) -> Path:
    """Single FLAC file with a standard set of tags."""
    return make_flac(
        tmp_path / "01 - Song.flac",
        {
            "title": "Song",
            "artist": "Artist",
            "albumartist": "Artist",
            "album": "Record",
            "tracknumber": "1",
            "date": "2024",
            "genre": "Rock",
        },
    )


@pytest.fixture
def album_dir(tmp_path) -> Path:
    """
    Fake album folder:
      tmp_path/
        Test Artist/
          Test Album/
            01 - Track One.flac
            02 - Track Two.flac
    """
    folder = tmp_path / "Test Artist" / "Test Album"
    make_flac(
        folder / "01 - Track One.flac",
        {
            "title": "Track One",
            "artist": "Test Artist",
            "albumartist": "Test Artist",
            "album": "Test Album",
            "tracknumber": "1",
            "date": "2024",
            "genre": "Rock",
        },
    )
    make_flac(
        folder / "02 - Track Two.flac",
        {
            "title": "Track Two",
            "artist": "Test Artist",
            "albumartist": "Test Artist",
            "album": "Test Album",
            "tracknumber": "2",
            "date": "2024",
            "genre": "Rock",
        },
    )
    return folder


@pytest.fixture
def media_root(tmp_path, album_dir) -> Path:
    """Media root containing one artist/album."""
    # album_dir is already under tmp_path via the fixture chain
    return tmp_path


@pytest.fixture
def api_client(media_root, monkeypatch):
    """FastAPI TestClient authenticated and pointed at a temp media root."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "media_path", media_root)
    monkeypatch.setattr(cfg.settings, "auth_user", "admin")
    monkeypatch.setattr(cfg.settings, "auth_password", "testpass")
    monkeypatch.setattr(cfg.settings, "organize_target", None)
    monkeypatch.setattr(cfg.settings, "navidrome_url", None)

    import base64
    auth = base64.b64encode(b"admin:testpass").decode()

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, headers={"Authorization": f"Basic {auth}"})
