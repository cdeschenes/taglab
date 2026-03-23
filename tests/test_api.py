"""Integration tests for FastAPI routes via TestClient."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_flac


# ── Auth ───────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_index_requires_auth(self, api_client):
        from app.main import app
        unauthed = TestClient(app)
        resp = unauthed.get("/")
        assert resp.status_code == 401

    def test_index_rejects_wrong_password(self, api_client):
        import base64
        from app.main import app
        bad_auth = base64.b64encode(b"admin:wrongpassword").decode()
        wrong = TestClient(app, headers={"Authorization": f"Basic {bad_auth}"})
        resp = wrong.get("/")
        assert resp.status_code == 401

    def test_index_ok_with_correct_credentials(self, api_client):
        resp = api_client.get("/")
        assert resp.status_code == 200
        assert "TagLab" in resp.text


# ── Explorer ───────────────────────────────────────────────────────────────────

class TestExplorer:
    def test_explorer_lists_artists(self, api_client):
        resp = api_client.get("/ui/explorer")
        assert resp.status_code == 200
        assert "Test Artist" in resp.text

    def test_albums_lists_albums(self, api_client):
        resp = api_client.get("/ui/albums", params={"artist": "Test Artist"})
        assert resp.status_code == 200
        assert "Test Album" in resp.text

    def test_albums_404_for_missing_artist(self, api_client):
        resp = api_client.get("/ui/albums", params={"artist": "Nobody"})
        assert resp.status_code == 404

    def test_albums_403_for_traversal(self, api_client):
        resp = api_client.get("/ui/albums", params={"artist": "../../../etc"})
        assert resp.status_code in (403, 404)


# ── Album editor ───────────────────────────────────────────────────────────────

class TestAlbumEditor:
    def test_loads_album_editor(self, api_client, album_dir):
        rel = str(album_dir.relative_to(album_dir.parent.parent))
        resp = api_client.get("/ui/album", params={"path": rel})
        assert resp.status_code == 200
        assert "Test Album" in resp.text
        assert "Track One" in resp.text
        assert "Track Two" in resp.text

    def test_album_editor_absolute_path(self, api_client, album_dir):
        resp = api_client.get("/ui/album", params={"path": str(album_dir)})
        assert resp.status_code == 200

    def test_album_empty_folder_shows_error(self, api_client, media_root):
        empty = media_root / "Empty Artist" / "Empty Album"
        empty.mkdir(parents=True)
        resp = api_client.get("/ui/album", params={"path": str(empty)})
        assert resp.status_code == 200
        assert "No FLAC files found" in resp.text


# ── Album preview & save ───────────────────────────────────────────────────────

class TestAlbumSave:
    def _build_payload(self, album_dir: Path) -> dict:
        from app.services.flac import list_flac_files, read_tags
        files = list_flac_files(album_dir)
        return {
            "path": str(album_dir),
            "shared_tags": {"genre": "Jazz"},
            "tracks": [
                {"path": str(f), "tags": read_tags(f)["tags"]}
                for f in files
            ],
        }

    def test_preview_returns_diff(self, api_client, album_dir):
        payload = self._build_payload(album_dir)
        resp = api_client.post("/api/album/preview", json=payload)
        assert resp.status_code == 200
        # Genre is changing from Rock → Jazz
        assert "Jazz" in resp.text
        assert "Rock" in resp.text

    def test_save_writes_tags(self, api_client, album_dir):
        payload = self._build_payload(album_dir)
        resp = api_client.post("/api/album/save", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 2

        # Verify on disk
        from app.services.flac import list_flac_files, read_tags
        for f in list_flac_files(album_dir):
            assert read_tags(f)["tags"].get("genre") == "Jazz"


# ── Single track ───────────────────────────────────────────────────────────────

class TestTrackEditor:
    def _first_track(self, album_dir: Path) -> Path:
        from app.services.flac import list_flac_files
        return list_flac_files(album_dir)[0]

    def test_track_editor_loads(self, api_client, album_dir):
        track = self._first_track(album_dir)
        resp = api_client.get("/ui/track", params={"path": str(track)})
        assert resp.status_code == 200
        assert "Track One" in resp.text

    def test_get_track_json(self, api_client, album_dir):
        track = self._first_track(album_dir)
        resp = api_client.get("/api/track", params={"path": str(track)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"]["title"] == "Track One"

    def test_save_track(self, api_client, album_dir):
        track = self._first_track(album_dir)
        payload = {
            "path": str(track),
            "tags": {"title": "New Title", "artist": "New Artist"},
        }
        resp = api_client.post("/api/track/save", json=payload)
        assert resp.status_code == 200

        from app.services.flac import read_tags
        assert read_tags(track)["tags"]["title"] == "New Title"

    def test_track_path_traversal_blocked(self, api_client):
        resp = api_client.get("/api/track", params={"path": "../../../etc/passwd"})
        assert resp.status_code == 403


# ── Artwork ────────────────────────────────────────────────────────────────────

class TestArtwork:
    FAKE_PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def _first_track(self, album_dir: Path) -> Path:
        from app.services.flac import list_flac_files
        return list_flac_files(album_dir)[0]

    def test_upload_cover_to_single_file(self, api_client, album_dir):
        track = self._first_track(album_dir)
        paths_json = json.dumps([str(track)])
        resp = api_client.post(
            "/api/artwork/upload",
            data={"paths": paths_json},
            files={"file": ("cover.png", self.FAKE_PNG, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        from app.services.flac import read_tags
        assert read_tags(track)["has_cover"] is True

    def test_upload_cover_to_all_tracks(self, api_client, album_dir):
        from app.services.flac import list_flac_files
        files = list_flac_files(album_dir)
        paths_json = json.dumps([str(f) for f in files])
        resp = api_client.post(
            "/api/artwork/upload",
            data={"paths": paths_json},
            files={"file": ("cover.png", self.FAKE_PNG, "image/png")},
        )
        assert resp.status_code == 200
        assert len(resp.json()["updated"]) == 2

    def test_delete_cover(self, api_client, album_dir):
        track = self._first_track(album_dir)
        # First add cover
        from app.services.flac import write_cover
        write_cover(track, self.FAKE_PNG, "image/png")

        resp = api_client.delete("/api/artwork", params={"path": str(track)})
        assert resp.status_code == 200

        from app.services.flac import read_tags
        assert read_tags(track)["has_cover"] is False

    def test_get_artwork(self, api_client, album_dir):
        track = self._first_track(album_dir)
        from app.services.flac import write_cover
        write_cover(track, self.FAKE_PNG, "image/png")

        resp = api_client.get("/api/artwork", params={"path": str(track)})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")

    def test_get_artwork_404_when_none(self, api_client, album_dir):
        track = self._first_track(album_dir)
        resp = api_client.get("/api/artwork", params={"path": str(track)})
        assert resp.status_code == 404

    def test_upload_rejects_invalid_mime(self, api_client, album_dir):
        track = self._first_track(album_dir)
        resp = api_client.post(
            "/api/artwork/upload",
            data={"paths": json.dumps([str(track)])},
            files={"file": ("cover.gif", b"GIF89a", "image/gif")},
        )
        assert resp.status_code == 415


# ── Navidrome (disabled by default in api_client fixture) ─────────────────────

class TestNavidrome:
    def test_scan_returns_400_when_not_configured(self, api_client):
        resp = api_client.post("/api/navidrome/scan", json={"full": False})
        assert resp.status_code == 400


# ── Organizer (disabled by default in api_client fixture) ─────────────────────

class TestOrganizer:
    def test_preview_returns_400_when_not_configured(self, api_client, album_dir):
        from app.services.flac import list_flac_files
        files = [str(f) for f in list_flac_files(album_dir)]
        resp = api_client.post("/api/organizer/preview", json={"paths": files})
        assert resp.status_code == 400

    def test_apply_returns_400_when_not_configured(self, api_client, album_dir):
        from app.services.flac import list_flac_files
        files = [str(f) for f in list_flac_files(album_dir)]
        moves = [{"source": f, "target": f} for f in files]
        resp = api_client.post("/api/organizer/apply", json={"moves": moves})
        assert resp.status_code == 400

    def test_preview_returns_html_when_configured(self, media_root, album_dir, monkeypatch, tmp_path):
        import base64
        import app.config as cfg
        organize_target = tmp_path / "organized"
        monkeypatch.setattr(cfg.settings, "media_path", media_root)
        monkeypatch.setattr(cfg.settings, "auth_user", "admin")
        monkeypatch.setattr(cfg.settings, "auth_password", "testpass")
        monkeypatch.setattr(cfg.settings, "organize_target", organize_target)
        monkeypatch.setattr(cfg.settings, "organize_pattern", "{albumartist}/{album}/{title}")

        from fastapi.testclient import TestClient
        from app.main import app
        auth = base64.b64encode(b"admin:testpass").decode()
        client = TestClient(app, headers={"Authorization": f"Basic {auth}"})

        from app.services.flac import list_flac_files
        files = [str(f) for f in list_flac_files(album_dir)]
        resp = client.post("/api/organizer/preview", json={"paths": files})
        assert resp.status_code == 200
        assert "Track One" in resp.text or "Track Two" in resp.text

    def test_apply_moves_files(self, media_root, album_dir, monkeypatch, tmp_path):
        import base64
        import app.config as cfg
        organize_target = tmp_path / "organized"
        monkeypatch.setattr(cfg.settings, "media_path", media_root)
        monkeypatch.setattr(cfg.settings, "cache_path", tmp_path / "cache")
        monkeypatch.setattr(cfg.settings, "auth_user", "admin")
        monkeypatch.setattr(cfg.settings, "auth_password", "testpass")
        monkeypatch.setattr(cfg.settings, "organize_target", organize_target)

        from fastapi.testclient import TestClient
        from app.main import app
        auth = base64.b64encode(b"admin:testpass").decode()
        client = TestClient(app, headers={"Authorization": f"Basic {auth}"})

        from app.services.flac import list_flac_files
        files = list_flac_files(album_dir)
        target_dir = organize_target / "Test Artist" / "Test Album"
        moves = [
            {"source": str(f), "target": str(target_dir / f.name)}
            for f in files
        ]
        resp = client.post("/api/organizer/apply", json={"moves": moves})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert all(r["ok"] for r in data["results"])


# ── ReplayGain ─────────────────────────────────────────────────────────────────

class TestReplayGain:
    def test_calculate_returns_html_preview(self, api_client, album_dir, monkeypatch):
        from app.services.flac import list_flac_files
        files = list_flac_files(album_dir)

        fake_results = [
            {
                "path": str(f),
                "filename": f.name,
                "lufs": -14.5,
                "tags": {"REPLAYGAIN_TRACK_GAIN": "-3.50 dB", "REPLAYGAIN_ALBUM_GAIN": "-3.50 dB"},
            }
            for f in files
        ]
        import app.services.replaygain as rg_svc
        monkeypatch.setattr(rg_svc, "calculate_replaygain", lambda paths, album_mode=True: fake_results)

        resp = api_client.post(
            "/api/replaygain/calculate",
            json={"paths": [str(f) for f in files], "album_mode": True},
        )
        assert resp.status_code == 200

    def test_calculate_returns_500_on_ffmpeg_error(self, api_client, album_dir, monkeypatch):
        from app.services.flac import list_flac_files
        files = list_flac_files(album_dir)

        import app.services.replaygain as rg_svc
        monkeypatch.setattr(rg_svc, "calculate_replaygain", lambda paths, album_mode=True: (_ for _ in ()).throw(RuntimeError("ffmpeg failed")))

        resp = api_client.post(
            "/api/replaygain/calculate",
            json={"paths": [str(f) for f in files], "album_mode": True},
        )
        assert resp.status_code == 500

    def test_calculate_returns_400_for_empty_paths(self, api_client):
        resp = api_client.post("/api/replaygain/calculate", json={"paths": []})
        assert resp.status_code == 400

    def test_apply_writes_tags(self, api_client, album_dir):
        from app.services.flac import list_flac_files, read_tags
        track = list_flac_files(album_dir)[0]
        results = [{"path": str(track), "tags": {"replaygain_track_gain": "-6.00 dB"}}]
        resp = api_client.post("/api/replaygain/apply", json={"results": results})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["updated"]) == 1
        assert read_tags(track)["tags"].get("replaygain_track_gain") == "-6.00 dB"


# ── MusicBrainz ────────────────────────────────────────────────────────────────

class TestMusicBrainz:
    FAKE_RELEASES = [
        {"mbid": "abc-123", "title": "Abbey Road", "artist": "The Beatles", "date": "1969", "tracks": 17}
    ]
    FAKE_RELEASE = {
        "mbid": "abc-123",
        "title": "Abbey Road",
        "artist": "The Beatles",
        "date": "1969",
        "tracks": [{"number": 1, "title": "Come Together", "length": "4:19"}],
    }

    def test_search_returns_html(self, api_client, monkeypatch):
        import app.services.musicbrainz as mb_svc
        monkeypatch.setattr(mb_svc, "search_releases", lambda artist, album, limit=10: self.FAKE_RELEASES)

        resp = api_client.get("/ui/musicbrainz/search", params={"artist": "Beatles", "album": "Abbey Road"})
        assert resp.status_code == 200
        assert "Abbey Road" in resp.text

    def test_search_empty_query_returns_html(self, api_client):
        resp = api_client.get("/ui/musicbrainz/search")
        assert resp.status_code == 200

    def test_search_handles_runtime_error(self, api_client, monkeypatch):
        import app.services.musicbrainz as mb_svc
        monkeypatch.setattr(mb_svc, "search_releases", lambda artist, album, limit=10: (_ for _ in ()).throw(RuntimeError("network error")))

        resp = api_client.get("/ui/musicbrainz/search", params={"artist": "x"})
        assert resp.status_code == 200
        assert "network error" in resp.text

    def test_get_release_returns_json(self, api_client, monkeypatch):
        import app.services.musicbrainz as mb_svc
        monkeypatch.setattr(mb_svc, "get_release", lambda mbid: self.FAKE_RELEASE)

        resp = api_client.get("/api/musicbrainz/release/abc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Abbey Road"

    def test_get_release_returns_502_on_error(self, api_client, monkeypatch):
        import app.services.musicbrainz as mb_svc
        monkeypatch.setattr(mb_svc, "get_release", lambda mbid: (_ for _ in ()).throw(RuntimeError("MB down")))

        resp = api_client.get("/api/musicbrainz/release/bad-mbid")
        assert resp.status_code == 502
