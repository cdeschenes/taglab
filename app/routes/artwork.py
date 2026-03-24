import asyncio
import hashlib
import io
import json
import re as _re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from PIL import Image

from app.auth import require_auth
from app.config import settings
from app.services import flac as flac_svc
from app.services import library_cache

router = APIRouter()

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_COVER_NAMES = {"cover.jpg", "folder.jpg"}


def _thumb_cache_path(flac_path: Path, size: int) -> Path:
    key = hashlib.sha256(f"{flac_path}:{size}".encode()).hexdigest()
    return settings.cache_path / "thumbs" / key[:2] / f"{key}.jpg"


def _info_cache_path(flac_path: Path) -> Path:
    key = hashlib.sha256(f"{flac_path}:info".encode()).hexdigest()
    return settings.cache_path / "thumbs" / key[:2] / f"{key}.json"


def _cache_valid(cache_file: Path, flac_file: Path) -> bool:
    return cache_file.exists() and cache_file.stat().st_mtime >= flac_file.stat().st_mtime


def _write_cover_file(folder: Path, image_data: bytes, preferred_name: str = "cover.jpg") -> None:
    """Write cover art as a JPEG in the album directory.

    Any existing cover.jpg or folder.jpg is renamed to <stem>.bak before writing,
    ensuring only one *.jpg exists in the directory afterward.
    """
    target_name = preferred_name.lower()
    if target_name not in _COVER_NAMES:
        target_name = "cover.jpg"

    for name in _COVER_NAMES:
        existing = folder / name
        if existing.exists():
            existing.unlink()

    target = folder / target_name
    try:
        img = Image.open(io.BytesIO(image_data))
        img.convert("RGB").save(str(target), format="JPEG", quality=95, optimize=True)
    except Exception:
        # Fallback: write raw bytes (e.g. if source is already JPEG)
        target.write_bytes(image_data)


def _flac_file(path: str) -> Path:
    f = flac_svc.validate_media_path(path, settings.media_path)
    if not f.is_file() or f.suffix.lower() != ".flac":
        raise HTTPException(status_code=400, detail="Not a FLAC file")
    return f


@router.get("/api/artwork")
async def get_artwork(path: str, _: str = Depends(require_auth)):
    f = _flac_file(path)
    data, mime = flac_svc.get_cover_bytes(f)
    return Response(content=data, media_type=mime)


@router.get("/api/artwork/info")
async def get_artwork_info(path: str, _: str = Depends(require_auth)):
    """Return dimensions and file size of the embedded cover art without sending pixel data."""
    f = _flac_file(path)
    cache_file = _info_cache_path(f)
    if _cache_valid(cache_file, f):
        return json.loads(cache_file.read_text())
    data, mime = flac_svc.get_cover_bytes(f)
    img = Image.open(io.BytesIO(data))
    info = {"width": img.width, "height": img.height, "mime": mime, "bytes": len(data)}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(info))
    return info


@router.get("/api/artwork/thumbnail")
async def get_artwork_thumbnail(
    path: str,
    size: int = Query(default=160, ge=32, le=800),
    _: str = Depends(require_auth),
):
    f = _flac_file(path)
    cache_file = _thumb_cache_path(f, size)
    if _cache_valid(cache_file, f):
        return FileResponse(str(cache_file), media_type="image/jpeg")
    data, _ = flac_svc.get_cover_bytes(f)
    img = Image.open(io.BytesIO(data))
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(buf.getvalue())
    return Response(content=buf.getvalue(), media_type="image/jpeg")


