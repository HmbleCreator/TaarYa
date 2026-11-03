(function () {
  'use strict';

  const logEl = document.getElementById('log-console');

  function log(msg, type) {
    const span = document.createElement('span');
    if (type) span.className = 'log-' + type;
    span.style.display = 'block';
    span.textContent = new Date().toLocaleTimeString('en', { hour12: false }) + '  ' + msg;
    logEl.appendChild(span);
    logEl.scrollTop = logEl.scrollHeight;
    while (logEl.childElementCount > 200) logEl.removeChild(logEl.firstChild);
  }

  function healthDot(ok) {
    var color = ok ? 'var(--success)' : 'var(--error)';
    var shadow = ok ? ';box-shadow:0 0 4px var(--success)' : '';
    return '<span class="s-health-dot" style="background:' + color + shadow + '"></span>';
  }

  function healthFmt(n) {
    return n != null ? Number(n).toLocaleString() : '\u2014';
  }

  function renderHealth(data) {
    var pg    = data.postgresql || {};
    var qd    = data.qdrant     || {};
    var neo   = data.neo4j      || {};
    var pgOk  = pg.status  === 'connected';
    var qdOk  = qd.status  === 'connected' || qd.points_count != null;
    var neoOk = neo.status === 'connected';
    document.getElementById('health-grid').innerHTML =
      '<div class="s-health-cell">' +
        '<div class="s-health-name">' + healthDot(pgOk) + ' PostgreSQL</div>' +
        '<div class="s-health-val">' + healthFmt(pg.total_stars) + '</div>' +
        '<div class="s-health-unit">Stars</div>' +
      '</div>' +
      '<div class="s-health-cell">' +
        '<div class="s-health-name">' + healthDot(qdOk) + ' Qdrant</div>' +
        '<div class="s-health-val">' + healthFmt(qd.points_count || qd.vectors_count || 0) + '</div>' +
        '<div class="s-health-unit">Vectors</div>' +
      '</div>' +
      '<div class="s-health-cell">' +
        '<div class="s-health-name">' + healthDot(neoOk) + ' Neo4j</div>' +
        '<div class="s-health-val">' + healthFmt((neo.stars || 0) + (neo.papers || 0) + (neo.clusters || 0)) + '</div>' +
        '<div class="s-health-unit">Graph nodes</div>' +
      '</div>' +
      '<div class="s-health-cell">' +
        '<div class="s-health-name"><span class="s-health-dot" style="background:var(--accent);"></span>Relationships</div>' +
        '<div class="s-health-val">' + healthFmt(neo.relationships || 0) + '</div>' +
        '<div class="s-health-unit">Edges</div>' +
      '</div>';
  }

  function loadHealth() {
    TaarYa.api.stats().then(renderHealth).catch(function (e) {
      log('Health check failed: ' + e.message, 'error');
    });
  }
  loadHealth();

  function triggerIngestion(pipeline) {
    var btn  = document.getElementById(pipeline + '-btn');
    var pill = document.getElementById(pipeline + '-status-pill');
    var txt  = document.getElementById(pipeline + '-status-text');
    btn.disabled = true;
    setPill(pill, txt, 'running', 'Running');
    log('Starting ' + pipeline + ' ingestion\u2026');

    fetch('/api/ingest/' + pipeline, { method: 'POST' })
      .then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new Error(data.detail || String(res.status));
          log(pipeline + ': ' + (data.message || 'started'));
          pollStatus(pipeline, pill, txt, btn);
        });
      })
      .catch(function (e) {
        log(pipeline + ' failed: ' + e.message, 'error');
        setPill(pill, txt, 'error', 'Error');
        btn.disabled = false;
      });
  }

  function setPill(pill, txt, state, label) {
    pill.className = 's-pill s-pill-' + state;
    txt.textContent = label;
  }

  function pollStatus(pipeline, pill, txt, btn) {
    var iv = setInterval(function () {
      fetch('/api/ingest/status')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var running = data[pipeline + '_running'] !== undefined
            ? data[pipeline + '_running']
            : data[pipeline];
          if (running === false || running === 'idle') {
            clearInterval(iv);
            setPill(pill, txt, 'idle', 'Idle');
            btn.disabled = false;
            log(pipeline + ' finished.');
            loadHealth();
          }
        })
        .catch(function () {
          clearInterval(iv);
          setPill(pill, txt, 'idle', 'Idle');
          btn.disabled = false;
        });
    }, 3000);
  }

  window.triggerIngestion = triggerIngestion;
})();

