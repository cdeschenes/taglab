/**
 * Alpine.js factory functions for HTMX/showModal()-injected modals.
 * Must be loaded globally (base.html) — scripts injected via innerHTML
 * are never executed by the browser, so these can't live in partials.
 */

function previewModal(payload) {
  return {
    applying: false,
    async apply() {
      this.applying = true;
      const editor = Alpine.$data(document.getElementById('album-editor'));
      await editor.confirmSave(payload);
      this.applying = false;
    }
  };
}

function rgModal(results) {
  return {
    applying: false,
    async apply() {
      this.applying = true;
      const editor = Alpine.$data(document.getElementById('album-editor'));
      await editor.applyRG(results);
      this.applying = false;
    }
  };
}

function organizeModal(previews, paths, currentPattern, currentTarget) {
  return {
    previews,
    paths,
    pattern: currentPattern,
    target: currentTarget,
    applying: false,
    _timer: null,
    tokens: [],
    separators: [],
    _dragSrcIdx: null,
    _dragoverIdx: null,
    _nextId: 1,
    savedPatterns: [],
    showLoadMenu: false,

    init() {
      const parsed = this._parsePattern(this.pattern);
      this.tokens = parsed.tokens;
      this.separators = parsed.separators;
      this.$watch('pattern', () => this._schedulePreview());
      this.$watch('target', () => this._schedulePreview());
      fetch('/api/patterns')
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          this.savedPatterns = data;
          // One-time migration from localStorage
          const legacy = JSON.parse(localStorage.getItem('taglab-org-patterns') || '[]');
          if (legacy.length > 0 && data.length === 0) {
            Promise.all(legacy.map(p =>
              fetch('/api/patterns', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(p),
              })
            )).then(() => {
              localStorage.removeItem('taglab-org-patterns');
              return fetch('/api/patterns').then(r => r.json());
            }).then(migrated => { this.savedPatterns = migrated; });
          }
        });
    },

    _parsePattern(pattern) {
      const parts = pattern.split(/(\{[^}]+\})/);
      const tokens = [], separators = [];
      for (let i = 0; i < parts.length; i++) {
        if (i % 2 === 0) separators.push(parts[i]);
        else tokens.push({ id: this._nextId++, value: parts[i] });
      }
      if (separators.length === tokens.length) separators.push('');
      return { tokens, separators };
    },

    _serializePattern() {
      let s = this.separators[0] || '';
      for (let i = 0; i < this.tokens.length; i++) {
        s += this.tokens[i].value + (this.separators[i + 1] || '');
      }
      return s;
    },

    onPatternChange() {
      this.pattern = this._serializePattern();
    },

    tokenLabel(value) {
      return value.replace(/^\{|\}$/g, '').replace(/:02d$/, '');
    },

    addToken(value) {
      this.tokens.push({ id: this._nextId++, value });
      this.separators.push('');
      this.onPatternChange();
    },

    removeToken(idx) {
      this.tokens.splice(idx, 1);
      this.separators.splice(idx + 1, 1);
      this.onPatternChange();
    },

    async savePattern() {
      const hint = this.tokens.map(t => this.tokenLabel(t.value)).join('-');
      const name = prompt('Save pattern as:', hint);
      if (!name || !name.trim()) return;
      const trimmed = name.trim();
      const resp = await fetch('/api/patterns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed, pattern: this.pattern }),
      });
      if (resp.ok) {
        this.savedPatterns = await fetch('/api/patterns').then(r => r.json());
        showNotification('Pattern saved');
      }
    },

    loadPattern(pattern) {
      const parsed = this._parsePattern(pattern);
      this.tokens = parsed.tokens;
      this.separators = parsed.separators;
      this.showLoadMenu = false;
      this.onPatternChange();
    },

    async deletePattern(name) {
      await fetch('/api/patterns/' + encodeURIComponent(name), { method: 'DELETE' });
      this.savedPatterns = this.savedPatterns.filter(p => p.name !== name);
    },

    dragStart(idx) { this._dragSrcIdx = idx; },
    dragOver(idx)  { this._dragoverIdx = idx; },
    dragLeave(idx) { if (this._dragoverIdx === idx) this._dragoverIdx = null; },
    dragEnd()      { this._dragSrcIdx = null; this._dragoverIdx = null; },
    drop(idx) {
      if (this._dragSrcIdx === null || this._dragSrcIdx === idx) {
        this._dragoverIdx = null;
        return;
      }
      const [moved] = this.tokens.splice(this._dragSrcIdx, 1);
      this.tokens.splice(idx, 0, moved);
      this._dragoverIdx = null;
      this.onPatternChange();
    },

    _schedulePreview() {
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this.rePreview(), 600);
    },

    async rePreview() {
      clearTimeout(this._timer);

      // Save focus state before showModal() replaces the DOM
      const active     = document.activeElement;
      const sepInputs  = [...document.querySelectorAll('.org-sep-input')];
      const focusIdx   = sepInputs.indexOf(active);
      const isTarget   = active?.classList.contains('org-target-input');
      const selStart   = active?.selectionStart ?? null;
      const selEnd     = active?.selectionEnd   ?? null;

      const resp = await fetch('/api/organizer/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: this.paths, pattern: this.pattern, target: this.target })
      });
      showModal(await resp.text());

      // Restore focus to the same input after DOM replacement
      if (isTarget) {
        const el = document.querySelector('.org-target-input');
        el?.focus();
        if (selStart != null) el?.setSelectionRange(selStart, selEnd);
      } else if (focusIdx >= 0) {
        const el = document.querySelectorAll('.org-sep-input')[focusIdx];
        el?.focus();
        if (selStart != null) el?.setSelectionRange(selStart, selEnd);
      }
    },

    async apply() {
      this.applying = true;
      const moves = this.previews
        .filter(p => p.target && !p.error && !p.conflict)
        .map(p => ({ source: p.source, target: p.target }));
      const resp = await fetch('/api/organizer/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ moves })
      });
      hideModal();
      const data = await resp.json();
      const ok = data.results.filter(r => r.ok).length;
      const fail = data.results.filter(r => !r.ok).length;
      showNotification(
        `Moved ${ok} file(s)` + (fail ? `, ${fail} failed` : ''),
        fail > 0
      );
      if (ok > 0) {
        let artist = '';
        const albumEditorEl = document.getElementById('album-editor');
        const artistPageEl = document.querySelector('.artist-page');
        if (albumEditorEl) {
          const editor = Alpine.$data(albumEditorEl);
          artist = editor ? editor.shared.albumartist : '';
        } else if (artistPageEl) {
          const page = Alpine.$data(artistPageEl);
          artist = page ? page._artist : '';
        }
        htmx.ajax('GET', '/ui/explorer', { target: '#explorer-root', swap: 'innerHTML' });
        if (artist) {
          htmx.ajax('GET', '/ui/artist?artist=' + encodeURIComponent(artist), { target: '#editor-panel', swap: 'innerHTML' });
        } else {
          document.getElementById('editor-panel').innerHTML = '';
        }
      }
    }
  };
}

