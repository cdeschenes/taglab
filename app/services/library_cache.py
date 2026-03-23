"""SQLite-backed library index for fast filesystem browsing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from mutagen.flac import FLAC

from app.config import settings

_connections: dict[str, sqlite3.Connection] = {}
_connections_lock = threading.Lock()

# Shared mutable scan state — single-user app, no concurrency concerns.
_scan_state: dict = {"status": "idle", "done": 0, "total": 0, "started": 0.0}


def _db_path(media_path: Path) -> Path:
    h = hashlib.sha256(str(media_path.resolve()).encode()).hexdigest()[:16]
    return settings.cache_path / f"library_{h}.db"


def get_db(media_path: Path) -> sqlite3.Connection:
    key = str(media_path)
    with _connections_lock:
        if key not in _connections:
            db_file = _db_path(media_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_file), check_same_thread=False, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            _init_schema(conn)
            _connections[key] = conn
    return _connections[key]


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            path        TEXT PRIMARY KEY,
            mtime       REAL NOT NULL,
            artist_dir  TEXT NOT NULL,
            album_dir   TEXT NOT NULL,
            filename    TEXT NOT NULL,
            has_cover   INTEGER NOT NULL DEFAULT 0,
            cover_w     INTEGER,
            cover_h     INTEGER,
            sample_rate INTEGER,
            bits        INTEGER,
            channels    INTEGER,
            duration    REAL,
            tags_json   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_album ON tracks(artist_dir, album_dir)")
    conn.commit()


def get_cached_track(conn: sqlite3.Connection, path: str, mtime: float) -> dict | None:
    row = conn.execute("SELECT * FROM tracks WHERE path = ?", (path,)).fetchone()
    if row and abs(row["mtime"] - mtime) < 0.001:
        return dict(row)
    return None


def upsert_track(conn: sqlite3.Connection, path: str, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO tracks
           (path, mtime, artist_dir, album_dir, filename, has_cover, cover_w, cover_h,
            sample_rate, bits, channels, duration, tags_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            path,
            data["mtime"],
            data["artist_dir"],
            data["album_dir"],
            data["filename"],
            1 if data.get("has_cover") else 0,
            data.get("cover_w"),
            data.get("cover_h"),
            data.get("sample_rate"),
            data.get("bits"),
            data.get("channels"),
            data.get("duration"),
            json.dumps(data.get("tags", {})),
        ),
    )
    conn.commit()


def get_all_albums(conn: sqlite3.Connection) -> list[dict]:
    """Return one dict per album, ordered by artist then album name."""
    rows = conn.execute(
        """SELECT artist_dir, album_dir,
                  MIN(path) AS first_flac,
                  COUNT(*) AS track_count,
                  MAX(has_cover) AS has_cover
           FROM tracks
           GROUP BY artist_dir, album_dir
           ORDER BY artist_dir COLLATE NOCASE, album_dir COLLATE NOCASE"""
    ).fetchall()
    result = []
    for row in rows:
        all_flacs = conn.execute(
            "SELECT path FROM tracks WHERE artist_dir = ? AND album_dir = ? ORDER BY filename",
            (row["artist_dir"], row["album_dir"]),
        ).fetchall()
        result.append({
            "artist": row["artist_dir"],
            "album": row["album_dir"],
            "first_flac": row["first_flac"],
            "all_flacs": [r["path"] for r in all_flacs],
            "track_count": row["track_count"],
            "has_cover": bool(row["has_cover"]),
        })
    return result


def get_artists(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT artist_dir FROM tracks ORDER BY artist_dir COLLATE NOCASE"
    ).fetchall()
    return [r["artist_dir"] for r in rows]


def get_albums_for_artist(conn: sqlite3.Connection, artist_dir: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT album_dir FROM tracks WHERE artist_dir = ? ORDER BY album_dir COLLATE NOCASE",
        (artist_dir,),
    ).fetchall()
    return [r["album_dir"] for r in rows]


def get_album_tracks_cached(
    conn: sqlite3.Connection, artist_dir: str, album_dir: str
) -> list[dict] | None:
    """Return read_tags()-compatible dicts from SQLite for one album.

    Validates each track's mtime against the cached value.  Returns None
    if the album is not cached or any track has been modified since the last
    scan (caller should fall back to reading from disk).
    """
    rows = conn.execute(
        "SELECT * FROM tracks WHERE artist_dir = ? AND album_dir = ? ORDER BY filename",
        (artist_dir, album_dir),
    ).fetchall()
    if not rows:
        return None
    result = []
    for row in rows:
        d = dict(row)
        try:
            if abs(Path(d["path"]).stat().st_mtime - d["mtime"]) >= 0.001:
                return None  # File modified since last scan — fall back
        except OSError:
            return None
        p = Path(d["path"])
        tags = json.loads(d["tags_json"] or "{}")
        result.append({
            "path": d["path"],
            "filename": d["filename"],
            "tags": tags,
            "has_cover": bool(d["has_cover"]),
            "has_lrc": p.with_suffix(".lrc").exists(),
            "has_lyrics_tag": bool(tags.get("lyrics")),
            "info": {
                "length": d["duration"] or 0.0,
                "sample_rate": d["sample_rate"] or 0,
                "bits_per_sample": d["bits"] or 0,
                "channels": d["channels"] or 0,
            },
        })
    return result


def get_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT COUNT(DISTINCT artist_dir) AS artists,
                  COUNT(DISTINCT artist_dir || '/' || album_dir) AS albums,
                  COUNT(*) AS tracks
           FROM tracks"""
    ).fetchone()
    return {"artists": row["artists"], "albums": row["albums"], "tracks": row["tracks"]}