@router.post("/api/artwork/upload")
async def upload_artwork(
    paths: str = Form(...),
    file: UploadFile = File(...),
    cover_filename: str = Form(default="cover.jpg"),
    _: str = Depends(require_auth),
):
    """
    Upload cover art and apply it to one or more FLAC files.
    `paths` is a JSON-encoded list of relative file paths.
    Also writes a cover.jpg / folder.jpg to the album directory.
    """
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {file.content_type}")

    image_data = await file.read()
    if len(image_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        path_list: list[str] = json.loads(paths)
    except (ValueError, TypeError):
        path_list = [paths]

    img = Image.open(io.BytesIO(image_data))
    cover_w, cover_h = img.width, img.height

    updated: list[str] = []
    album_dirs: set[Path] = set()
    conn = library_cache.get_db(settings.media_path)
    for p in path_list:
        f = _flac_file(p)
        flac_svc.write_cover(f, image_data, file.content_type)
        library_cache.update_cover_dimensions(conn, str(f), True, cover_w, cover_h)
        updated.append(f.name)
        album_dirs.add(f.parent)

    for folder in album_dirs:
        _write_cover_file(folder, image_data, cover_filename)

    return {"ok": True, "updated": updated}


class FromUrlPayload(BaseModel):
    url: str
    paths: list[str]
    cover_filename: str = "cover.jpg"


@router.post("/api/artwork/from-url")
async def upload_artwork_from_url(
    payload: FromUrlPayload,
    _: str = Depends(require_auth),
):
    """Fetch cover art from a URL (server-side) and apply to FLAC files.
    Also writes a cover.jpg / folder.jpg to the album directory.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(payload.url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}")

    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {content_type}")

    image_data = resp.content
    if len(image_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    img = Image.open(io.BytesIO(image_data))
    cover_w, cover_h = img.width, img.height

    updated: list[str] = []
    album_dirs: set[Path] = set()
    conn = library_cache.get_db(settings.media_path)
    for p in payload.paths:
        f = _flac_file(p)
        flac_svc.write_cover(f, image_data, content_type)
        library_cache.update_cover_dimensions(conn, str(f), True, cover_w, cover_h)
        updated.append(f.name)
        album_dirs.add(f.parent)

    for folder in album_dirs:
        _write_cover_file(folder, image_data, payload.cover_filename)

    return {"ok": True, "updated": updated}


@router.delete("/api/artwork")
async def delete_artwork(path: str, _: str = Depends(require_auth)):
    f = _flac_file(path)
    flac_svc.remove_cover(f)
    conn = library_cache.get_db(settings.media_path)
    library_cache.update_cover_dimensions(conn, str(f), False, None, None)
    return {"ok": True}


@router.get("/api/artwork/artist-photo")
async def artist_photo(folder: str, _: str = Depends(require_auth)):
    """Serve artist.jpg (or variant) from the artist's root media folder."""
    artist_folder = flac_svc.validate_media_path(folder, settings.media_path)
    for name in ("artist.jpg", "artist.png", "artist.jpeg", "artist.webp"):
        p = artist_folder / name
        if p.exists():
            return FileResponse(p)
    raise HTTPException(status_code=404, detail="No artist image found")


_ARTIST_IMAGE_NAMES = ("artist.jpg", "artist.png", "artist.jpeg", "artist.webp")


_DEEZER_NO_IMAGE = "artist//"  # placeholder URLs contain this double-slash


@router.get("/api/artist-photo/search")
async def search_artist_photos(artist: str, _: str = Depends(require_auth)):
    """Search Deezer and iTunes for artist photos."""
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                  headers={"User-Agent": "TagLab/1.0"}) as client:

        async def _deezer() -> None:
            try:
                r = await client.get("https://api.deezer.com/search/artist",
                    params={"q": artist, "limit": 10})
                for item in r.json().get("data", []):
                    xl = item.get("picture_xl") or item.get("picture_big") or ""
                    thumb = item.get("picture_medium") or item.get("picture_small") or xl
                    # Skip Deezer placeholder images (URL contains artist// with no ID)
                    if xl and _DEEZER_NO_IMAGE not in xl:
                        results.append({"thumbnail": thumb, "full": xl})
            except Exception:
                pass

        async def _itunes() -> None:
            try:
                r = await client.get("https://itunes.apple.com/search",
                    params={"term": artist, "media": "music", "entity": "musicArtist", "limit": 10})
                for item in r.json().get("results", []):
                    art = item.get("artistLinkUrl", "")
                    # iTunes musicArtist search doesn't return images directly;
                    # but artist album art URLs can be derived from artworkUrl100
                    img = item.get("artworkUrl100", "")
                    if img:
                        full = img.replace("100x100bb", "600x600bb")
                        thumb = img.replace("100x100bb", "150x150bb")
                        results.append({"thumbnail": thumb, "full": full})
            except Exception:
                pass

        await asyncio.gather(_deezer(), _itunes())

    return results[:20]


class ArtistPhotoPayload(BaseModel):
    artist: str
    url: str
    folder: str


