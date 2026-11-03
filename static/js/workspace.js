(function () {
  'use strict';

  const number = (value) => Number(value || 0).toLocaleString();
  let selectedRegion = null;

  async function loadCoverage() {
    const state = document.getElementById('coverage-state');
    const summary = document.getElementById('coverage-summary');
    try {
      const [statsResponse, regionsResponse] = await Promise.all([
        fetch('/api/stats'), fetch('/api/regions'),
      ]);
      if (!statsResponse.ok || !regionsResponse.ok) throw new Error('Coverage data unavailable');
      const stats = await statsResponse.json();
      const { regions = [] } = await regionsResponse.json();
      const pg = stats.postgresql || {};
      const qdrant = stats.qdrant || {};
      const stars = Number(pg.total_stars || 0);
      const papers = Number(qdrant.points_count || qdrant.vectors_count || 0);
      const populated = regions.filter((region) => Number(region.count || 0) > 0).length;
      document.getElementById('coverage-stars').textContent = number(stars);
      document.getElementById('coverage-papers').textContent = number(papers);
      document.getElementById('coverage-regions').textContent = number(regions.length);
      state.textContent = stars || papers ? 'Indexed' : 'No records';
      summary.textContent = `${populated} of ${regions.length} regions contain indexed stars`;
    } catch (error) {
      state.textContent = 'Unavailable';
      summary.textContent = 'Could not read catalog coverage';
      console.error('[Workspace] Coverage failed:', error);
    }
  }

  async function saveItem(itemType, title, payload) {
    const projectId = localStorage.getItem('taarya.activeProjectId');
    if (!projectId) throw new Error('Create or select a project first');
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_type: itemType, title, payload }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `Could not save item (${response.status})`);
    window.TaarYaProjectsRefresh?.();
  }

  document.addEventListener('click', async (event) => {
    const chip = event.target.closest('.obs-loc-chip');
    if (chip) {
      selectedRegion = {
        name: chip.textContent.trim(),
        ra: Number(chip.dataset.ra), dec: Number(chip.dataset.dec), fov: Number(chip.dataset.fov),
      };
    }
    if (!event.target.closest('#save-current-region')) return;
    if (!selectedRegion) {
      document.getElementById('coverage-summary').textContent = 'Choose a named region first';
      return;
    }
    try {
      await saveItem('search', selectedRegion.name, selectedRegion);
      document.getElementById('coverage-summary').textContent = `${selectedRegion.name} saved to this project`;
    } catch (error) {
      document.getElementById('coverage-summary').textContent = error.message;
    }
  });

  window.addEventListener('taarya:sky-source-selected', async (event) => {
    const source = event.detail;
    if (!source?.source_id) return;
    try {
      await saveItem('star', source.source_id, source);
      document.getElementById('coverage-summary').textContent = `${source.source_id} pinned to this project`;
    } catch (error) {
      document.getElementById('coverage-summary').textContent = error.message;
    }
  });

  window.addEventListener('taarya:pin-results', async (event) => {
    const { itemType, items = [] } = event.detail || {};
    try {
      const saved = await Promise.all(items.slice(0, 8).map((item) => {
        const title = itemType === 'paper'
          ? `${item.arxiv_id || ''} ${item.title || 'Untitled paper'}`.trim()
          : String(item.source_id || item.id || 'Star');
        return saveItem(itemType, title, item);
      }));
      document.getElementById('coverage-summary').textContent = `${saved.length} result${saved.length === 1 ? '' : 's'} pinned to this project`;
    } catch (error) {
      document.getElementById('coverage-summary').textContent = error.message;
    }
  });

  loadCoverage();
})();
