(function () {
  const status = document.getElementById('system-status');
  if (!status) return;

  const label = status.querySelector('span');
  fetch('/ready')
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok && !data.backends) throw new Error(`Readiness check returned ${response.status}`);
      return { response, data };
    })
    .then(({ response, data }) => {
      const ready = response.ok && data.ready === true;
      status.dataset.state = ready ? 'ready' : 'degraded';
      label.textContent = ready ? 'Services ready' : 'Services degraded';
      status.title = Object.entries(data.backends || {})
        .map(([name, backend]) => `${name}: ${backend.status || 'unknown'}`)
        .join(', ');
    })
    .catch(() => {
      status.dataset.state = 'error';
      label.textContent = 'Status unavailable';
      status.title = 'Could not read service readiness';
    });
})();
