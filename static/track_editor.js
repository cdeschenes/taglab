/**
 * Alpine.js component factory for the track editor modal.
 * Loaded globally so it's available when HTMX swaps in the modal HTML
 * (Alpine's MutationObserver fires before HTMX executes inline <script> tags).
 */
function trackEditor(data) {
  const STANDARD = [
    'title','artist','albumartist','album','date','tracknumber','discnumber',
    'genre','composer','label','country','isrc','barcode','comment','bpm','key','lyrics',
    'musicbrainz_albumid','musicbrainz_albumartistid','musicbrainz_artistid',
    'musicbrainz_trackid','musicbrainz_releasegroupid','musicbrainz_releasetrackid',
    'replaygain_track_gain','replaygain_track_peak',
    'replaygain_album_gain','replaygain_album_peak','replaygain_reference_loudness'
  ];
  const allTags = { ...data.tags };
  const standardTags = {};
  const customTagsInit = {};
  for (const k of STANDARD) { standardTags[k] = allTags[k] || ''; }
  for (const [k, v] of Object.entries(allTags)) {
    if (!STANDARD.includes(k)) customTagsInit[k] = v;
  }
  return {
    path: data.path,
    tags: standardTags,
    customTags: customTagsInit,
    standardKeys: STANDARD,
    newKey: '',
    newVal: '',
    lyricsStatus: '',
    lyricsStatusOk: false,

    init() {
      const dimsEl = document.getElementById('track-cover-dims');
      if (dimsEl) {
        fetch('/api/artwork/info?path=' + encodeURIComponent(this.path))
          .then(r => r.ok ? r.json() : null)
          .then(d => { if (d) dimsEl.textContent = d.width + ' × ' + d.height + ' px'; })
          .catch(() => {});
      }
    },

    addCustomTag() {
      if (this.newKey.trim()) {
        this.customTags[this.newKey.trim().toLowerCase()] = this.newVal;
        this.newKey = '';
        this.newVal = '';
      }
    },

    deleteCustomTag(key) {
      const updated = { ...this.customTags };
      delete updated[key];
      this.customTags = updated;
    },

    async fetchLyrics() {
      const artist = this.tags.artist || '';
      const title = this.tags.title || '';
      const album = this.tags.album || '';
      if (!artist || !title) {
        this.lyricsStatus = 'Need artist and title';
        this.lyricsStatusOk = false;
        setTimeout(() => { this.lyricsStatus = ''; }, 3000);
        return;
      }
      this.lyricsStatus = 'Fetching\u2026';
      this.lyricsStatusOk = false;
      const params = new URLSearchParams({ artist, track: title });
      if (album) params.set('album', album);
      try {
        const resp = await fetch('/api/lyrics?' + params.toString());
        if (resp.status === 404) {
          this.lyricsStatus = 'Not found';
        } else if (!resp.ok) {
          this.lyricsStatus = 'Fetch error';
        } else {
          const data = await resp.json();
          if (data.synced) {
            const lrcResp = await fetch('/api/lyrics/write-lrc', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: this.path, content: data.synced }),
            });
            const lrcData = await lrcResp.json();
            if (!lrcResp.ok) {
              this.lyricsStatus = 'Error saving .lrc';
            } else if (lrcData.exists) {
              this.lyricsStatus = 'Synced \u2014 .lrc already exists';
              this.lyricsStatusOk = true;
            } else {
              this.lyricsStatus = 'Synced \u2014 .lrc saved \u2713';
              this.lyricsStatusOk = true;
            }
          } else if (data.plain) {
            this.tags['lyrics'] = data.plain;
            this.lyricsStatus = 'Plain lyrics fetched';
            this.lyricsStatusOk = true;
          } else {
            this.lyricsStatus = 'Not found';
          }
        }
      } catch (e) {
        this.lyricsStatus = 'Fetch error';
      }
      setTimeout(() => { this.lyricsStatus = ''; }, 4000);
    },

    async save() {
      const merged = { ...this.tags, ...this.customTags };
      const resp = await fetch('/api/track/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: this.path, tags: merged })
      });
      hideModal();
      showNotification(resp.ok ? 'Track saved' : 'Save failed', !resp.ok);
    }
  };
}