@router.post("/api/artist-photo/save")
async def save_artist_photo(payload: ArtistPhotoPayload, _: str = Depends(require_auth)):
    """Download an image URL and save as artist.jpg in the artist's media folder.
    Any existing artist.* is deleted first.
    """
    artist_folder = flac_svc.validate_media_path(payload.folder, settings.media_path)

    for name in _ARTIST_IMAGE_NAMES:
        p = artist_folder / name
        if p.exists():
            p.unlink()

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(payload.url, headers={"User-Agent": "TagLab/1.0"})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch image: {exc}")

    dest = artist_folder / "artist.jpg"
    dest.write_bytes(resp.content)

    local_url = f"/api/artwork/artist-photo?folder={artist_folder}"
    return {"ok": True, "local_url": local_url}


@router.get("/api/covers/search")
async def search_covers(
    artist: str = "",
    album: str = "",
    _: str = Depends(require_auth),
):
    """Search iTunes, Deezer, MusicBrainz CAA, and Bandcamp for album covers."""
    query = f"{artist} {album}".strip()
    covers: list[dict] = []

    async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                  headers={"User-Agent": "TagLab/1.0"}) as client:

        async def _itunes():
            try:
                r = await client.get("https://itunes.apple.com/search",
                    params={"term": query, "media": "music", "entity": "album", "limit": 8})
                for item in r.json().get("results", []):
                    art = item.get("artworkUrl100", "")
                    if art:
                        full = art.replace("100x100bb", "600x600bb")
                        thumb = art.replace("100x100bb", "150x150bb")
                        covers.append({"thumbnail": thumb, "image": full,
                            "release": item.get("collectionName", ""),
                            "artist": item.get("artistName", ""), "source": "iTunes",
                            "dims": "600×600", "format": "JPEG"})
            except Exception:
                pass

        async def _deezer():
            try:
                r = await client.get("https://api.deezer.com/search/album",
                    params={"q": query, "limit": 8})
                for item in r.json().get("data", []):
                    xl = item.get("cover_xl") or item.get("cover_big")
                    thumb = item.get("cover_medium") or item.get("cover_small")
                    if xl:
                        covers.append({"thumbnail": thumb, "image": xl,
                            "release": item.get("title", ""),
                            "artist": item.get("artist", {}).get("name", ""),
                            "source": "Deezer",
                            "dims": "1000×1000", "format": "JPEG"})
            except Exception:
                pass

        async def _caa():
            try:
                from app.services import musicbrainz as mb_svc
                releases = mb_svc.search_releases(artist=artist, album=album)
                for release in releases[:5]:
                    mbid = release.get("id")
                    if not mbid:
                        continue
                    try:
                        r = await client.get(f"https://coverartarchive.org/release/{mbid}")
                        if r.status_code != 200:
                            continue
                        for img in r.json().get("images", []):
                            if img.get("front"):
                                thumbs = img.get("thumbnails", {})
                                covers.append({
                                    "thumbnail": thumbs.get("250") or img["image"],
                                    "image": img["image"],
                                    "release": release.get("title", ""),
                                    "artist": release.get("artist-credit-phrase", ""),
                                    "source": "MusicBrainz",
                                    "dims": "", "format": "JPEG"})
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        async def _bandcamp():
            try:
                r = await client.get("https://bandcamp.com/search",
                    params={"q": query, "item_type": "a"})
                ids = dict.fromkeys(
                    _re.findall(r'bcbits\.com/img/a(\d+)_\d+\.jpg', r.text))
                for img_id in list(ids)[:8]:
                    base = f"https://f4.bcbits.com/img/a{img_id}"
                    covers.append({"thumbnail": f"{base}_7.jpg",
                        "image": f"{base}_10.jpg",
                        "release": "", "artist": "", "source": "Bandcamp",
                        "dims": "", "format": "JPEG"})
            except Exception:
                pass

        await asyncio.gather(_itunes(), _deezer(), _caa(), _bandcamp())

        # Probe dimensions for covers that don't have them (MusicBrainz, Bandcamp)
        async def _probe_dims(cover: dict) -> None:
            try:
                r = await client.get(cover["image"], headers={"Range": "bytes=0-65535"})
                img = Image.open(io.BytesIO(r.content))
                cover["dims"] = f"{img.width}\u00d7{img.height}"
            except Exception:
                pass

        await asyncio.gather(*[_probe_dims(c) for c in covers if not c.get("dims")])

    def _pixel_area(c: dict) -> int:
        dims = c.get("dims", "")
        if not dims:
            return 0
        try:
            w, h = dims.split("\u00d7")
            return int(w) * int(h)
        except Exception:
            return 0

    covers.sort(key=_pixel_area, reverse=True)
    return covers
