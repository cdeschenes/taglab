function coverCleanup(albums) {
  return {
    cards: albums.map(a => ({
      artist: a.artist,
      album: a.album,
      firstFlac: a.first_flac,
      allFlacs: a.all_flacs,
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

    init() {
      // Fetch cover dimensions in small batches to avoid a thundering herd.
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
          const img = document.getElementById('cover-img-' + i);
          if (img) img.src = newSrc;
        });
      });
    },

    onImgError(event) {
      event.target.style.display = 'none';
    },

    pickFile(i) {
      document.getElementById('file-input-' + i).click();
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
      const artist = encodeURIComponent(card.artist || '');
      const albumQ = encodeURIComponent(album);
      const resp = await fetch(`/api/covers/search?artist=${artist}&album=${albumQ}`);
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
      const img = document.getElementById('cover-img-' + i);
      if (img) {
        img.style.display = '';
        img.src = newSrc;
      }
      fetch('/api/artwork/info?path=' + encodeURIComponent(this.cards[i].firstFlac) + '&t=' + Date.now())
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) this.cards[i].dims = d.width + ' \xd7 ' + d.height; })
        .catch(() => {});
    },
  };
}
