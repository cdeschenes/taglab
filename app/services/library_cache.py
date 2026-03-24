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


def drop_db(media_path: Path) -> None:
    """Close and delete the SQLite cache for media_path so the next get_db() starts fresh."""
    key = str(media_path)
    db_file = _db_path(media_path)
    with _connections_lock:
        conn = _connections.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_file) + suffix)
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS navidrome_tracks (
            path        TEXT PRIMARY KEY,
            navi_id     TEXT NOT NULL,
            play_count  INTEGER NOT NULL DEFAULT 0,
            starred     INTEGER NOT NULL DEFAULT 0,
            user_rating INTEGER NOT NULL DEFAULT 0,
            synced_at   REAL NOT NULL,
            navi_created REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_navi_id ON navidrome_tracks(navi_id)")
    # Migrate existing databases that predate the navi_created column.
    try:
        conn.execute("ALTER TABLE navidrome_tracks ADD COLUMN navi_created REAL")
    except Exception:
        pass  # Column already exists
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


def get_all_albums_filtered(
    conn: sqlite3.Connection,
    sort: str = "name",
    min_rating: int = 0,
    starred_only: bool = False,
) -> list[dict]:
    """Return albums with optional sort and Navidrome filters.

    sort: "name" (default) | "recently_added" | "cover_size"
    min_rating: 0 (no filter) or 1-5 (minimum album track rating)
    starred_only: if True, only albums with at least one starred track
    """
    needs_navi = min_rating > 0 or starred_only
    join = " INNER JOIN navidrome_tracks nt ON nt.path = t.path" if needs_navi else ""
    # Always LEFT JOIN for navi_created so recently-added sort uses Navidrome's stable add date.
    navi_created_join = " LEFT JOIN navidrome_tracks nt2 ON nt2.path = t.path" if sort == "recently_added" else ""

    having_parts: list[str] = []
    params: list = []
    if min_rating > 0:
        having_parts.append("MAX(nt.user_rating) >= ?")
        params.append(min_rating)
    if starred_only:
        having_parts.append("MAX(nt.starred) = 1")
    having = ("HAVING " + " AND ".join(having_parts)) if having_parts else ""

    if sort == "recently_added":
        order = "ORDER BY COALESCE(MAX(nt2.navi_created), MAX(t.mtime)) DESC"
    elif sort == "cover_size":
        order = "ORDER BY MAX(t.has_cover) ASC, COALESCE(MAX(t.cover_w) * MAX(t.cover_h), 0) ASC"
    else:
        order = "ORDER BY t.artist_dir COLLATE NOCASE, t.album_dir COLLATE NOCASE"

    sql = f"""
        SELECT t.artist_dir, t.album_dir,
               MIN(t.path) AS first_flac,
               COUNT(*) AS track_count,
               MAX(t.has_cover) AS has_cover,
               MAX(t.cover_w) AS cover_w,
               MAX(t.cover_h) AS cover_h
        FROM tracks t{join}{navi_created_join}
        GROUP BY t.artist_dir, t.album_dir
        {having}
        {order}
    """
    rows = conn.execute(sql, params).fetchall()
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
            "cover_w": row["cover_w"],
            "cover_h": row["cover_h"],
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


def update_cover_dimensions(
    conn: sqlite3.Connection,
    path: str,
    has_cover: bool,
    cover_w: int | None,
    cover_h: int | None,
) -> None:
    """Update cover art dimensions in the cache without a full track re-read."""
    conn.execute(
        "UPDATE tracks SET has_cover=?, cover_w=?, cover_h=? WHERE path=?",
        (1 if has_cover else 0, cover_w, cover_h, path),
    )
    conn.commit()


def invalidate_path(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    conn.commit()


def delete_tracks_under(conn: sqlite3.Connection, path_prefix: str) -> None:
    """Remove all tracks whose path starts with path_prefix (for trashed folders/files)."""
    conn.execute("DELETE FROM tracks WHERE path = ? OR path LIKE ?",
                 (path_prefix, path_prefix.rstrip("/") + "/%"))
    conn.commit()


def upsert_navidrome_track(
    conn: sqlite3.Connection,
    path: str,
    navi_id: str,
    play_count: int,
    starred: bool,
    user_rating: int,
    navi_created: float | None = None,
) -> None:
    conn.execute(
        """INSERT INTO navidrome_tracks
           (path, navi_id, play_count, starred, user_rating, synced_at, navi_created)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
             navi_id=excluded.navi_id,
             play_count=excluded.play_count,
             starred=excluded.starred,
             user_rating=excluded.user_rating,
             synced_at=excluded.synced_at,
             navi_created=COALESCE(excluded.navi_created, navidrome_tracks.navi_created)""",
        (path, navi_id, play_count, 1 if starred else 0, user_rating, time.time(), navi_created),
    )
    conn.commit()


def get_navidrome_for_album(
    conn: sqlite3.Connection, artist_dir: str, album_dir: str
) -> dict[str, dict]:
    """Return a dict keyed by local path for all Navidrome-cached tracks in an album."""
    rows = conn.execute(
        """SELECT nt.* FROM navidrome_tracks nt
           JOIN tracks t ON t.path = nt.path
           WHERE t.artist_dir = ? AND t.album_dir = ?""",
        (artist_dir, album_dir),
    ).fetchall()
    return {r["path"]: dict(r) for r in rows}


def get_path_by_navi_id(conn: sqlite3.Connection, navi_id: str) -> str | None:
    row = conn.execute(
        "SELECT path FROM navidrome_tracks WHERE navi_id = ?", (navi_id,)
    ).fetchone()
    return row["path"] if row else None


def update_navidrome_star(conn: sqlite3.Connection, path: str, starred: bool) -> None:
    conn.execute(
        "UPDATE navidrome_tracks SET starred = ?, synced_at = ? WHERE path = ?",
        (1 if starred else 0, time.time(), path),
    )
    conn.commit()


def update_navidrome_rating(conn: sqlite3.Connection, path: str, rating: int) -> None:
    conn.execute(
        "UPDATE navidrome_tracks SET user_rating = ?, synced_at = ? WHERE path = ?",
        (rating, time.time(), path),
    )
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
            cached = get_cached_track(conn, str(f), mtime)
            needs_update = cached is None or (
                cached.get("has_cover") and not cached.get("cover_w")
            )
            if needs_update:
                audio = FLAC(str(f))
                tags: dict[str, str] = {}
                if audio.tags:
                    for key, values in audio.tags.as_dict().items():
                        tags[key.lower()] = values[0] if len(values) == 1 else "; ".join(values)
                cover_pic = next((pic for pic in audio.pictures if pic.type == 3), None)
                has_cover = cover_pic is not None
                upsert_track(conn, str(f), {
                    "mtime": mtime,
                    "artist_dir": f.parent.parent.name,
                    "album_dir": f.parent.name,
                    "filename": f.name,
                    "has_cover": has_cover,
                    "cover_w": cover_pic.width if cover_pic else None,
                    "cover_h": cover_pic.height if cover_pic else None,
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
