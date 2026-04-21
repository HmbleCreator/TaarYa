/**
 * TaarYa Aladin Sky Panel — Reusable Aladin Lite v3 controller.
 *
 * Usage (MUST be called inside A.init.then):
 *   A.init.then(() => {
 *     TaarYaAladin.init('aladin-container', { fov: 2, survey: 'P/DSS2/color' });
 *   });
 *   TaarYaAladin.goto(66.75, 15.96, 2.0);
 *   TaarYaAladin.addMarkers(starsArray);
 */
window.TaarYaAladin = (function () {
  'use strict';

  let aladin = null;
  let catalog = null;
  let searchOverlay = null;
  let _ready = false;
  let _onReadyQueue = [];

  /* ── Color by discovery score ────────────────────────── */
  function scoreColor(score) {
    if (score >= 15) return '#f87171';   // red — high anomaly
    if (score >= 10) return '#fbbf24';   // amber
    if (score >= 5)  return '#a3e635';   // green
    return '#60a5fa';                     // blue — normal
  }

  /* ── Init ─────────────────────────────────────────────── */
  function init(containerId, opts) {
    var container = document.getElementById(containerId);
    if (!container) {
      console.error('[TaarYaAladin] Container #' + containerId + ' not found');
      return;
    }

    // Ensure container has dimensions
    if (container.offsetHeight < 10) {
      container.style.height = '400px';
    }
    if (container.offsetWidth < 10) {
      container.style.width = '100%';
    }

    opts = opts || {};
    var fov    = opts.fov    || 60;
    var ra     = opts.ra     || 0;
    var dec    = opts.dec    || 0;
    var survey = opts.survey || 'P/DSS2/color';

    try {
      aladin = A.aladin('#' + containerId, {
        fov: fov,
        target: ra + ' ' + dec,
        survey: survey,
        showReticle: true,
        showZoomControl: false,
        showLayersControl: false,
        showGotoControl: false,
        showShareControl: false,
        showSimbadPointerControl: false,
        showCooGrid: false,
        showFrame: false,
        fullScreen: false,
        cooFrame: 'J2000',
      });
    } catch (err) {
      console.error('[TaarYaAladin] Failed to create Aladin instance:', err);
      return;
    }

    // Discovery catalog layer
    try {
      catalog = A.catalog({
        name: 'TaarYa Discoveries',
        shape: 'circle',
        sourceSize: 14,
        color: '#a3e635',
        onClick: 'showPopup',
      });
      aladin.addCatalog(catalog);

      // Search cone overlay
      searchOverlay = A.graphicOverlay({
        name: 'Search Cone',
        color: 'rgba(255,255,255,0.25)',
        lineWidth: 1.5,
      });
      aladin.addOverlay(searchOverlay);
    } catch (err) {
      console.warn('[TaarYaAladin] Could not add catalog/overlay:', err);
    }

    // Coordinate readout
    if (opts.coordReadout) {
      var readoutEl = document.getElementById(opts.coordReadout);
      if (readoutEl) {
        aladin.on('mouseMove', function (e) {
          if (e.ra !== undefined && e.dec !== undefined) {
            readoutEl.textContent = 'RA ' + e.ra.toFixed(4) + '°  Dec ' + e.dec.toFixed(4) + '°';
          }
        });
      }
    }

    // Click handler — show star info
    aladin.on('objectClicked', function (object) {
      if (!object || !object.data) return;
      var d = object.data;
      var popup =
        '<div style="font-family:Inter,sans-serif;font-size:12px;max-width:220px;">' +
        '<div style="font-weight:700;margin-bottom:4px;">' + (d.name || d.source_id || 'Star') + '</div>' +
        '<div style="color:#aaa;">RA ' + Number(d.ra).toFixed(4) + '° &nbsp; Dec ' + Number(d.dec).toFixed(4) + '°</div>';
      if (d.discovery_score != null) {
        popup += '<div style="margin-top:4px;">Score: <strong style="color:' + scoreColor(d.discovery_score) + ';">' + Number(d.discovery_score).toFixed(1) + '</strong></div>';
      }
      if (d.phot_g_mean_mag != null) {
        popup += '<div>G mag: ' + Number(d.phot_g_mean_mag).toFixed(2) + '</div>';
      }
      popup += '</div>';
      aladin.showPopup(object.ra, object.dec, popup);
    });

    _ready = true;
    _onReadyQueue.forEach(function (fn) { fn(); });
    _onReadyQueue = [];
    console.log('[TaarYaAladin] Initialized on #' + containerId);
  }

  function _whenReady(fn) {
    if (_ready) fn();
    else _onReadyQueue.push(fn);
  }

  /* ── Navigate ────────────────────────────────────────── */
  function goto(ra, dec, fov) {
    _whenReady(function () {
      if (ra != null && dec != null) aladin.gotoRaDec(ra, dec);
      if (fov) aladin.setFov(fov);
    });
  }

  /* ── Markers ─────────────────────────────────────────── */
  function addMarkers(stars) {
    _whenReady(function () {
      if (!catalog) return;
      catalog.removeAll();

      stars.forEach(function (star) {
        var ra  = Number(star.ra);
        var dec = Number(star.dec);
        if (isNaN(ra) || isNaN(dec)) return;

        var score = Number(star.discovery_score || star.score || 0);
        var source = A.source(ra, dec, {
          name: star.source_id || '',
          source_id: star.source_id || '',
          ra: ra,
          dec: dec,
          discovery_score: score,
          phot_g_mean_mag: star.phot_g_mean_mag || star.gmag || null,
          parallax: star.parallax || null,
        });
        catalog.addSources([source]);
      });
    });
  }

  function clearMarkers() {
    _whenReady(function () {
      if (catalog) catalog.removeAll();
      if (searchOverlay) searchOverlay.removeAll();
    });
  }

  /* ── Search Cone ─────────────────────────────────────── */
  function drawSearchCone(ra, dec, radiusDeg) {
    _whenReady(function () {
      if (!searchOverlay) return;
      searchOverlay.removeAll();
      searchOverlay.add(A.circle(ra, dec, radiusDeg, {
        color: 'rgba(163,230,53,0.3)',
        lineWidth: 1.5,
      }));
    });
  }

  /* ── Survey ──────────────────────────────────────────── */
  function setSurvey(surveyId) {
    _whenReady(function () {
      aladin.setImageSurvey(surveyId);
    });
  }

  /* ── Highlight ───────────────────────────────────────── */
  function highlightStar(ra, dec) {
    _whenReady(function () {
      aladin.gotoRaDec(ra, dec);
      aladin.setFov(0.1);
    });
  }

  /* ── Handle SSE sky_command event ─────────────────────── */
  function handleSkyCommand(data) {
    if (!data) return;
    switch (data.action) {
      case 'goto':
        goto(data.ra, data.dec, data.fov);
        break;
      case 'markers':
        addMarkers(data.stars || []);
        break;
      case 'cone':
        drawSearchCone(data.ra, data.dec, data.radius);
        break;
      case 'survey':
        setSurvey(data.survey);
        break;
      case 'highlight':
        highlightStar(data.ra, data.dec);
        break;
      case 'clear':
        clearMarkers();
        break;
    }
  }

  /* ── Public API ───────────────────────────────────────── */
  return {
    init: init,
    goto: goto,
    addMarkers: addMarkers,
    clearMarkers: clearMarkers,
    drawSearchCone: drawSearchCone,
    setSurvey: setSurvey,
    highlightStar: highlightStar,
    handleSkyCommand: handleSkyCommand,
    isReady: function () { return _ready; },
  };
})();
