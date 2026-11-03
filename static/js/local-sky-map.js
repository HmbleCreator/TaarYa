(function () {
  'use strict';

  const container = document.getElementById('chat-aladin-container');
  const status = document.getElementById('sky-map-status');
  const readout = document.getElementById('chat-sky-coords');
  if (!container || !status || !readout) return;

  const canvas = document.createElement('canvas');
  canvas.className = 'local-sky-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Interactive right ascension and declination star map');
  container.replaceChildren(canvas);

  const ctx = canvas.getContext('2d');
  const view = { ra: 83.82, dec: -5.39, fov: 8, stars: [], cone: null, selected: null };
  let width = 0;
  let height = 0;
  let dpr = 1;
  let request = null;
  let drag = null;
  let ignoreNextClick = false;

  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const wrapRa = (value) => ((value % 360) + 360) % 360;
  const radians = (value) => value * Math.PI / 180;
  const fmt = (value) => Number(value).toFixed(3);

  function updateReadout() {
    readout.textContent = `RA ${fmt(view.ra)}°  Dec ${fmt(view.dec)}°`;
  }

  function resize() {
    const rect = container.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function project(ra, dec) {
    let deltaRa = wrapRa(Number(ra) - view.ra);
    if (deltaRa > 180) deltaRa -= 360;
    const fieldWidth = view.fov * Math.max(width / Math.max(height, 1), 0.2);
    const x = width / 2 + (deltaRa * Math.cos(radians(view.dec)) / fieldWidth) * width;
    const y = height / 2 - ((Number(dec) - view.dec) / view.fov) * height;
    return [x, y];
  }

  function draw() {
    if (!width || !height) return;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#151b22';
    ctx.fillRect(0, 0, width, height);

    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(167, 187, 211, .08)';
    ctx.fillStyle = 'rgba(190, 204, 221, .6)';
    ctx.font = '11px Cascadia Mono, monospace';
    for (let i = -4; i <= 4; i += 2) {
      const x = width / 2 + (i / 4) * width / 2;
      const y = height / 2 + (i / 4) * height / 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      if (i < 4) {
        const ra = wrapRa(view.ra - (i / 4) * view.fov * Math.max(width / height, 0.2) / Math.max(Math.cos(radians(view.dec)), .15));
        const dec = clamp(view.dec + (i / 4) * view.fov, -90, 90);
        ctx.fillText(`${fmt(ra)}°`, x + 4, 14);
        if (i !== 0) ctx.fillText(`${fmt(dec)}°`, 5, y - 4);
      }
    }

    ctx.strokeStyle = 'rgba(109, 163, 230, .55)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(width / 2 - 8, height / 2); ctx.lineTo(width / 2 + 8, height / 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(width / 2, height / 2 - 8); ctx.lineTo(width / 2, height / 2 + 8); ctx.stroke();

    for (const star of view.stars) {
      const ra = Number(star.ra);
      const dec = Number(star.dec);
      if (!Number.isFinite(ra) || !Number.isFinite(dec)) continue;
      const [x, y] = project(ra, dec);
      if (x < -6 || x > width + 6 || y < -6 || y > height + 6) continue;
      const mag = Number(star.phot_g_mean_mag);
      const radius = Number.isFinite(mag) ? clamp(2.6 - (mag - 8) * .16, 1, 3.4) : 1.4;
      ctx.fillStyle = Number.isFinite(mag) && mag < 8 ? '#e5f4ff' : '#a6c8e9';
      ctx.globalAlpha = Number.isFinite(mag) ? clamp(1.05 - (mag - 6) * .035, .3, .95) : .55;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    }

    if (view.cone) {
      const [x, y] = project(view.cone.ra, view.cone.dec);
      const radius = Math.max(2, (view.cone.radius / view.fov) * height);
      ctx.strokeStyle = '#7eb4f0';
      ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
    }

    if (view.selected) {
      const [x, y] = project(view.selected.ra, view.selected.dec);
      ctx.strokeStyle = '#e8c77e';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.stroke();
    }
  }

  async function loadField() {
    if (request) request.abort();
    request = new AbortController();
    status.textContent = 'Loading catalog sources…';
    updateReadout();
    const radius = Math.min(10, Math.max(.03, view.fov / 2));
    const params = new URLSearchParams({
      ra: String(view.ra), dec: String(view.dec), radius: String(radius), limit: '1000',
    });
    try {
      const response = await fetch(`/api/stars/cone-search?${params}`, { signal: request.signal });
      if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
      const payload = await response.json();
      view.stars = Array.isArray(payload.stars) ? payload.stars : [];
      status.textContent = `${view.stars.length.toLocaleString()} sources · ${view.fov.toFixed(view.fov < 1 ? 2 : 1)}° field`;
      draw();
    } catch (error) {
      if (error.name === 'AbortError') return;
      view.stars = [];
      status.textContent = 'Catalog unavailable · showing sky coordinates';
      console.error('[SkyMap] Catalog load failed:', error);
      draw();
    }
  }

  function goto(ra, dec, fov) {
    if (Number.isFinite(Number(ra))) view.ra = wrapRa(Number(ra));
    if (Number.isFinite(Number(dec))) view.dec = clamp(Number(dec), -90, 90);
    if (Number.isFinite(Number(fov)) && Number(fov) > 0) view.fov = clamp(Number(fov), .03, 180);
    view.selected = null;
    loadField();
  }

  function addMarkers(stars) {
    if (!Array.isArray(stars)) return;
    view.stars = stars.filter((star) => Number.isFinite(Number(star.ra)) && Number.isFinite(Number(star.dec)));
    status.textContent = `${view.stars.length.toLocaleString()} search results`;
    draw();
  }

  canvas.addEventListener('pointerdown', (event) => {
    drag = { x: event.clientX, y: event.clientY, moved: false };
    ignoreNextClick = false;
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add('dragging');
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    view.ra = wrapRa(view.ra - (dx / Math.max(width, 1)) * view.fov * Math.max(width / height, .2) / Math.max(Math.cos(radians(view.dec)), .15));
    view.dec = clamp(view.dec + (dy / Math.max(height, 1)) * view.fov, -90, 90);
    drag.x = event.clientX;
    drag.y = event.clientY;
    updateReadout();
    draw();
  });
  function endDrag(event) {
    if (!drag) return;
    const moved = drag.moved;
    drag = null;
    canvas.classList.remove('dragging');
    if (event.pointerId !== undefined && canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (moved) {
      ignoreNextClick = true;
      loadField();
    }
  }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('click', (event) => {
    if (ignoreNextClick) { ignoreNextClick = false; return; }
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest = null;
    let nearestDistance = 14;
    for (const star of view.stars) {
      const [sx, sy] = project(star.ra, star.dec);
      const distance = Math.hypot(sx - x, sy - y);
      if (distance < nearestDistance) { nearest = star; nearestDistance = distance; }
    }
    if (!nearest) return;
    view.selected = nearest;
    draw();
    window.dispatchEvent(new CustomEvent('taarya:sky-source-selected', { detail: nearest }));
  });
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    view.fov = clamp(view.fov * (event.deltaY < 0 ? .8 : 1.25), .03, 180);
    loadField();
  }, { passive: false });

  document.querySelectorAll('.obs-loc-chip').forEach((button) => {
    button.addEventListener('click', () => goto(button.dataset.ra, button.dataset.dec, button.dataset.fov));
  });

  window.TaarYaAladin = {
    goto,
    addMarkers,
    clearMarkers: () => { view.stars = []; view.cone = null; draw(); },
    drawSearchCone: (ra, dec, radius) => { view.cone = { ra: Number(ra), dec: Number(dec), radius: Number(radius) }; draw(); },
    setSurvey: () => {},
    highlightStar: (ra, dec) => goto(ra, dec, .1),
    handleSkyCommand: (command) => {
      if (!command) return;
      if (command.action === 'goto') goto(command.ra, command.dec, command.fov);
      if (command.action === 'markers') addMarkers(command.stars || []);
      if (command.action === 'cone') { goto(command.ra, command.dec, Math.max(Number(command.radius) * 3, .5)); window.TaarYaAladin.drawSearchCone(command.ra, command.dec, command.radius); }
      if (command.action === 'clear') window.TaarYaAladin.clearMarkers();
      if (command.action === 'highlight') window.TaarYaAladin.highlightStar(command.ra, command.dec);
    },
  };
  window.TaarYaSkyPanel = { open: () => {}, close: () => {}, isOpen: () => true, pulse: () => {
    canvas.classList.remove('map-attention');
    void canvas.offsetWidth;
    canvas.classList.add('map-attention');
    window.setTimeout(() => canvas.classList.remove('map-attention'), 700);
  } };

  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize();

  /* ── Covered Regions picker ─────────────────────────────── */
  const crBtn   = document.getElementById('covered-regions-btn');
  const crPanel = document.getElementById('covered-regions-panel');
  const crList  = document.getElementById('covered-regions-list');

  function initCoveredRegions(regions) {
    if (!crBtn || !crPanel || !crList) return;

    if (!regions || !regions.length) {
      crList.innerHTML = '<li class="cr-empty">No indexed regions in database.</li>';
      return;
    }

    crList.innerHTML = '';
    regions.forEach((r, i) => {
      const name  = r.name || r.region_name || ('Region ' + (i + 1));
      const ra    = Number(r.ra  || r.center_ra  || 0);
      const dec   = Number(r.dec || r.center_dec || 0);
      const count = Number(r.count || r.star_count || 0);
      const fov   = Math.max(Number(r.radius || 2) * 2.5, 4);

      const li = document.createElement('li');
      li.className = 'cr-item';
      li.innerHTML =
        '<span class="cr-dot"></span>' +
        '<div style="flex:1;min-width:0;">' +
          '<div class="cr-name">' + name + '</div>' +
          '<div class="cr-coords">' + (count > 0 ? count.toLocaleString() + ' stars · ' : '') + 'RA ' + ra.toFixed(2) + '° Dec ' + dec.toFixed(2) + '°</div>' +
        '</div>';

      li.addEventListener('click', (e) => {
        e.stopPropagation();
        goto(ra, dec, fov);
        crPanel.hidden = true;
      });
      crList.appendChild(li);
    });

    crBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      crPanel.hidden = !crPanel.hidden;
    });

    document.addEventListener('click', (e) => {
      if (!crPanel.contains(e.target) && e.target !== crBtn) {
        crPanel.hidden = true;
      }
    });

    crPanel.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }

  fetch('/api/regions')
    .then((response) => { if (!response.ok) throw new Error(`Regions unavailable (${response.status})`); return response.json(); })
    .then(({ regions = [] }) => {
      initCoveredRegions(regions);
      const populated = regions.filter((region) => Number(region.count) > 0);
      const initial = populated.find((region) => /orion|hyades|pleiades/i.test(region.name)) || populated[0];
      if (initial) goto(initial.ra, initial.dec, clamp(Number(initial.radius) * 2, 1, 24));
      else loadField();
    })
    .catch((error) => {
      console.error('[SkyMap] Could not choose initial field:', error);
      loadField();
    });
})();
