(function () {
  const form = document.getElementById('tess-form');
  const state = document.getElementById('tess-state');
  const stateMessage = document.getElementById('tess-state-message');
  const stateHelp = document.getElementById('tess-state-help');
  const results = document.getElementById('tess-results');
  const submit = document.getElementById('tess-submit');
  const canvas = document.getElementById('tess-phase-plot');
  let plotData = [];

  function setState(message, kind) {
    state.hidden = false;
    state.dataset.state = kind || 'empty';
    stateMessage.textContent = message;
    stateHelp.hidden = state.dataset.state !== 'empty';
    results.hidden = true;
  }

  function appendMetric(parent, label, value) {
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value;
    parent.append(term, description);
  }

  function fixed(value, digits) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : 'Not reported';
  }

  function drawPlot() {
    if (!canvas || !plotData.length || canvas.clientWidth === 0) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = 280;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext('2d');
    context.scale(ratio, ratio);
    const style = getComputedStyle(document.documentElement);
    const text = style.getPropertyValue('--text-tertiary').trim() || '#a0a0a0';
    const accent = style.getPropertyValue('--accent').trim() || '#d4ad77';
    const border = style.getPropertyValue('--border').trim() || '#343434';
    const left = 48, right = width - 14, top = 14, bottom = height - 30;
    const values = plotData.map((point) => point.relative_flux).filter(Number.isFinite);
    if (!values.length) return;
    const center = values.reduce((sum, value) => sum + value, 0) / values.length;
    const spread = Math.max(0.003, Math.max(...values.map((value) => Math.abs(value - center))) * 1.08);
    context.font = '11px system-ui';
    context.strokeStyle = border;
    context.fillStyle = text;
    context.lineWidth = 1;
    for (let tick = -1; tick <= 1; tick += 1) {
      const y = top + (1 - (tick + 1) / 2) * (bottom - top);
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(right, y);
      context.stroke();
      context.fillText((center + tick * spread).toFixed(3), 2, y + 4);
    }
    context.fillText('-0.5', left - 9, height - 8);
    context.fillText('0', (left + right) / 2 - 3, height - 8);
    context.fillText('0.5 phase', right - 48, height - 8);
    context.fillStyle = accent;
    for (const point of plotData) {
      const x = left + ((point.phase + 0.5) % 1) * (right - left);
      const y = top + (1 - (point.relative_flux - (center - spread)) / (2 * spread)) * (bottom - top);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      context.beginPath();
      context.arc(x, y, 1.5, 0, Math.PI * 2);
      context.fill();
    }
  }

  function render(result) {
    const analysis = result.analysis;
    document.getElementById('tess-target').textContent = `TIC ${result.target.tic_id}`;
    document.getElementById('tess-status').textContent = 'Unvalidated candidate signal';
    const metrics = document.getElementById('tess-metrics');
    metrics.replaceChildren();
    appendMetric(metrics, 'Period', `${fixed(analysis.period_days, 5)} d`);
    appendMetric(metrics, 'Epoch (BTJD)', fixed(analysis.epoch_btjd, 5));
    appendMetric(metrics, 'Duration', `${fixed(analysis.duration_hours, 2)} h`);
    appendMetric(metrics, 'Depth', `${fixed(analysis.depth_fraction * 100, 3)}%`);
    appendMetric(metrics, 'BLS power', fixed(analysis.bls_power, 5));
    appendMetric(metrics, 'Sectors', analysis.sectors.join(', '));
    appendMetric(metrics, 'Baseline', `${fixed(analysis.baseline_days, 1)} d`);
    appendMetric(metrics, 'Screened samples', String(analysis.analysis_points));

    const rows = document.getElementById('tess-product-rows');
    rows.replaceChildren();
    for (const product of result.products) {
      const row = document.createElement('tr');
      for (const value of [product.sector, product.provenance_name, product.filename, product.data_uri, product.flux_column,
        product.quality_rule, JSON.stringify(product.fits_metadata), product.sha256]) {
        const cell = document.createElement('td');
        cell.textContent = String(value);
        row.appendChild(cell);
      }
      rows.appendChild(row);
    }
    document.getElementById('tess-interpretation').textContent = result.interpretation;
    plotData = result.lightcurve_preview;
    state.hidden = true;
    results.hidden = false;
    drawPlot();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const tic = document.getElementById('tic-id').value.trim();
    const sectorText = document.getElementById('tess-sectors').value.trim();
    let sectors;
    if (sectorText) {
      const parts = sectorText.split(',').map((item) => item.trim());
      if (parts.length > 5 || parts.some((item) => !/^\d{1,3}$/.test(item))) {
        setState('Enter at most five sector numbers separated by commas.', 'error');
        return;
      }
      sectors = parts.map(Number);
      if (sectors.some((value) => value < 1 || value > 999) || new Set(sectors).size !== sectors.length) {
        setState('Sector numbers must be distinct integers from 1 to 999.', 'error');
        return;
      }
    }

    submit.disabled = true;
    setState('Querying MAST and screening the returned light curves…', 'loading');
    try {
      const response = await fetch('/api/tess/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tic_id: tic, sectors }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status}).`);
      render(data);
    } catch (error) {
      setState(error.message || 'TESS analysis failed.', 'error');
    } finally {
      submit.disabled = false;
    }
  });

  window.addEventListener('resize', drawPlot);
  window.addEventListener('storage', drawPlot);
})();