function bulkEditModal(albumFolders, artist) {
  return {
    albumFolders,
    artist,
    previewing: false,
    shared: {
      album: '',
      albumartist: '',
      date: '',
      genre: '',
      label: '',
      country: '',
      musicbrainz_albumid: '',
      musicbrainz_albumartistid: '',
      musicbrainz_releasegroupid: '',
    },

    async previewSave() {
      const filtered = Object.fromEntries(
        Object.entries(this.shared).filter(([, v]) => String(v).trim())
      );
      if (!Object.keys(filtered).length) {
        showNotification('No fields filled in — nothing to update', true);
        return;
      }
      this.previewing = true;
      try {
        const resp = await fetch('/api/album/bulk-preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ album_folders: this.albumFolders, shared_tags: filtered }),
        });
        if (!resp.ok) {
          const d = await resp.json().catch(() => ({}));
          showNotification(d.detail || 'Preview failed', true);
          return;
        }
        showModal(await resp.text());
      } catch (e) {
        showNotification('Preview failed: ' + e.message, true);
      } finally {
        this.previewing = false;
      }
    },
  };
}

function bulkPreviewModal(payload) {
  return {
    applying: false,
    async apply() {
      this.applying = true;
      try {
        const resp = await fetch('/api/album/bulk-save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        hideModal();
        const data = await resp.json();
        showNotification(
          resp.ok ? `Saved ${data.saved} file(s)` : (data.detail || 'Save failed'),
          !resp.ok
        );
      } catch (e) {
        hideModal();
        showNotification('Save failed: ' + e.message, true);
      }
    },
  };
}

function mbModal() { return {}; }
