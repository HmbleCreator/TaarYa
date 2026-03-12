(function() {
  'use strict';
  const { api } = TaarYa;

  const messagesEl = document.getElementById('chat-messages');
  const inputEl    = document.getElementById('chat-input');
  const sendBtn    = document.getElementById('chat-send');
  const welcomeEl  = document.getElementById('welcome');
  const countEl    = document.getElementById('query-count');
  const toggleBtn  = document.getElementById('theme-toggle');
  const welcomeTemplate = messagesEl.innerHTML;

  let chatHistory = [];
  let activeSessionId = null;
  let sending = false;
  let queryCount = 0;

  // ─── Helpers ────────────────────────────────────────────
  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addHTML(html) {
    const currentWelcomeEl = document.getElementById('welcome');
    if (currentWelcomeEl) currentWelcomeEl.style.display = 'none';
    messagesEl.insertAdjacentHTML('beforeend', html);
    scrollBottom();
  }

  function escapeHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function formatAnswer(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
    html = html.replace(/\|(.+)\|/g, (match) => {
      const cells = match.split('|').filter(c => c.trim());
      if (cells.every(c => /^[-:]+$/.test(c.trim()))) return '';
      return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
    });
    html = html.replace(/\n/g, '<br>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');
    return html;
  }

  // Tool icon & label maps
  const toolIcons = {
    'cone_search': 'radar',
    'star_lookup': 'star',
    'find_nearby_stars': 'scatter_plot',
    'semantic_search': 'article',
    'graph_query': 'hub',
    'count_stars_in_region': 'grid_on',
  };

  const toolLabels = {
    'cone_search': 'Scanning sky coordinates',
    'star_lookup': 'Querying Gaia catalog',
    'find_nearby_stars': 'Finding nearby objects',
    'semantic_search': 'Searching arXiv papers',
    'graph_query': 'Traversing knowledge graph',
    'count_stars_in_region': 'Counting objects in region',
  };

  function parseMaybeObject(input) {
    if (!input || typeof input !== 'string') return input || null;
    const raw = input.trim();
    try {
      return JSON.parse(raw);
    } catch (err) {
      try {
        return JSON.parse(raw.replace(/'/g, '"').replace(/\bNone\b/g, 'null').replace(/\bTrue\b/g, 'true').replace(/\bFalse\b/g, 'false'));
      } catch (err2) {
        return raw;
      }
    }
  }

  function regionLabelFromInput(toolName, params) {
    if (!params || typeof params !== 'object') return toolLabels[toolName] || toolName;
    const ra = Number(params.ra);
    const dec = Number(params.dec);
    if (toolName === 'cone_search') {
      if (Math.abs(ra - 83.82) < 1 && Math.abs(dec + 5.39) < 1) return 'Orion Nebula';
      if (Math.abs(ra - 56.75) < 1 && Math.abs(dec - 24.12) < 1) return 'Pleiades M45';
      if (Math.abs(ra - 266.4) < 1 && Math.abs(dec + 29.0) < 1) return 'Galactic Center';
      return `Cone Search · RA ${ra.toFixed(2)}° Dec ${dec.toFixed(2)}°`;
    }
    return toolLabels[toolName] || toolName;
  }

  function summarizeParams(params) {
    if (!params) return '';
    if (typeof params === 'string') return params;
    return Object.entries(params)
      .map(([key, value]) => `${key}: ${typeof value === 'number' ? value : String(value)}`)
      .join('\n');
  }

  function getStepState(preview) {
    const text = (preview || '').toLowerCase();
    if (!text) return 'running';
    if (text.includes('error')) return 'error';
    if (text.includes('no ') || text.includes('not found') || text.includes('0 papers') || text.includes('0 results') || text.includes('empty')) return 'empty';
    return 'success';
  }

  function iconForState(state) {
    if (state === 'success') return '✓';
    if (state === 'empty') return '•';
    if (state === 'error') return '×';
    return '○';
  }

  function shortSourceId(value) {
    const text = String(value || '—');
    return text.length > 13 ? `${text.slice(0, 7)}…${text.slice(-6)}` : text;
  }

  function distancePc(star) {
    const parallax = Number(star.parallax);
    if (!Number.isFinite(parallax) || parallax <= 0) return '—';
    return (1000 / parallax).toFixed(1);
  }

  function detectDuplicateMeasurements(rows) {
    const seen = new Set();
    let duplicates = 0;
    rows.forEach((row) => {
      const key = [
        Number(row.ra || 0).toFixed(6),
        Number(row.dec || 0).toFixed(6),
        Number(row.parallax || 0).toFixed(6),
        Number((row.phot_g_mean_mag ?? row.gmag) || 0).toFixed(6),
      ].join('|');
      if (seen.has(key)) duplicates += 1;
      else seen.add(key);
    });
    return duplicates;
  }

  function updateProcessSummary(thinkingId, streamState) {
    const summaryEl = document.getElementById(`${thinkingId}-summary`);
    const stateEl = document.getElementById(`${thinkingId}-process-state`);
    if (!summaryEl || !stateEl) return;

    const steps = streamState.steps || [];
    const successCount = steps.filter(step => step.state === 'success').length;
    const emptyCount = steps.filter(step => step.state === 'empty').length;
    const errorCount = steps.filter(step => step.state === 'error').length;
    const duration = ((Date.now() - streamState.startedAt) / 1000).toFixed(1);

    let stateClass = 'running';
    let stateText = 'working';
    if (errorCount > 0 && successCount === 0) {
      stateClass = 'error';
      stateText = 'error';
    } else if (successCount > 0) {
      stateClass = 'success';
      stateText = 'complete';
    } else if (emptyCount > 0) {
      stateClass = 'empty';
      stateText = 'no results';
    }

    stateEl.className = `process-state ${stateClass}`;
    stateEl.textContent = stateText;

    const stats = [];
    if (successCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--success)"></span>${successCount} success</span>`);
    if (emptyCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--warning)"></span>${emptyCount} empty</span>`);
    if (errorCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--error)"></span>${errorCount} error</span>`);
    stats.push(`<span class="summary-stat">${steps.length} tool${steps.length === 1 ? '' : 's'} · ${duration}s</span>`);
    summaryEl.innerHTML = stats.join('');
  }

  function setLiveMessage(thinkingId, message) {
    const liveTextEl = document.getElementById(`${thinkingId}-live-text`);
    if (liveTextEl) liveTextEl.innerHTML = message;
  }

  function hideLiveMessage(thinkingId) {
    const liveEl = document.getElementById(`${thinkingId}-live`);
    if (liveEl) liveEl.style.display = 'none';
  }

  function addThinking(thinkingId) {
    const html = `
      <div class="thinking-container" id="${thinkingId}">
        <div class="live-step" id="${thinkingId}-live">
          <div class="live-spinner"></div>
          <span id="${thinkingId}-live-text">Thinking… decomposing query</span>
        </div>
        <details class="agent-process" id="${thinkingId}-process">
          <summary class="process-header">
            <span>⚡</span>
            <span class="process-title">Research Trace</span>
            <span class="process-state running" id="${thinkingId}-process-state">working</span>
            <span class="process-chevron">▼</span>
          </summary>
          <div class="process-steps" id="${thinkingId}-steps"></div>
          <div class="process-summary" id="${thinkingId}-summary"></div>
        </details>
      </div>`;
    addHTML(html);
  }

  function handleEvent(thinkingId, event, streamState) {
    const processEl = document.getElementById(`${thinkingId}-process`);
    const stepsEl = document.getElementById(`${thinkingId}-steps`);
    if (!processEl || !stepsEl) return;

    const { type, data } = event;

    if (type === 'thinking') {
      setLiveMessage(thinkingId, escapeHtml(data.status || 'Thinking…'));
      return;
    }

    if (type === 'tool_start') {
      const toolName = data.tool || 'unknown';
      const params = parseMaybeObject(data.input);
      const label = regionLabelFromInput(toolName, params);
      const stepId = `${thinkingId}-step-${streamState.steps.length + 1}`;

      streamState.steps.push({ id: stepId, tool: toolName, params, label, state: 'running', preview: '' });
      setLiveMessage(thinkingId, `<strong>${escapeHtml(toolName)}</strong> · <span class="coord">${escapeHtml(label)}</span> · scanning…`);

      const stepHtml = `
        <details class="step" id="${stepId}">
          <summary>
            <div class="step-icon running">${iconForState('running')}</div>
            <div class="step-copy">
              <div class="step-label">${escapeHtml(toolName)} — ${escapeHtml(label)}</div>
              <div class="step-result">running…</div>
            </div>
          </summary>
          ${data.input ? `<div class="step-params">${escapeHtml(summarizeParams(params))}</div>` : ''}
        </details>`;
      stepsEl.insertAdjacentHTML('beforeend', stepHtml);
      updateProcessSummary(thinkingId, streamState);
      scrollBottom();
      return;
    }

    if (type === 'tool_end') {
      const step = streamState.steps[streamState.steps.length - 1];
      if (!step) return;

      const preview = data.output_preview || 'Completed';
      const state = getStepState(preview);
      step.state = state;
      step.preview = preview;

      const stepEl = document.getElementById(step.id);
      if (stepEl) {
        const iconEl = stepEl.querySelector('.step-icon');
        const resultEl = stepEl.querySelector('.step-result');
        if (iconEl) {
          iconEl.className = `step-icon ${state}`;
          iconEl.textContent = iconForState(state);
        }
        if (resultEl) {
          resultEl.className = `step-result ${state}`;
          resultEl.textContent = preview;
        }
      }

      updateProcessSummary(thinkingId, streamState);
      setLiveMessage(thinkingId, `<strong>${escapeHtml(step.tool)}</strong> · ${escapeHtml(preview)}`);
      scrollBottom();
      return;
    }

    if (type === 'error') {
      const stepId = `${thinkingId}-step-${streamState.steps.length + 1}`;
      streamState.steps.push({
        id: stepId,
        tool: 'system',
        params: null,
        label: 'Agent error',
        state: 'error',
        preview: data.message || 'Unknown error',
      });

      stepsEl.insertAdjacentHTML('beforeend', `
        <details class="step" id="${stepId}">
          <summary>
            <div class="step-icon error">${iconForState('error')}</div>
            <div class="step-copy">
              <div class="step-label">system — Agent error</div>
              <div class="step-result error">${escapeHtml(data.message || 'Unknown error')}</div>
            </div>
          </summary>
        </details>`);
      updateProcessSummary(thinkingId, streamState);
      setLiveMessage(thinkingId, escapeHtml(data.message || 'Unknown error'));
      scrollBottom();
    }
  }

  function finishThinkingCompact(thinkingId, streamState) {
    const container = document.getElementById(thinkingId);
    const processEl = document.getElementById(`${thinkingId}-process`);
    if (!container || !processEl) return;

    hideLiveMessage(thinkingId);
    updateProcessSummary(thinkingId, streamState);

    if (!(streamState.steps || []).length) {
      container.remove();
      return;
    }

    processEl.open = false;
  }

  function addUserMsg(text) {
    addHTML(`
      <div class="msg user">
        <div class="msg-avatar"><span class="material-icons">person</span></div>
        <div class="msg-body">
          <div class="msg-sender">You</div>
          <div class="msg-bubble">${escapeHtml(text)}</div>
        </div>
      </div>`);
  }

  function summarizeToolOutputData(toolOutput) {
    if (!toolOutput || toolOutput.data == null) return 'Completed';
    if (Array.isArray(toolOutput.data)) {
      return `Returned ${toolOutput.data.length} result${toolOutput.data.length === 1 ? '' : 's'}`;
    }
    if (typeof toolOutput.data === 'object') {
      if (typeof toolOutput.data.count === 'number') {
        return `Found ${toolOutput.data.count} result${toolOutput.data.count === 1 ? '' : 's'}`;
      }
      if (toolOutput.data.message) {
        return String(toolOutput.data.message);
      }
    }
    return 'Completed';
  }

  function buildTraceAccordion(trace) {
    const toolsUsed = Array.isArray(trace?.tools_used) ? trace.tools_used : [];
    const toolOutputs = Array.isArray(trace?.tool_outputs) ? trace.tool_outputs : [];

    if (!toolsUsed.length && !toolOutputs.length) return '';

    const outputByTool = new Map();
    toolOutputs.forEach((item) => {
      if (!outputByTool.has(item.tool)) outputByTool.set(item.tool, item);
    });

    const steps = toolsUsed.map((tool, index) => {
      const params = parseMaybeObject(tool.input);
      const label = regionLabelFromInput(tool.tool, params);
      const output = outputByTool.get(tool.tool);
      const preview = tool.output_preview || summarizeToolOutputData(output);
      const state = getStepState(preview);

      return `
        <details class="step" id="saved-step-${index + 1}">
          <summary>
            <div class="step-icon ${state}">${iconForState(state)}</div>
            <div class="step-copy">
              <div class="step-label">${escapeHtml(tool.tool)} â€” ${escapeHtml(label)}</div>
              <div class="step-result ${state}">${escapeHtml(preview)}</div>
            </div>
          </summary>
          ${tool.input ? `<div class="step-params">${escapeHtml(summarizeParams(params))}</div>` : ''}
        </details>`;
    });

    const successCount = steps.filter((_, index) => getStepState(toolsUsed[index].output_preview || summarizeToolOutputData(outputByTool.get(toolsUsed[index].tool))) === 'success').length;
    const emptyCount = steps.filter((_, index) => getStepState(toolsUsed[index].output_preview || summarizeToolOutputData(outputByTool.get(toolsUsed[index].tool))) === 'empty').length;
    const errorCount = steps.filter((_, index) => getStepState(toolsUsed[index].output_preview || summarizeToolOutputData(outputByTool.get(toolsUsed[index].tool))) === 'error').length;

    let stateClass = 'running';
    let stateText = 'working';
    if (errorCount > 0 && successCount === 0) {
      stateClass = 'error';
      stateText = 'error';
    } else if (successCount > 0) {
      stateClass = 'success';
      stateText = 'complete';
    } else if (emptyCount > 0) {
      stateClass = 'empty';
      stateText = 'no results';
    }

    const stats = [];
    if (successCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--success)"></span>${successCount} success</span>`);
    if (emptyCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--warning)"></span>${emptyCount} empty</span>`);
    if (errorCount) stats.push(`<span class="summary-stat"><span class="summary-dot" style="background:var(--error)"></span>${errorCount} error</span>`);
    stats.push(`<span class="summary-stat">${toolsUsed.length} tool${toolsUsed.length === 1 ? '' : 's'}</span>`);

    return `
      <details class="agent-process">
        <summary class="process-header">
          <span>âš¡</span>
          <span class="process-title">Research Trace</span>
          <span class="process-state ${stateClass}">${stateText}</span>
          <span class="process-chevron">â–¼</span>
        </summary>
        <div class="process-steps">${steps.join('')}</div>
        <div class="process-summary">${stats.join('')}</div>
      </details>`;
  }

  function addAIMsg(html, traceHtml = '') {
    addHTML(`
      <div class="msg ai">
        <div class="msg-avatar"><span class="material-icons">auto_awesome</span></div>
        <div class="msg-body">
          <div class="msg-sender">TaarYa</div>
          ${traceHtml}
          <div class="msg-bubble">${html}</div>
        </div>
      </div>`);
  }

  function renderMessage(role, content, toolTrace = null) {
    if (role === 'user') {
      addUserMsg(content);
      return;
    }
    const traceHtml = toolTrace ? buildTraceAccordion(toolTrace) : '';
    addAIMsg(formatAnswer(content), traceHtml);
  }

  async function askWithSession(query, chatHistoryForRequest = null) {
    const response = await fetch('/api/agent/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        chat_history: chatHistoryForRequest,
        session_id: activeSessionId
      }),
    });
    if (!response.ok) throw new Error(`POST /api/agent/ask → ${response.status}`);
    return response.json();
  }

  async function askStreamWithSession(query, chatHistoryForRequest, onEvent) {
    const response = await fetch('/api/agent/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        chat_history: chatHistoryForRequest,
        session_id: activeSessionId
      }),
    });
    if (!response.ok) throw new Error(`POST /api/agent/ask/stream → ${response.status}`);

    const reader = response.body.getReader();
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
          onEvent(JSON.parse(dataLines.join('\n')));
        } catch (error) {
          // Ignore malformed SSE chunks.
        }
      }
    }
  }

  async function initSessions() {
    const res = await fetch('/api/sessions');
    const sessions = await res.json();
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    for (const s of sessions) {
      const item = document.createElement('div');
      item.className = 'session-item' + (s.id === activeSessionId ? ' active' : '');
      item.dataset.id = s.id;
      const ago = timeAgo(new Date(s.updated_at));
      item.innerHTML = `
            <span class="s-delete" data-id="${s.id}">✕</span>
            <div class="s-title">${escapeHtml(s.title || 'New conversation')}</div>
            <div class="s-time">${ago}</div>`;
      item.addEventListener('click', () => switchSession(s.id));
      item.querySelector('.s-delete').addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/sessions/${s.id}`, { method: 'DELETE' });
        if (activeSessionId === s.id) await newSession();
        else initSessions();
      });
      list.appendChild(item);
    }
  }

  async function newSession() {
    const res = await fetch('/api/sessions', { method: 'POST' });
    const data = await res.json();
    activeSessionId = data.session_id;
    chatHistory = [];
    document.getElementById('chat-messages').innerHTML = welcomeTemplate;
    await initSessions();
  }

  async function switchSession(id) {
    activeSessionId = id;
    const res = await fetch(`/api/sessions/${id}/messages`);
    const messages = await res.json();
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    chatHistory = [];

    if (!messages.length) {
      container.innerHTML = welcomeTemplate;
    } else {
      for (const m of messages) {
        if (m.role === 'user') {
          addUserMsg(m.content);
        } else {
          const traceHtml = m.tool_trace ? buildTraceAccordion(m.tool_trace) : '';
          addAIMsg(formatAnswer(m.content), traceHtml);
        }
        chatHistory.push({ role: m.role, content: m.content });
      }
    }

    await initSessions();
  }

  function timeAgo(date) {
    const diff = Math.floor((Date.now() - date) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function buildStarsTable(toolOutput, step) {
    const stars = toolOutput.data || [];
    const duplicates = detectDuplicateMeasurements(stars);
    const header = step && step.params && typeof step.params === 'object' && Number.isFinite(Number(step.params.ra)) && Number.isFinite(Number(step.params.dec))
      ? `Gaia Sources · RA ${Number(step.params.ra).toFixed(2)}°, Dec ${Number(step.params.dec).toFixed(2)}°`
      : 'Gaia Sources';

    let rows = stars.slice(0, 8).map((star) => `
      <tr>
        <td class="source-cell">${escapeHtml(shortSourceId(star.source_id || star.id || '—'))}</td>
        <td>${Number(star.ra || 0).toFixed(3)}</td>
        <td>${Number(star.dec || 0).toFixed(3)}</td>
        <td class="highlight-cell">${escapeHtml(distancePc(star))}</td>
        <td>${Number((star.phot_g_mean_mag ?? star.gmag) || 0).toFixed(2)}</td>
      </tr>`).join('');

    if (duplicates > 0) {
      rows += `<tr class="warning-row"><td colspan="5">Possible duplicate measurements detected in ${duplicates} row${duplicates === 1 ? '' : 's'}.</td></tr>`;
    } else if (stars.length > 8) {
      rows += `<tr class="warning-row"><td colspan="5">${stars.length - 8} more rows available.</td></tr>`;
    }

    return `
      <div class="data-table-wrap">
        <div class="data-table-header">
          <span>${escapeHtml(header)}</span>
          <span class="data-count">${stars.length} star${stars.length === 1 ? '' : 's'}</span>
        </div>
        <table class="answer-table">
          <thead>
            <tr>
              <th>Source ID</th>
              <th>RA</th>
              <th>Dec</th>
              <th>Dist (pc)</th>
              <th>G mag</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function buildPapersTable(toolOutput) {
    const papers = toolOutput.data || [];
    const rows = papers.slice(0, 6).map((paper) => `
      <tr>
        <td class="source-cell">${escapeHtml((paper.arxiv_id || '—'))}</td>
        <td>${escapeHtml(paper.title || paper.name || 'Untitled')}</td>
        <td>${escapeHtml(paper.published_date || paper.category || '—')}</td>
      </tr>`).join('');

    return `
      <div class="data-table-wrap">
        <div class="data-table-header">
          <span>Literature Results</span>
          <span class="data-count">${papers.length} paper${papers.length === 1 ? '' : 's'}</span>
        </div>
        <table class="answer-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function buildActionChips(toolOutput, step) {
    const chips = [];
    if (toolOutput.tool === 'cone_search' && step && step.params) {
      const ra = Number(step.params.ra);
      const dec = Number(step.params.dec);
      const radius = Number(step.params.radius_deg || 0.5);
      chips.push({ icon: '📡', label: 'Expand search radius', query: `Search again near RA=${ra}, Dec=${dec} with radius ${Math.max(radius * 2, 1).toFixed(1)} degrees` });
      chips.push({ icon: '📄', label: 'Find related papers', query: `Find papers about stars near RA=${ra}, Dec=${dec}` });
      chips.push({ icon: '🔍', label: 'Investigate duplicates', query: `Check whether the current star results near RA=${ra}, Dec=${dec} contain duplicate measurements` });
    } else if (toolOutput.tool === 'semantic_search') {
      chips.push({ icon: '🛰', label: 'Search catalog instead', query: 'Search the spatial catalog for interesting nearby stars instead' });
    }
    if (!chips.length) return '';
    return `<div class="action-chips">${chips.map(chip => `<button class="chip-btn" data-query="${escapeHtml(chip.query)}"><span>${chip.icon}</span>${escapeHtml(chip.label)}</button>`).join('')}</div>`;
  }

  function addAnswerCard(answer, toolOutputs, streamState) {
    const firstDataOutput = (toolOutputs || []).find(to => Array.isArray(to.data) && to.data.length);
    const lastStep = streamState.steps && streamState.steps.length ? streamState.steps[streamState.steps.length - 1] : null;

    if (!firstDataOutput && streamState.steps.length && streamState.steps.every(step => step.state === 'empty' || step.state === 'error')) {
      addHTML(`
        <div class="msg ai">
          <div class="msg-avatar"><span class="material-icons">auto_awesome</span></div>
          <div class="msg-body">
            <div class="msg-sender">TaarYa</div>
            <div class="error-card">
              <div class="error-icon">○</div>
              <div><strong>No grounded results found.</strong><br>${formatAnswer(answer)}</div>
            </div>
          </div>
        </div>`);
      return;
    }

    let dataSection = '';
    let chips = '';
    if (firstDataOutput) {
      const matchingStep = (streamState.steps || []).find(step => step.tool === firstDataOutput.tool) || lastStep;
      dataSection = firstDataOutput.tool === 'semantic_search' || firstDataOutput.tool === 'graph_query'
        ? buildPapersTable(firstDataOutput)
        : buildStarsTable(firstDataOutput, matchingStep);
      chips = buildActionChips(firstDataOutput, matchingStep);
    }

    addHTML(`
      <div class="msg ai">
        <div class="msg-avatar"><span class="material-icons">auto_awesome</span></div>
        <div class="msg-body">
          <div class="msg-sender">TaarYa</div>
          <div class="answer-card">
            <div class="answer-header">
              <div class="answer-tag">${firstDataOutput ? 'DISCOVERY' : 'RESPONSE'}</div>
            </div>
            <div class="answer-body">${formatAnswer(answer)}</div>
            ${dataSection}
            ${chips}
          </div>
        </div>
      </div>`);
  }

  // ─── Send Logic (SSE Stream) ───────────────────────────
  async function send(overrideQuery) {
    if (sending) return;
    const query = overrideQuery || inputEl.value.trim();
    if (!query) return;
    if (!activeSessionId) await newSession();

    inputEl.value = '';
    sending = true;
    sendBtn.disabled = true;
    queryCount++;
    countEl.textContent = `${queryCount} ${queryCount === 1 ? 'query' : 'queries'}`;

    // User bubble
    addUserMsg(query);
    chatHistory.push({ role: 'user', content: query });

    // Start thinking panel
    const thinkingId = 'think-' + Date.now();
    addThinking(thinkingId);

    const streamState = { toolCount: 0, timelineCount: 0, traceCount: 0, steps: [], startedAt: Date.now() };
    let answered = false;

    try {
      await askStreamWithSession(
        query,
        chatHistory.length > 2 ? chatHistory.slice(-10) : null,
        (event) => {
          if (event.type === 'tool_start') streamState.toolCount++;

          if (event.type === 'token') {
            return;
          }

          if (event.type === 'answer') {
            const answer = event.data.answer || 'No response received.';

            if (!answered) {
              answered = true;
              finishThinkingCompact(thinkingId, streamState);
              addAnswerCard(answer, event.data.tool_outputs || [], streamState);
            }

            const lastMessage = chatHistory[chatHistory.length - 1];
            if (!lastMessage || lastMessage.role !== 'assistant' || lastMessage.content !== answer) {
              chatHistory.push({ role: 'assistant', content: answer });
            }
          }

          else if (event.type === 'done') {
            // ensure thinking is finalized
            if (!answered) finishThinkingCompact(thinkingId, streamState);
          }

          else if (event.type !== 'answer') {
            // thinking, decision, tool_start, tool_end, error
            handleEvent(thinkingId, event, streamState);
          }
        }
      );
      await initSessions();
    } catch (err) {
      // Fallback to non-streaming API
      const thinkEl = document.getElementById(thinkingId);
      if (thinkEl) thinkEl.remove();

      try {
        const resp = await askWithSession(query, chatHistory.length > 2 ? chatHistory.slice(-10) : null);
        const answer = resp.answer || resp.response || 'No response.';
        addAIMsg(formatAnswer(answer));
        chatHistory.push({ role: 'assistant', content: answer });
        await initSessions();
      } catch (fallbackErr) {
        addAIMsg(`<span style="color:var(--error);">⚠ Failed:</span> ${escapeHtml(fallbackErr.message)}`);
      }
    }

    sending = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }

  // ─── Event Listeners ──────────────────────────────────
  sendBtn.addEventListener('click', () => send());
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  // Suggestion chips
  document.querySelectorAll('.welcome-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-query');
      if (q) send(q);
    });
  });

  messagesEl.addEventListener('click', (event) => {
    const welcomeChip = event.target.closest('.welcome-chip[data-query]');
    if (welcomeChip) {
      const welcomeQuery = welcomeChip.getAttribute('data-query');
      if (welcomeQuery) send(welcomeQuery);
      return;
    }

    const chip = event.target.closest('.chip-btn[data-query]');
    if (!chip) return;
    const q = chip.getAttribute('data-query');
    if (q) send(q);
  });

  document.addEventListener('sidebar-ready', async () => {
    document.getElementById('new-chat-btn').addEventListener('click', newSession);

    const sessions = await fetch('/api/sessions').then(r => r.json());
    if (sessions.length > 0) {
      await switchSession(sessions[0].id);
    } else {
      await newSession();
    }
    inputEl.focus();
  });
})();
