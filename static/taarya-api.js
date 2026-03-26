/**
 * TaarYa — Shared API Client & Render Helpers
 * Include this in every screen BEFORE screen-specific scripts:
 *   <script src="/static/taarya-api.js"></script>
 */
(function (global) {
    'use strict';

    const BASE = '';   // same origin

    /* ── Utilities ─────────────────────────────────────────── */
    async function _get(path) {
        const r = await fetch(BASE + path);
        if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
        return r.json();
    }

    async function _post(path, body) {
        const r = await fetch(BASE + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
        return r.json();
    }

    function qs(params) {
        const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null);
        return p.length ? '?' + p.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&') : '';
    }

    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = String(reader.result || '');
                const comma = result.indexOf(',');
                resolve(comma >= 0 ? result.slice(comma + 1) : result);
            };
            reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
            reader.readAsDataURL(file);
        });
    }

    /* ── API Layer ──────────────────────────────────────────── */
    const api = {
        stats:   () => _get('/api/stats'),
        regions: () => _get('/api/regions'),
        spaceVolume: ({ limit = 8000, minParallax, magLimit } = {}) =>
            _get('/api/stars/space-volume' + qs({
                limit,
                min_parallax: minParallax,
                mag_limit: magLimit,
            })),
        discovery: ({ limit = 15, poolLimit = 3000, radiusDeg = 0.08, mode = 'balanced' } = {}) =>
            _get('/api/stars/discovery' + qs({
                limit,
                pool_limit: poolLimit,
                radius_deg: radiusDeg,
                mode,
            })),

        ingestionStatus: () => _get('/api/ingest/status'),
        ingestCatalog: ({ catalogSource, filepath, limit, fieldMap } = {}) =>
            _post('/api/ingest/catalog', {
                catalog_source: catalogSource,
                filepath,
                limit,
                field_map: fieldMap,
            }),

        uploadCatalog: async ({ catalogSource, file, limit, fieldMap } = {}) => {
            if (!file) throw new Error('A file must be selected before upload');
            const contentBase64 = await readFileAsBase64(file);
            return _post('/api/ingest/catalog/upload', {
                catalog_source: catalogSource,
                filename: file.name || 'upload.csv',
                content_base64: contentBase64,
                limit,
                field_map: fieldMap,
            });
        },

        // Stars
        coneSearch: (ra, dec, radius, { magLimit, minParallax, limit = 100 } = {}) =>
            _get('/api/stars/cone-search' + qs({ ra, dec, radius, mag_limit: magLimit, min_parallax: minParallax, limit })),

        lookupStar: (sourceId) => _get(`/api/stars/lookup/${encodeURIComponent(sourceId)}`),

        nearbyStar: (sourceId, { radius = 0.5, limit = 50 } = {}) =>
            _get(`/api/stars/nearby/${encodeURIComponent(sourceId)}` + qs({ radius, limit })),

        countStars: (ra, dec, radius) => _get('/api/stars/count' + qs({ ra, dec, radius })),

        // Papers
        searchPapers: (q, limit = 10) => _get('/api/papers/search' + qs({ q, limit })),
        papersByTopic: (keyword, limit = 20) => _get('/api/papers/topic' + qs({ keyword, limit })),
        papersByStar: (sourceId) => _get(`/api/papers/by-star/${encodeURIComponent(sourceId)}`),

        // Hybrid search
        hybridSearch: ({ q, ra, dec, radius, sourceId, limit = 20 } = {}) =>
            _get('/api/search/hybrid' + qs({ q, ra, dec, radius, source_id: sourceId, limit })),

        coneWithContext: (ra, dec, radius, limit = 50) =>
            _get('/api/search/cone-with-context' + qs({ ra, dec, radius, limit })),

        // Agent
        ask: (query, chatHistory = null) =>
            _post('/api/agent/ask', { query, chat_history: chatHistory }),

        askStream: async (query, chatHistory, onEvent) => {
            const r = await fetch(BASE + '/api/agent/ask/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, chat_history: chatHistory }),
            });
            if (!r.ok) throw new Error(`POST /api/agent/ask/stream → ${r.status}`);

            const reader = r.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const chunks = buffer.split(/\r?\n\r?\n/);
                buffer = chunks.pop() || '';

                for (const chunk of chunks) {
                    const dataLines = chunk
                        .split(/\r?\n/)
                        .filter(line => line.startsWith('data:'))
                        .map(line => line.slice(5).trimStart());

                    if (!dataLines.length) continue;

                    try {
                        const parsed = JSON.parse(dataLines.join('\n'));
                        onEvent(parsed);
                    } catch (e) {
                        // skip malformed
                    }
                }
            }
        },
    };

    /* ── Export Helpers ─────────────────────────────────────── */
    const STAR_COLS = ['source_id', 'ra', 'dec', 'phot_g_mean_mag', 'parallax', 'pmra', 'pmdec'];

    function exportCSV(stars) {
        const header = STAR_COLS.join(',');
        const rows = stars.map(s =>
            STAR_COLS.map(k => {
                const v = s[k];
                if (v === null || v === undefined) return '';
                return typeof v === 'string' && v.includes(',') ? `"${v}"` : v;
            }).join(',')
        );
        const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv' });
        _triggerDownload(blob, 'taarya_stars.csv');
    }

    function exportJSON(stars) {
        const blob = new Blob([JSON.stringify(stars, null, 2)], { type: 'application/json' });
        _triggerDownload(blob, 'taarya_stars.json');
    }

    function _triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    /* ── Render Helpers ─────────────────────────────────────── */
    const render = {

        /** Card for a single star */
        starCard: (star, { clickable = false } = {}) => {
            const dist = star.parallax && star.parallax > 0
                ? (1000 / star.parallax).toFixed(1) + ' ly'
                : '—';
            const mag = star.phot_g_mean_mag != null ? star.phot_g_mean_mag.toFixed(2) : '—';
            const ra = star.ra != null ? star.ra.toFixed(4) : '—';
            const dec = star.dec != null ? star.dec.toFixed(4) : '—';
            return `
        <div class="ty-star-card${clickable ? ' cursor-pointer hover:border-primary/50' : ''}"
             data-source-id="${star.source_id || ''}"
             style="padding:12px 14px;border:1px solid var(--panel-border, rgba(255,255,255,0.07));border-radius:8px;
                    background:var(--panel-bg, rgba(255,255,255,0.03));margin-bottom:8px;transition:border-color 0.2s, transform 0.2s;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <div>
              <div style="font-size:12px;font-family:monospace;color:var(--text-primary);letter-spacing:.5px;">${star.source_id || 'Unknown'}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">RA ${ra}° · Dec ${dec}°</div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
              <div style="font-size:14px;font-weight:600;color:var(--text-primary);">G ${mag}</div>
              <div style="font-size:11px;color:var(--text-muted);">${dist}</div>
            </div>
          </div>
          ${star.angular_distance != null ? `<div style="font-size:10px;color:var(--text-muted);margin-top:6px;">θ = ${(star.angular_distance * 60).toFixed(2)}′ from centre</div>` : ''}
        </div>`;
        },

        /** Card for a paper */
        paperCard: (paper, { clickable = false } = {}) => {
            const authorsRaw = Array.isArray(paper.authors)
                ? paper.authors
                : (paper.authors || '').split(',');
            const authors = authorsRaw.slice(0, 2).join(', ') + (authorsRaw.length > 2 ? ' et al.' : '');
            const date = paper.published_date ? paper.published_date.slice(0, 7) : '';
            const score = paper.score != null ? (paper.score * 100).toFixed(0) + '% match' : '';
            const catsRaw = Array.isArray(paper.categories)
                ? paper.categories
                : (paper.categories || '').split(' ');
            const cats = catsRaw.slice(0, 2).map(c =>
                `<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:var(--accent-soft);color:var(--text-primary);">${c}</span>`
            ).join(' ');
            return `
        <div class="ty-paper-card${clickable ? ' cursor-pointer hover:border-primary/40' : ''}"
             data-arxiv-id="${paper.arxiv_id || ''}"
             style="padding:12px 14px;border:1px solid var(--panel-border, rgba(255,255,255,0.07));border-radius:8px;
                    background:var(--panel-bg, rgba(255,255,255,0.03));margin-bottom:10px;transition:border-color 0.2s, transform 0.2s;">
          <div style="display:flex;align-items:flex-start;gap:10px;">
            <div style="flex:1;min-width:0;">
              <div style="font-size:13px;font-weight:600;color:var(--text-primary);line-height:1.4;">${paper.title || 'Untitled'}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">${authors}</div>
              <div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">${cats}</div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
              ${date ? `<div style="font-size:10px;color:var(--text-muted);">${date}</div>` : ''}
              ${score ? `<div style="font-size:10px;color:var(--text-primary);margin-top:2px;">${score}</div>` : ''}
              ${paper.arxiv_id ? `<a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank"
                   style="font-size:10px;color:var(--text-primary);display:block;margin-top:4px;">arXiv ↗</a>` : ''}
            </div>
          </div>
          ${paper.abstract ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:8px;line-height:1.5;
                                   display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
            ${paper.abstract}</div>` : ''}
        </div>`;
        },

        /** Status badge for a backend */
        statusBadge: (name, statusObj) => {
            const ok = statusObj && statusObj.status !== 'error' && statusObj.status !== 'disconnected';
            const color = ok ? '#10b981' : '#ef4444';
            const label = ok ? 'ONLINE' : 'OFFLINE';
            return `<span style="font-size:10px;padding:2px 8px;border-radius:12px;
                           background:${color}22;color:${color};border:1px solid ${color}44;">
                ${name}: ${label}</span>`;
        },

        /** Empty state for lists */
        emptyState: (msg = 'No results found') =>
            `<div style="text-align:center;padding:32px 16px;color:var(--text-secondary);">
         <span class="material-icons" style="font-size:36px;opacity:.4;display:block;margin-bottom:8px;">search_off</span>
         <div style="font-size:13px;">${msg}</div>
       </div>`,

        /** Loading spinner */
        spinner: () =>
            `<div style="text-align:center;padding:24px;">
         <div style="width:24px;height:24px;border:2px solid var(--accent-soft);border-top-color:var(--accent);
                     border-radius:50%;animation:ty-spin 0.7s linear infinite;display:inline-block;"></div>
       </div>`,

        /** Agent message bubble */
        agentMessage: (text, role = 'assistant') => {
            const isUser = role === 'user';
            return `
        <div style="display:flex;gap:10px;${isUser ? 'flex-direction:row-reverse;' : ''}margin-bottom:16px;">
          <div style="width:28px;height:28px;border-radius:50%;flex-shrink:0;
                      background:${isUser ? 'linear-gradient(135deg,#7c3aed,#2547f4)' : 'linear-gradient(135deg,#0ea5e9,#2547f4)'};
                      display:flex;align-items:center;justify-content:center;">
            <span class="material-icons" style="font-size:14px;color:white;">${isUser ? 'person' : 'smart_toy'}</span>
          </div>
          <div style="flex:1;max-width:85%;">
            <div style="font-size:11px;color:#475569;margin-bottom:4px;">${isUser ? 'You' : 'TaarYa'}</div>
            <div style="font-size:13px;line-height:1.6;color:#cbd5e1;
                        background:${isUser ? 'rgba(37,71,244,.12)' : 'rgba(255,255,255,.05)'};
                        border:1px solid ${isUser ? 'rgba(37,71,244,.25)' : 'rgba(255,255,255,.08)'};
                        border-radius:${isUser ? '12px 2px 12px 12px' : '2px 12px 12px 12px'};
                        padding:10px 14px;">${text}</div>
          </div>
        </div>`;
        },

        /**
         * Full star results table with scrollable container + export buttons.
         * Replaces the old truncated resultTable.
         * @param {Array} stars
         * @param {number} maxRows - rows shown initially before "Show all" (used in agent context only)
         */
        resultTable: (stars = [], maxRows = 25) => {
            if (!stars.length) return '';

            // Generate a unique id so multiple tables on one page don't collide
            const uid = 'tbl-' + Math.random().toString(36).slice(2, 7);

            const rowsHTML = stars.map((s, i) => `
                <tr style="border-bottom:1px solid rgba(255,255,255,.04);${i % 2 === 0 ? 'background:rgba(255,255,255,.015)' : ''}"
                    class="star-row">
                  <td style="padding:7px 10px;color:#94a3b8;font-size:11px;white-space:nowrap;">${s.source_id || '—'}</td>
                  <td style="padding:7px 10px;color:#cbd5e1;text-align:right;white-space:nowrap;">${s.ra?.toFixed(5) ?? '—'}</td>
                  <td style="padding:7px 10px;color:#cbd5e1;text-align:right;white-space:nowrap;">${s.dec?.toFixed(5) ?? '—'}</td>
                  <td style="padding:7px 10px;color:#fbbf24;text-align:right;white-space:nowrap;">${s.phot_g_mean_mag?.toFixed(2) ?? '—'}</td>
                  <td style="padding:7px 10px;color:#6ee7b7;text-align:right;white-space:nowrap;">${s.parallax?.toFixed(3) ?? '—'}</td>
                  <td style="padding:7px 10px;color:#a5b4fc;text-align:right;white-space:nowrap;">${s.pmra?.toFixed(2) ?? '—'}</td>
                  <td style="padding:7px 10px;color:#a5b4fc;text-align:right;white-space:nowrap;">${s.pmdec?.toFixed(2) ?? '—'}</td>
                </tr>`).join('');

            // Store stars on window so export handlers can access them
            window._taarya_export = window._taarya_export || {};
            window._taarya_export[uid] = stars;

            return `
        <div style="margin-top:12px;">
          <!-- Toolbar -->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
            <span style="font-size:11px;color:#64748b;font-family:'JetBrains Mono',monospace;">
              ${stars.length} star${stars.length !== 1 ? 's' : ''}
            </span>
            <div style="display:flex;gap:6px;">
              <button onclick="window._taarya_export_csv('${uid}')"
                style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;
                       font-size:11px;font-family:inherit;cursor:pointer;border-radius:5px;
                       background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
                       color:#94a3b8;transition:all .15s;"
                onmouseover="this.style.background='rgba(255,255,255,0.08)';this.style.color='#e2e8f0';"
                onmouseout="this.style.background='rgba(255,255,255,0.04)';this.style.color='#94a3b8';">
                <span class="material-icons" style="font-size:13px;">download</span> CSV
              </button>
              <button onclick="window._taarya_export_json('${uid}')"
                style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;
                       font-size:11px;font-family:inherit;cursor:pointer;border-radius:5px;
                       background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
                       color:#94a3b8;transition:all .15s;"
                onmouseover="this.style.background='rgba(255,255,255,0.08)';this.style.color='#e2e8f0';"
                onmouseout="this.style.background='rgba(255,255,255,0.04)';this.style.color='#94a3b8';">
                <span class="material-icons" style="font-size:13px;">data_object</span> JSON
              </button>
            </div>
          </div>

          <!-- Scrollable table wrapper -->
          <div style="overflow:auto;max-height:480px;border:1px solid rgba(255,255,255,0.07);
                      border-radius:8px;background:rgba(255,255,255,0.02);">
            <table id="${uid}" style="width:100%;border-collapse:collapse;font-size:11px;
                                      font-family:'JetBrains Mono',monospace;min-width:620px;">
              <thead>
                <tr style="position:sticky;top:0;background:#111;z-index:1;border-bottom:1px solid rgba(255,255,255,.12);">
                  <th style="text-align:left;padding:8px 10px;color:#475569;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">Source ID</th>
                  <th style="text-align:right;padding:8px 10px;color:#475569;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">RA °</th>
                  <th style="text-align:right;padding:8px 10px;color:#475569;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">Dec °</th>
                  <th style="text-align:right;padding:8px 10px;color:#fbbf2488;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">G mag</th>
                  <th style="text-align:right;padding:8px 10px;color:#6ee7b788;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">Parallax mas</th>
                  <th style="text-align:right;padding:8px 10px;color:#a5b4fc88;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">pmRA</th>
                  <th style="text-align:right;padding:8px 10px;color:#a5b4fc88;font-size:10px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap;">pmDec</th>
                </tr>
              </thead>
              <tbody>${rowsHTML}</tbody>
            </table>
          </div>
        </div>`;
        },
    };

    /* ── Export handlers (global, called from inline onclick) ── */
    window._taarya_export_csv = function(uid) {
        const stars = (window._taarya_export || {})[uid];
        if (stars) exportCSV(stars);
    };
    window._taarya_export_json = function(uid) {
        const stars = (window._taarya_export || {})[uid];
        if (stars) exportJSON(stars);
    };

    /* ── Navigation helper ──────────────────────────────────── */
    function goToStar(sourceId) {
        window.location.href = `/static/stellar_detail.html?id=${encodeURIComponent(sourceId)}`;
    }

    /* ── CSS keyframe for spinner ───────────────────────────── */
    const style = document.createElement('style');
    style.textContent = '@keyframes ty-spin { to { transform: rotate(360deg); } }';
    document.head.appendChild(style);

    /* ── Expose globals ─────────────────────────────────────── */
    global.TaarYa = { api, render, goToStar, exportCSV, exportJSON };

})(window);
