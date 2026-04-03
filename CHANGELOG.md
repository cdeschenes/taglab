# Changelog

All notable changes to TagLab are documented here.

---

## [Unreleased]

---

## [0.4.0] — 2026-04-03

### Added
- **Debug Log button on Help page** — opens a modal showing the last 1000 lines of `CACHE_PATH/taglab.log`. Application and uvicorn access/error logs are written to this file on startup via a `RotatingFileHandler` (5 MB, 2 backups). Includes a Copy to Clipboard button. Useful for diagnosing issues without needing `docker logs` access.
- **`app/version.py`** — single source of truth for the application version. `help.html` version badge and the MusicBrainz user-agent string now both read from this file.

### Removed
- **Navidrome filters on Cover Clean-Up page** — the Favorites Only and Min Rating dropdowns have been removed. Navidrome filtering belongs in the library explorer sidebar only; the Cover Clean-Up page is a maintenance tool and should always show all albums.

---

## [0.3.0] — 2026-03-28

### Added
- **Saved Organizer Patterns** — patterns are now stored server-side in `CACHE_PATH/organizer_patterns.json` and shared across browsers/machines. Three new API routes: `GET /api/patterns`, `POST /api/patterns`, `DELETE /api/patterns/{name}`. Any patterns previously saved in `localStorage` are migrated automatically on first use.

### Fixed
- **Cover size sort** — covers embedded by third-party tools (Picard, beets, mp3tag, etc.) have `width=0`/`height=0` in the FLAC Picture block metadata because those fields are optional in the spec. The sort now falls back to decoding the actual image bytes with PIL to get real pixel dimensions. A Reset & Rescan (or regular Rescan) will backfill correct dimensions for all existing albums.

### Documentation
- README feature list expanded: Navidrome full sync, Trash recovery page, saved organizer patterns, Reset & Rescan, artist photo auto-save, Help page.
- User Guide updated: new sections for Saved Patterns, Cover Cleanup sort options, Trash recovery page, Navidrome sync (play counts, favorites, ratings), artist photo auto-save, Reset & Rescan in Settings table, and Help page.

---

## [0.2.0] — 2026-03-23

### Added
- **Help page** — in-app user guide accessible from the sidebar. Feature cards with icons covering all major features. Navidrome and Trash cards are gated on their respective feature flags. Submit Feedback form opens a pre-filled GitHub issue in a new tab (fully client-side).
- **Reset & Rescan** — new button in the Settings panel that deletes the SQLite library cache and triggers a full rebuild from scratch. Useful when the index is stale or corrupted.
- **Trash page** — dedicated sidebar page (gated on `ALLOW_DELETE=true`) showing everything in `.trash/` as a hierarchical Artist → Album → Track tree. Supports recovering individual tracks, entire albums, or all albums by an artist. Recovered files are re-indexed immediately.
- **Performer and Mood fields** — both fields added to `STANDARD_TAGS` and the track editor's Standard Fields column.
- **Navidrome favorites and star ratings** — display and edit Navidrome ♥ favorites and 1–5 star ratings inline in the album editor track list. Changes write back to Navidrome via the Subsonic API in real time. Explorer can filter to starred albums and filter by minimum rating.
- **Library explorer sort** — new Sort dropdown in the explorer: A–Z (default), Recently Added, and Cover Size.
- **Cover Cleanup sort** — Sort dropdown on the Cover Cleanup page: Missing first (default), Size (small → large), Recently Added.

### Fixed
- **Recently Added sort** — previously used file `mtime`, which gets bumped whenever tags or covers are written. Now uses Navidrome's `created` timestamp (when the track was first indexed in Navidrome), falling back to `mtime` when Navidrome is not configured. Sort is now stable across tag and cover edits.
- **Cover dimensions stored during scan** — `run_scan()` now reads actual pixel dimensions from image bytes (via PIL) and stores `cover_w`/`cover_h` in the SQLite cache. Tracks with a cover but missing dimensions are re-read on the next incremental scan.
- **Cover dimensions updated on upload** — uploading a new cover immediately updates `cover_w`/`cover_h` in the SQLite cache. No rescan needed for the Cover Cleanup size sort to reflect the new image.

---

## [0.1.0] — 2026-03-23

### Added
- Initial TagLab release.
- Browse music library by artist and album. SQLite-backed index with mtime-based incremental scanning.
- Album editor: shared tag fields (Album, Album Artist, Year, Genre, Label, Country, MusicBrainz IDs) applied across all tracks; per-track editor with all standard Vorbis comment fields.
- Cover art: upload, drag-and-drop, URL fetch, remove. Cover written to FLAC tags and as `cover.jpg` / `folder.jpg` in the album directory. Cover Cleanup page for albums missing artwork.
- Artist page with Last.fm card (bio, stats, genre tags, similar artists, artist photo). Artist photo search via Deezer and iTunes. Auto-saves Last.fm photo to `artist.jpg` on first visit.
- MusicBrainz lookup: search by album + artist, select release, auto-fill tags and per-track titles.
- ReplayGain: EBU R128 calculation via ffmpeg; album + track gain; preview before writing.
- Lyrics: fetch synchronized lyrics from LRCLib; stored in the `LYRICS` tag; `.lrc` sidecar file support.
- File Organizer: pattern-based rename/move with token builder UI; preview before applying; post-move junk file cleanup.
- Move to Trash: albums and tracks moved to `{MEDIA_PATH}/.trash/` preserving relative paths. Empty Trash in Settings panel.
- Navidrome integration: trigger library rescan via Subsonic API.
- Multi-library support: configure multiple libraries via `LIBRARIES` env var; switch at runtime.
- Six dark themes: Default, Nord, Dracula, GitHub Dark, Tokyo Night, Catppuccin Mocha.
- Login page with persistent cookie-based sessions; HTTP Basic auth supported for API access.
- Docker image with ffmpeg bundled; `docker compose` and bare `docker run` workflows.
