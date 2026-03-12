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

    /* ── API Layer ──────────────────────────────────────────── */
    const api = {
        stats: () => _get('/api/stats'),

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

        /**
         * Stream agent response via SSE.
         * @param {string} query
         * @param {Array|null} chatHistory
         * @param {function} onEvent - called with {type, data} for each event
         * @returns {Promise<void>} resolves when stream ends
         */
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
             style="padding:12px 14px;border:1px solid rgba(255,255,255,0.07);border-radius:8px;
                    background:rgba(255,255,255,0.03);margin-bottom:8px;transition:border-color 0.2s;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <div>
              <div style="font-size:12px;font-family:monospace;color:#94a3b8;letter-spacing:.5px;">${star.source_id || 'Unknown'}</div>
              <div style="font-size:11px;color:#475569;margin-top:2px;">RA ${ra}° · Dec ${dec}°</div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
              <div style="font-size:14px;font-weight:600;color:#e2e8f0;">G ${mag}</div>
              <div style="font-size:11px;color:#475569;">${dist}</div>
            </div>
          </div>
          ${star.angular_distance != null ? `<div style="font-size:10px;color:#334155;margin-top:6px;">θ = ${(star.angular_distance * 60).toFixed(2)}′ from centre</div>` : ''}
        </div>`;
        },

        /** Card for a paper */
        paperCard: (paper, { clickable = false } = {}) => {
            const authors = paper.authors ? paper.authors.split(',').slice(0, 2).join(', ') + (paper.authors.split(',').length > 2 ? ' et al.' : '') : '—';
            const date = paper.published_date ? paper.published_date.slice(0, 7) : '';
            const score = paper.score != null ? (paper.score * 100).toFixed(0) + '% match' : '';
            const cats = (paper.categories || '').split(' ').slice(0, 2).map(c =>
                `<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:rgba(37,71,244,0.18);color:#93c5fd;">${c}</span>`
            ).join(' ');
            return `
        <div class="ty-paper-card${clickable ? ' cursor-pointer hover:border-primary/40' : ''}"
             data-arxiv-id="${paper.arxiv_id || ''}"
             style="padding:12px 14px;border:1px solid rgba(255,255,255,0.07);border-radius:8px;
                    background:rgba(255,255,255,0.03);margin-bottom:10px;transition:border-color 0.2s;">
          <div style="display:flex;align-items:flex-start;gap:10px;">
            <div style="flex:1;min-width:0;">
              <div style="font-size:13px;font-weight:600;color:#e2e8f0;line-height:1.4;">${paper.title || 'Untitled'}</div>
              <div style="font-size:11px;color:#64748b;margin-top:4px;">${authors}</div>
              <div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">${cats}</div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
              ${date ? `<div style="font-size:10px;color:#475569;">${date}</div>` : ''}
              ${score ? `<div style="font-size:10px;color:#2547f4;margin-top:2px;">${score}</div>` : ''}
              ${paper.arxiv_id ? `<a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank"
                   style="font-size:10px;color:#3b82f6;display:block;margin-top:4px;">arXiv ↗</a>` : ''}
            </div>
          </div>
          ${paper.abstract ? `<div style="font-size:11px;color:#475569;margin-top:8px;line-height:1.5;
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
            `<div style="text-align:center;padding:32px 16px;color:#475569;">
         <span class="material-icons" style="font-size:36px;opacity:.4;display:block;margin-bottom:8px;">search_off</span>
         <div style="font-size:13px;">${msg}</div>
       </div>`,

        /** Loading spinner */
        spinner: () =>
            `<div style="text-align:center;padding:24px;">
         <div style="width:24px;height:24px;border:2px solid rgba(37,71,244,.3);border-top-color:#2547f4;
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

        /** Inline star data table from agent tool results */
        resultTable: (stars = [], maxRows = 5) => {
            if (!stars.length) return '';
            const shown = stars.slice(0, maxRows);
            return `<div style="margin-top:10px;overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:11px;font-family:monospace;">
          <thead><tr style="border-bottom:1px solid rgba(255,255,255,.1);">
            <th style="text-align:left;padding:4px 8px;color:#64748b;">Source ID</th>
            <th style="text-align:right;padding:4px 8px;color:#64748b;">RA</th>
            <th style="text-align:right;padding:4px 8px;color:#64748b;">Dec</th>
            <th style="text-align:right;padding:4px 8px;color:#64748b;">G mag</th>
            <th style="text-align:right;padding:4px 8px;color:#64748b;">Parallax</th>
          </tr></thead>
          <tbody>${shown.map((s, i) => `
            <tr style="border-bottom:1px solid rgba(255,255,255,.04);${i % 2 === 0 ? 'background:rgba(255,255,255,.02)' : ''}">
              <td style="padding:4px 8px;color:#94a3b8;font-size:10px;">${s.source_id || '—'}</td>
              <td style="padding:4px 8px;color:#cbd5e1;text-align:right;">${s.ra?.toFixed(4) ?? '—'}</td>
              <td style="padding:4px 8px;color:#cbd5e1;text-align:right;">${s.dec?.toFixed(4) ?? '—'}</td>
              <td style="padding:4px 8px;color:#fbbf24;text-align:right;">${s.phot_g_mean_mag?.toFixed(2) ?? '—'}</td>
              <td style="padding:4px 8px;color:#6ee7b7;text-align:right;">${s.parallax?.toFixed(3) ?? '—'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
        ${stars.length > maxRows ? `<div style="font-size:10px;color:#475569;padding:4px 8px;">${stars.length - maxRows} more results…</div>` : ''}
      </div>`;
        }
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
    global.TaarYa = { api, render, goToStar };

})(window);