def invalidate_path(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    conn.commit()


def delete_tracks_under(conn: sqlite3.Connection, path_prefix: str) -> None:
    """Remove all tracks whose path starts with path_prefix (for trashed folders/files)."""
    conn.execute("DELETE FROM tracks WHERE path = ? OR path LIKE ?",
                 (path_prefix, path_prefix.rstrip("/") + "/%"))
    conn.commit()


def scan_state() -> dict:
    return dict(_scan_state)


def run_scan(media_path: Path) -> None:
    """Walk the media directory, index any new or changed FLAC files into SQLite.

    Designed to run in a thread executor (blocking I/O).
    """
    conn = get_db(media_path)
    _scan_state.update({"status": "scanning", "done": 0, "total": 0, "started": time.time()})

    # Collect all FLAC paths first so we can show a total count.
    flac_paths: list[Path] = []
    try:
        for artist_dir in sorted(media_path.iterdir()):
            if not artist_dir.is_dir() or artist_dir.name.startswith("."):
                continue
            for album_dir in sorted(artist_dir.iterdir()):
                if not album_dir.is_dir() or album_dir.name.startswith("."):
                    continue
                for f in sorted(album_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() == ".flac":
                        flac_paths.append(f)
    except OSError:
        pass

    _scan_state["total"] = len(flac_paths)

    found_paths: set[str] = set()
    for i, f in enumerate(flac_paths):
        found_paths.add(str(f))
        try:
            mtime = f.stat().st_mtime
            if get_cached_track(conn, str(f), mtime) is None:
                audio = FLAC(str(f))
                tags: dict[str, str] = {}
                if audio.tags:
                    for key, values in audio.tags.as_dict().items():
                        tags[key.lower()] = values[0] if len(values) == 1 else "; ".join(values)
                has_cover = any(pic.type == 3 for pic in audio.pictures)
                upsert_track(conn, str(f), {
                    "mtime": mtime,
                    "artist_dir": f.parent.parent.name,
                    "album_dir": f.parent.name,
                    "filename": f.name,
                    "has_cover": has_cover,
                    "sample_rate": audio.info.sample_rate,
                    "bits": audio.info.bits_per_sample,
                    "channels": audio.info.channels,
                    "duration": audio.info.length,
                    "tags": tags,
                })
                # Yield to the network: brief sleep after each FLAC read so the
                # CIFS connection stays available for UI requests during the scan.
                time.sleep(0.05)
        except Exception:
            pass
        _scan_state["done"] = i + 1

    # Prune rows for files that no longer exist on disk.
    indexed = {r[0] for r in conn.execute("SELECT path FROM tracks").fetchall()}
    stale = indexed - found_paths
    if stale:
        conn.executemany("DELETE FROM tracks WHERE path = ?", [(p,) for p in stale])
        conn.commit()

    _scan_state["status"] = "idle"
