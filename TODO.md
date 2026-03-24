# TagLab — TODO / Ideas
# Sorted easiest → hardest to implement

## Additional ID3 Tag Fields *(easy-to-medium — additive UI work)*
- **Implemented.** Performer and Mood added to `STANDARD_TAGS` and the JS `STANDARD` array; both fields now appear in the Standard Fields column of the track editor.

## Help Page *(medium — content + client-side URL construction, no backend)*
- Add a Help entry to the sidebar that opens a dedicated Help page in the main content area.
- **User Guide section**: a scannable manual covering browsing, tag editing, artwork, MusicBrainz, ReplayGain, Lyrics, File Organizer, and settings. Rendered from a static HTML partial — no extra deps.
- **Submit Feedback section**: fields for Title, Type (Bug / Enhancement / Question), and Description. On submit, open a pre-filled GitHub new-issue URL (`https://github.com/cdeschenes/taglab/issues/new?title=...&body=...&labels=...`) in a new tab — fully client-side, no backend needed.
- Effort is mostly writing the guide content and wiring up the sidebar link.

## Saved Organizer Patterns — Persistent File Storage *(medium — new CRUD API + file I/O)*
- Currently saved patterns are stored in `localStorage`, which is browser-specific and hard to back up.
- Create a `patterns/` folder (at the config level) where each saved pattern is stored as a small JSON file.
- New API routes needed: `GET /api/patterns`, `POST /api/patterns`, `DELETE /api/patterns/{name}`.
- Frontend: replace `localStorage` reads/writes with fetch calls to the new endpoints.
- Makes patterns portable across browsers and machines, and easy to back up.

## "The" Article Handling for Organizer *(medium — config option + string transform logic)*
- When organizing by Album Artist, add an option to sort/file under the non-article form.
- Examples: "The Beatles" → filed under `Beatles, The`; "A Tribe Called Quest" → `Tribe Called Quest, A`.
- Configurable: off by default, user-defined article list (The, A, An), choice of strategy (strip for folder name vs. append suffix).
- Backend: new transform step in `organizer.py` `build_target_path()`; needs unit tests for edge cases.
- Frontend: new toggle + article-list input in the organizer modal.

## Trash Page — Recovery & Management *(medium-hard — filesystem scan + restore logic + new UI)*
- **Implemented.** Trash sidebar button (gated on `allow_delete`), hierarchical Artist→Album→Track view with Recover / Restore Album / Restore Artist buttons. Files restored back to original location and re-indexed in the library cache immediately. Empty Trash button on the page mirrors the settings panel action.

## Update Notifications & In-Place Updates *(medium-hard — registry API + optional Docker socket)*
- On startup (or via a periodic background check), compare the running image digest to the latest digest on `ghcr.io` via the GitHub Container Registry API. Surface a subtle banner or badge in the UI when an update is available.
- Alternatively, check the GitHub Releases API for a newer tagged version (requires adding a version constant to the app and tagging releases).
- **In-place update (stretch)**: A button in settings that triggers `docker compose pull && docker compose up -d` from within the container. Requires mounting the Docker socket (`/var/run/docker.sock`) — convenient but a known privilege escalation risk; should be opt-in and clearly documented.

## Additional Lyrics Sources *(medium-hard — third-party API integration + auth flows)*
- LRCLib is implemented. Still to add:
  - **Genius** — requires OAuth app registration; returns HTML that must be scraped/parsed for plain lyrics (no official sync support).
  - **Musixmatch** — requires an API key; has a strict rate limit on the free tier; returns subtitled lyrics with a proprietary format.
- Each source needs its own service module, error handling, and fallback ordering logic.

## Reporting *(hard — new view + multiple analysis queries + async jobs)*
- A dedicated Reports view (sidebar entry) with built-in reports:
  - **Mixed Bitrate Albums** — list albums where tracks have inconsistent bit depth or sample rate (data already in library cache).
  - **Missing Tags** — configurable required tag list (Genre, Mood, BPM, Key, Lyrics, etc.); report lists every album/track missing one or more selected tags.
  - **Duplicate Albums** — fuzzy match across Album + Album Artist to surface likely duplicates; configurable similarity threshold. Computationally expensive on large libraries.
  - **Potentially Damaged FLACs** — run `flac --test` on every file; flags integrity errors and anomalous file sizes/durations. Long-running: needs background job + progress UI.
- Mixed Bitrate and Missing Tags can run against the existing SQLite cache; Duplicates and Damaged FLACs require file-level processing.

## Navidrome Integration *(hard — bidirectional Subsonic API + data model extension)*
- Pull play counts, ratings, and scrobble history from Navidrome via the Subsonic API and display/edit alongside FLAC tags.
- Potentially write Last.FM play count / loved status back into FLAC tags.
- Requires matching Navidrome track IDs to local file paths (fragile if paths differ), handling auth, pagination, and keeping data in sync across edits.
- **Favorites & Star Ratings** — display and allow editing of Navidrome favorites (heart) and star ratings (1–5) at the artist, album, and track level. Uses the Subsonic API: `star`/`unstar` for favorites, `setRating` for star ratings. Ratings would appear inline in the album editor track list and on the artist/album pages, with changes written back to Navidrome in real time. No FLAC tag writeback needed — Navidrome owns this data.

## FLAC Quality Analysis *(hard — audio fingerprinting + spectral analysis)*
- Detect upscaled lossy files (e.g. an MP3 re-encoded to FLAC) by analyzing the audio spectrum for lossy encoding artifacts.
- Reference implementation: https://github.com/casantosmu/audiodeck
- Requires integrating a spectral analysis library or calling an external tool; results are probabilistic, not definitive.
- Long-running per-file analysis needs a background job queue and progress reporting UI.

## BPM & Key Detection *(hard — heavy ML dependency + background job infrastructure)*
- Auto-detect BPM and musical key from audio and write to FLAC tags.
- Use Essentia (https://github.com/MTG/essentia) for analysis — a large C++ library with a Python binding; significantly increases the Docker image size and build complexity.
- Expose as a button in the track editor and/or album editor action bar, similar to Fetch Lyrics.
- Analysis is CPU-intensive and must run as a background job with progress feedback; results need review before writing tags.

## Last.FM Personal Data Sync *(hardest — authenticated API + personal data sync)*
- Read-only enrichment is already implemented: artist bio, tags, similar artists, and photos are fetched and displayed on the artist page.
- What's missing is personal data: play counts, loved tracks, scrobble history, top tracks/albums — requires user auth (Last.FM API key + secret + session token flow).
- Optionally write Last.FM play count / loved status back into FLAC tags.
- Covers a wide surface area: authenticated personal data and optional tag writeback — each with its own API limits, auth flow, and sync complexity.
