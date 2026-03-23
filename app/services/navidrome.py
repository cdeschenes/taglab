"""Navidrome API integration — trigger library rescan."""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings


async def trigger_scan(full: bool = False) -> dict:
    """
    Trigger a Navidrome library scan.
    Navidrome uses the Subsonic API; scanner is triggered via /rest/startScan.
    Returns {"ok": bool, "message": str}.
    """
    if not settings.navidrome_url:
        return {"ok": False, "message": "Navidrome not configured"}

    base = settings.navidrome_url.rstrip("/")
    params = {
        "u": settings.navidrome_user,
        "p": settings.navidrome_password,
        "c": "TagLab",
        "v": "1.16.1",
        "f": "json",
        "fullScan": "true" if full else "false",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/rest/startScan", params=params)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("subsonic-response", {}).get("status", "")
            if status == "ok":
                return {"ok": True, "message": "Navidrome scan triggered"}
            return {"ok": False, "message": f"Navidrome returned: {status}"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"HTTP error: {e}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
