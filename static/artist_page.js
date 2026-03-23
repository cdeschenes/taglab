function artistImageCard(artist, imageUrl, folder) {
  return {
    artist,
    folder,
    imgSrc: imageUrl || '',
    imgFailed: !imageUrl,
    showPhotoSearch: false,
    photoSearchLoading: false,
    photoSearchResults: [],
    saving: false,

    onImgError() {
      this.imgFailed = true;
    },

    async searchArtistPhoto() {
      this.showPhotoSearch = true;
      this.photoSearchLoading = true;
      this.photoSearchResults = [];
      try {
        const resp = await fetch('/api/artist-photo/search?artist=' + encodeURIComponent(this.artist));
        this.photoSearchResults = resp.ok ? await resp.json() : [];
      } catch (_) {
        this.photoSearchResults = [];
      }
      this.photoSearchLoading = false;
    },

    async selectArtistPhoto(photo) {
      this.showPhotoSearch = false;
      this.saving = true;
      try {
        const resp = await fetch('/api/artist-photo/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artist: this.artist, url: photo.full, folder: this.folder }),
        });
        if (resp.ok) {
          const { local_url } = await resp.json();
          this.imgSrc = local_url + '&t=' + Date.now();
          this.imgFailed = false;
          showNotification('Artist photo saved');
        } else {
          const err = await resp.json().catch(() => ({}));
          showNotification('Failed: ' + (err.detail || 'Unknown error'), true);
        }
      } catch (e) {
        showNotification('Error: ' + e.message, true);
      } finally {
        this.saving = false;
      }
    },
  };
}

