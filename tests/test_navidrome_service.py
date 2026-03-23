"""Tests for app/services/navidrome.py"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import navidrome as navi_svc


class TestTriggerScan:
    async def test_not_configured_returns_not_ok(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "navidrome_url", None)
        result = await navi_svc.trigger_scan()
        assert result["ok"] is False
        assert "not configured" in result["message"].lower()

    async def test_success(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "navidrome_url", "http://navidrome:4533")
        monkeypatch.setattr(cfg.settings, "navidrome_user", "admin")
        monkeypatch.setattr(cfg.settings, "navidrome_password", "pass")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"subsonic-response": {"status": "ok"}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await navi_svc.trigger_scan(full=False)

        assert result["ok"] is True
        assert "triggered" in result["message"].lower()

    async def test_http_error_returns_not_ok(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "navidrome_url", "http://navidrome:4533")
        monkeypatch.setattr(cfg.settings, "navidrome_user", "admin")
        monkeypatch.setattr(cfg.settings, "navidrome_password", "pass")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await navi_svc.trigger_scan()

        assert result["ok"] is False
        assert "HTTP error" in result["message"] or "refused" in result["message"]

    async def test_bad_subsonic_status(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "navidrome_url", "http://navidrome:4533")
        monkeypatch.setattr(cfg.settings, "navidrome_user", "admin")
        monkeypatch.setattr(cfg.settings, "navidrome_password", "pass")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"subsonic-response": {"status": "failed"}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await navi_svc.trigger_scan()

        assert result["ok"] is False
        assert "failed" in result["message"]
