# TagLab — TODO / Ideas
# Sorted easiest → hardest to implement

---

## Pending

### "The" Article Handling for Organizer *(medium — config option + string transform)*
- When organizing by Album Artist, add an option to sort/file under the non-article form.
- Examples: "The Beatles" → filed under `Beatles, The`; "A Tribe Called Quest" → `Tribe Called Quest, A`.
- Configurable: off by default, user-defined article list (The, A, An), choice of strategy (strip for folder name vs. append suffix).
- Backend: new transform step in `organizer.py` `build_target_path()`; needs unit tests for edge cases.
- Frontend: new toggle + article-list input in the organizer modal.

### Last.FM Artist Image — Overwrite on Refresh *(small — one-line behavior change)*
- Currently the auto-save only runs when no local `artist.*` file exists.
- Add an option (or always-on behavior) to re-download and overwrite when Last.FM returns a new image URL, so the photo stays current.
- Care needed: should not overwrite images the user manually saved via the photo search modal.

### Update Notifications *(medium-hard — registry API check)*
- On startup (or via a periodic background check), compare the running image digest to the latest digest on `ghcr.io` via the GitHub Container Registry API. Surface a subtle banner or badge in the UI when an update is available.
- Alternatively, check the GitHub Releases API for a newer tagged version (requires adding a version constant to the app and tagging releases).
- **In-place update (stretch)**: A button in settings that triggers `docker compose pull && docker compose up -d` from within the container. Requires mounting the Docker socket — convenient but opt-in and clearly documented.

### Additional Lyrics Sources *(medium-hard — third-party API integration)*
- LRCLib is implemented. Still to add:
  - **Genius** — requires OAuth app registration; returns HTML that must be scraped/parsed for plain lyrics (no official sync support).
  - **Musixmatch** — requires an API key; has a strict rate limit on the free tier; returns subtitled lyrics with a proprietary format.
- Each source needs its own service module, error handling, and fallback ordering logic.

### Reporting *(hard — new view + multiple analysis queries)*
- A dedicated Reports view (sidebar entry) with built-in reports:
  - **Mixed Bitrate Albums** — list albums where tracks have inconsistent bit depth or sample rate (data already in library cache).
  - **Missing Tags** — configurable required tag list (Genre, Mood, BPM, Key, Lyrics, etc.); report lists every album/track missing one or more selected tags.
  - **Duplicate Albums** — fuzzy match across Album + Album Artist to surface likely duplicates; configurable similarity threshold.
  - **Potentially Damaged FLACs** — run `flac --test` on every file; flags integrity errors. Long-running: needs background job + progress UI.
- Mixed Bitrate and Missing Tags can run against the existing SQLite cache; Duplicates and Damaged FLACs require file-level processing.

### Navidrome — Full Personal Data Sync *(hard — bidirectional Subsonic API)*
- Favorites (♥) and star ratings (1–5) display/edit are already implemented.
- Still to add:
  - Pull **play counts** per track from Navidrome and display in the album editor / track list.
  - Optionally write Last.FM play count / loved status back into FLAC tags.
  - Keep data in sync across edits (currently sync is manual via the Sync button).

### FLAC Quality Analysis *(hard — spectral analysis)*
- Detect upscaled lossy files (e.g. an MP3 re-encoded to FLAC) by analyzing the audio spectrum.
- Reference: https://github.com/casantosmu/audiodeck
- Requires a spectral analysis library; results are probabilistic.
- Long-running per-file analysis needs a background job queue and progress UI.

### BPM & Key Detection *(hard — heavy ML dependency)*
- Auto-detect BPM and musical key from audio and write to FLAC tags.
- Use Essentia (https://github.com/MTG/essentia) — significantly increases image size and build complexity.
- Expose as a button in the track editor and album editor action bar.
- CPU-intensive: must run as a background job with progress feedback.

### Last.FM Personal Data Sync *(hardest — authenticated API + personal data)*
- Read-only enrichment (artist bio, tags, similar artists, photos) is already implemented.
- What's missing: personal data — play counts, loved tracks, scrobble history — requires user auth (API key + secret + session token flow).
- Optionally write Last.FM play count / loved status back into FLAC tags.

---

## Completed

| Feature | Notes |
|---|---|
| Additional ID3 Tag Fields | Performer and Mood added to `STANDARD_TAGS`; appear in the track editor |
| Help Page | Card-grid user guide in the sidebar; Submit Feedback opens a pre-filled GitHub issue |
| Saved Organizer Patterns | Stored server-side in `cache_path/organizer_patterns.json`; localStorage migrated on first load |
| Trash Page — Recovery & Management | Hierarchical Artist→Album→Track view; Recover / Restore Album / Restore Artist; re-indexes immediately |
| Last.FM Artist Image — Auto-Save | Downloaded to `artist.jpg` in the artist folder on first visit when no local image exists |
| Reset & Rescan | Deletes the SQLite cache and rebuilds from scratch; accessible from the Settings panel |
| Navidrome — Favorites & Star Ratings | Display and edit ♥ favorites and 1–5 star ratings; explorer filter by starred/rating |
| Explorer Sort | Sort by A–Z, Recently Added (uses Navidrome `created` date), and cover size |
| Cover Cleanup Sort | Sort by missing first, size (small → large), or recently added |
| Recently Added Sort Fix | Uses Navidrome's `created` timestamp; stable across tag and cover edits |
| Cover Size Sort Fix | Dimensions decoded from image bytes when FLAC Picture block fields are zero |
| Cover Dimensions on Upload | Cache updated immediately after upload; no rescan needed to reflect new dimensions |