function artistPage(albums, artist, artistPath) {
  return {
    cards: albums.map(a => ({
      artist: a.artist,
      album: a.album,
      firstFlac: a.first_flac,
      allFlacs: a.all_flacs,
      trackCount: a.track_count,
      imgSrc: '/api/artwork/thumbnail?size=' + getThumbnailSize() + '&path=' + encodeURIComponent(a.first_flac),
      dims: '',
      urlInput: '',
      showUrl: false,
      uploading: false,
    })),
    dragging: albums.map(() => false),
    showCoverSearch: false,
    coverSearchLoading: false,
    coverSearchGroups: [],
    activeSearchIdx: null,
    bulkRunning: false,
    _artist: artist,
    _artistPath: artistPath,
    deleteEnabled: typeof isDeleteEnabled === 'function' ? isDeleteEnabled() : false,

    init() {
      document.addEventListener('taglab:deletepref', (e) => { this.deleteEnabled = e.detail.enabled; });
      const BATCH = 10;
      const cards = this.cards;
      let offset = 0;
      const fetchNext = () => {
        const batch = cards.slice(offset, offset + BATCH);
        if (!batch.length) return;
        const base = offset;
        batch.forEach((card, j) => {
          fetch('/api/artwork/info?path=' + encodeURIComponent(card.firstFlac))
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) this.cards[base + j].dims = d.width + ' \xd7 ' + d.height; })
            .catch(() => {});
        });
        offset += BATCH;
        setTimeout(fetchNext, 200);
      };
      fetchNext();

      document.addEventListener('taglab:thumbsize', (e) => {
        const size = e.detail.size;
        this.cards.forEach((card, i) => {
          const newSrc = '/api/artwork/thumbnail?size=' + size + '&path=' + encodeURIComponent(card.firstFlac) + '&t=' + Date.now();
          this.cards[i].imgSrc = newSrc;
          const img = document.getElementById('ap-cover-img-' + i);
          if (img) img.src = newSrc;
        });
      });
    },

    navigateAlbum(card) {
      htmx.ajax('GET', '/ui/album?path=' + encodeURIComponent(card.artist + '/' + card.album), {
        target: '#editor-panel',
        swap: 'innerHTML',
      });
    },

    onImgError(event) {
      event.target.style.display = 'none';
    },

    pickFile(i) {
      document.getElementById('ap-file-input-' + i).click();
    },

    toggleUrl(i) {
      this.cards[i].showUrl = !this.cards[i].showUrl;
    },

    async searchCovers(i) {
      const card = this.cards[i];
      const album = card.album
        .replace(/^\d{4}\s*-\s*/, '')
        .replace(/\s*\[.*?\]\s*$/, '')
        .trim();
      this.activeSearchIdx = i;
      this.showCoverSearch = true;
      this.coverSearchLoading = true;
      this.coverSearchGroups = [];
      const artistQ = encodeURIComponent(card.artist || '');
      const albumQ = encodeURIComponent(album);
      const resp = await fetch(`/api/covers/search?artist=${artistQ}&album=${albumQ}`);
      const flat = resp.ok ? await resp.json() : [];
      const bySource = {};
      for (const c of flat) {
        if (!bySource[c.source]) bySource[c.source] = [];
        bySource[c.source].push(c);
      }
      const order = ['iTunes', 'Deezer', 'MusicBrainz', 'Bandcamp'];
      this.coverSearchGroups = order.map(src => ({
        source: src,
        covers: bySource[src] || [],
        expanded: !!(bySource[src] && bySource[src].length > 0),
      }));
      this.coverSearchLoading = false;
    },

    selectSearchCover(cover) {
      const i = this.activeSearchIdx;
      this.showCoverSearch = false;
      this.activeSearchIdx = null;
      this._doUploadUrl(i, cover.image);
    },

    onDragOver(i) { this.dragging[i] = true; },
    onDragLeave(i) { this.dragging[i] = false; },

    dropFile(i, event) {
      this.dragging[i] = false;
      const file = event.dataTransfer.files[0];
      if (!file) return;
      this._doUploadFile(i, file);
    },

    uploadFile(i, event) {
      const file = event.target.files[0];
      if (!file) return;
      this._doUploadFile(i, file);
      event.target.value = '';
    },

    async _doUploadFile(i, file) {
      this.cards[i].uploading = true;
      try {
        const fd = new FormData();
        fd.append('paths', JSON.stringify(this.cards[i].allFlacs));
        fd.append('file', file);
        fd.append('cover_filename', getCoverFilename());
        const resp = await fetch('/api/artwork/upload', { method: 'POST', body: fd });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: resp.statusText }));
          showNotification('Upload failed: ' + (err.detail || resp.statusText), true);
          return;
        }
        this._bustCache(i);
        showNotification('Cover updated');
      } catch (e) {
        showNotification('Upload error: ' + e.message, true);
      } finally {
        this.cards[i].uploading = false;
      }
    },

    async uploadUrl(i) {
      const url = this.cards[i].urlInput.trim();
      if (!url) return;
      await this._doUploadUrl(i, url);
      this.cards[i].showUrl = false;
      this.cards[i].urlInput = '';
    },

    async _doUploadUrl(i, url) {
      this.cards[i].uploading = true;
      try {
        const resp = await fetch('/api/artwork/from-url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, paths: this.cards[i].allFlacs, cover_filename: getCoverFilename() }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: resp.statusText }));
          showNotification('Failed: ' + (err.detail || resp.statusText), true);
          return;
        }
        this._bustCache(i);
        showNotification('Cover updated');
      } catch (e) {
        showNotification('Error: ' + e.message, true);
      } finally {
        this.cards[i].uploading = false;
      }
    },

    _bustCache(i) {
      const base = '/api/artwork/thumbnail?size=' + getThumbnailSize() + '&path=' + encodeURIComponent(this.cards[i].firstFlac);
      const newSrc = base + '&t=' + Date.now();
      this.cards[i].imgSrc = newSrc;
      const img = document.getElementById('ap-cover-img-' + i);
      if (img) {
        img.style.display = '';
        img.src = newSrc;
      }
      fetch('/api/artwork/info?path=' + encodeURIComponent(this.cards[i].firstFlac) + '&t=' + Date.now())
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) this.cards[i].dims = d.width + ' \xd7 ' + d.height; })
        .catch(() => {});
    },

    // ── Bulk Edit All Albums ───────────────────────────────────────────────────

    bulkEditAllAlbums() {
      const albumFolders = this.cards.map(card => {
        const parts = card.firstFlac.split('/');
        parts.pop();
        return parts.join('/');
      });
      const escapedArtist = this._artist.replace(/&/g, '&amp;').replace(/</g, '&lt;');
      showModal(`
        <div class="bulk-edit-modal" x-data='bulkEditModal(${JSON.stringify(albumFolders)}, ${JSON.stringify(this._artist)})'>
          <div class="modal-header">
            <h2>Edit All Albums &mdash; ${escapedArtist}</h2>
            <button class="modal-close" @click="hideModal()">&#x2715;</button>
          </div>
          <div class="modal-body">
            <p class="bulk-edit-hint">Only filled fields will be updated. Leave blank to keep existing values.</p>
            <div class="fields-grid">
              <label>Album<input type="text" x-model="shared.album"></label>
              <label>Album Artist<input type="text" x-model="shared.albumartist"></label>
              <label>Date<input type="text" x-model="shared.date" placeholder="YYYY-MM-DD"></label>
              <label>Genre<input type="text" x-model="shared.genre"></label>
              <label>Label<input type="text" x-model="shared.label"></label>
              <label>Country<input type="text" x-model="shared.country" placeholder="GB"></label>
              <label>MBID Album<input type="text" x-model="shared.musicbrainz_albumid" class="monospace" placeholder="MusicBrainz Release ID"></label>
              <label>MBID Album Artist<input type="text" x-model="shared.musicbrainz_albumartistid" class="monospace"></label>
              <label>MBID Release Group<input type="text" x-model="shared.musicbrainz_releasegroupid" class="monospace"></label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="hideModal()">Cancel</button>
            <button class="btn btn-primary" @click="previewSave()" :disabled="previewing">
              <span x-text="previewing ? 'Loading\u2026' : 'Preview \u0026 Save'"></span>
            </button>
          </div>
        </div>
      `);
    },

    // ── Organize All Albums ────────────────────────────────────────────────────

    async organizeAllAlbums() {
      const paths = this.cards.flatMap(card => card.allFlacs);
      if (!paths.length) { showNotification('No tracks found', true); return; }
      const resp = await fetch('/api/organizer/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        showNotification(d.detail || 'Organizer not configured', true);
        return;
      }
      showModal(await resp.text());
    },

    // ── Bulk Lyrics ────────────────────────────────────────────────────────────

    async fetchAllLyrics() {
      if (this.bulkRunning) return;
      const tracks = [];
      for (const a of albums) {
        for (const t of (a.tracks || [])) {
          tracks.push({
            path: t.path,
            artist: t.tags.artist || artist,
            track: t.tags.title || t.filename,
            album: t.tags.album || a.album,
            has_lyrics_tag: !!(t.tags.lyrics),
          });
        }
      }
      if (!tracks.length) { showNotification('No tracks found', true); return; }

      const toFetch = tracks.filter(t => !t.has_lyrics_tag).length;
      const preSkipped = tracks.length - toFetch;

      this.bulkRunning = true;
      showModal(`
        <div class="modal-header"><h2>Fetch Lyrics \u2014 ${artist}</h2></div>
        <div class="modal-body" style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:48px 20px;color:var(--text-dim)">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" style="animation:rg-spin 1.2s linear infinite">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
          </svg>
          <div style="font-size:14px">Fetching lyrics for ${toFetch} track(s)\u2026</div>
          ${preSkipped ? `<div style="font-size:12px">${preSkipped} track${preSkipped !== 1 ? 's' : ''} already have lyrics \u2014 skipping</div>` : ''}
        </div>
        <style>@keyframes rg-spin{to{transform:rotate(360deg)}}</style>
      `);

      let results;
      try {
        const resp = await fetch('/api/lyrics/fetch-batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tracks }),
        });
        if (!resp.ok) { hideModal(); showNotification('Lyrics fetch failed', true); return; }
        ({ results } = await resp.json());
      } catch (e) {
        hideModal(); showNotification('Lyrics fetch failed', true); return;
      } finally {
        this.bulkRunning = false;
      }

      const synced   = results.filter(r => r.status === 'synced').length;
      const plain    = results.filter(r => r.status === 'plain').length;
      const skipped  = results.filter(r => r.status === 'skipped').length;
      const missing  = results.filter(r => r.status === 'not_found').length;
      const errors   = results.filter(r => r.status === 'error').length;

      const rows = results.map(r => {
        const fname = r.path.split('/').pop();
        let badge, note;
        if      (r.status === 'synced')                         { badge = '<span style="color:#4ade80">synced</span>';       note = '.lrc saved'; }
        else if (r.status === 'plain')                          { badge = '<span style="color:#60a5fa">plain</span>';        note = 'applied to tag'; }
        else if (r.status === 'skipped' && r.reason==='lrc_exists')     { badge = '<span style="color:#94a3b8">has lyrics</span>'; note = '.lrc file exists'; }
        else if (r.status === 'skipped' && r.reason==='has_lyrics_tag') { badge = '<span style="color:#94a3b8">has lyrics</span>'; note = 'lyrics tag set'; }
        else if (r.status === 'not_found')                      { badge = '<span style="color:#6b7280">\u2014</span>';      note = 'not found'; }
        else                                                    { badge = '<span style="color:#f87171">error</span>';       note = r.message || ''; }
        return `<tr>
          <td style="padding:4px 8px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${fname}">${fname}</td>
          <td style="padding:4px 8px">${badge}</td>
          <td style="padding:4px 8px;color:var(--text-dim);font-size:12px">${note}</td>
        </tr>`;
      }).join('');

      showModal(`
        <div class="modal-header"><h2>Fetch Lyrics \u2014 Results</h2></div>
        <div class="modal-body" style="padding:20px">
          <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:16px;font-size:13px">
            ${synced  ? `<span style="color:#4ade80">${synced} synced</span>` : ''}
            ${plain   ? `<span style="color:#60a5fa">${plain} plain</span>` : ''}
            ${skipped ? `<span style="color:#94a3b8">${skipped} already have lyrics</span>` : ''}
            ${missing ? `<span style="color:#6b7280">${missing} not found</span>` : ''}
            ${errors  ? `<span style="color:#f87171">${errors} errors</span>` : ''}
          </div>
          <div style="max-height:340px;overflow-y:auto">
            <table style="width:100%;border-collapse:collapse;font-size:13px">${rows}</table>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-primary" onclick="hideModal()">Close</button>
        </div>
      `);
    },

    // ── Trash Artist ──────────────────────────────────────────────────────────

    trashArtist() {
      showConfirm(`Move entire artist to trash?\n\n${this._artistPath}`, async () => {
        const resp = await fetch('/api/trash/artist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: this._artistPath }),
        });
        if (resp.ok) {
          showNotification('Artist moved to trash');
          document.getElementById('editor-panel').innerHTML = '';
          htmx.ajax('GET', '/ui/explorer', { target: '#explorer-root', swap: 'innerHTML' });
        } else {
          const d = await resp.json();
          showNotification(d.detail || 'Failed to trash artist', true);
        }
      });
    },

    // ── Bulk ReplayGain ────────────────────────────────────────────────────────

    async calculateAllRG() {
      if (this.bulkRunning) return;
      this.bulkRunning = true;
      const total = albums.length;

      showModal(`
        <div class="modal-header"><h2>ReplayGain \u2014 ${artist}</h2></div>
        <div class="modal-body" style="padding:20px">
          <div id="rg-bulk-progress" style="font-size:13px;margin-bottom:12px;color:var(--text-dim)">Starting\u2026</div>
          <div id="rg-bulk-log" style="max-height:320px;overflow-y:auto;font-size:12px;font-family:monospace;display:flex;flex-direction:column;gap:4px"></div>
        </div>
      `);

      const log = [];
      for (let i = 0; i < albums.length; i++) {
        const a = albums[i];
        const progEl = document.getElementById('rg-bulk-progress');
        if (progEl) progEl.textContent = `Processing: ${a.album} (${i + 1}/${total})`;

        try {
          const resp = await fetch('/api/replaygain/calculate-apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths: a.all_flacs, album_mode: true }),
          });
          if (resp.ok) {
            const d = await resp.json();
            log.push({ album: a.album, ok: true, count: d.count });
          } else {
            const d = await resp.json().catch(() => ({}));
            log.push({ album: a.album, ok: false, message: d.detail || 'Error' });
          }
        } catch (e) {
          log.push({ album: a.album, ok: false, message: e.message });
        }

        const logEl = document.getElementById('rg-bulk-log');
        if (logEl) {
          const last = log[log.length - 1];
          const row = document.createElement('div');
          row.style.color = last.ok ? 'var(--success, #4ade80)' : 'var(--danger, #f87171)';
          row.textContent = (last.ok ? '\u2713 ' : '\u2717 ') + last.album +
            (last.ok ? ` (${last.count} track${last.count !== 1 ? 's' : ''})` : ` \u2014 ${last.message}`);
          logEl.appendChild(row);
          logEl.scrollTop = logEl.scrollHeight;
        }
      }

      const ok  = log.filter(r =>  r.ok).length;
      const err = log.filter(r => !r.ok).length;
      const progEl = document.getElementById('rg-bulk-progress');
      if (progEl) {
        progEl.textContent = `Done \u2014 ${ok} album${ok !== 1 ? 's' : ''} updated${err ? `, ${err} failed` : ''}`;
        progEl.style.color = err ? 'var(--danger, #f87171)' : 'var(--success, #4ade80)';
      }
      const body = document.querySelector('#modal-container .modal-body');
      if (body) {
        const footer = document.createElement('div');
        footer.className = 'modal-footer';
        footer.innerHTML = '<button class="btn btn-primary" onclick="hideModal()">Close</button>';
        body.after(footer);
      }
      this.bulkRunning = false;
    },
  };
}
