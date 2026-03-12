(function () {
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function timeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    const intervals = [
      { label: 'y', seconds: 31536000 },
      { label: 'mo', seconds: 2592000 },
      { label: 'd', seconds: 86400 },
      { label: 'h', seconds: 3600 },
      { label: 'm', seconds: 60 },
    ];
    for (const i of intervals) {
      const interval = Math.floor(seconds / i.seconds);
      if (interval >= 1) return interval + i.label;
    }
    return 'now';
  }

  async function loadSessions() {
    const list = document.getElementById('session-list');
    if (!list) return;
    try {
      const res = await fetch('/api/sessions');
      const sessions = await res.json();
      list.innerHTML = '';
      for (const s of sessions) {
        const item = document.createElement('div');
        item.className = 'session-item';
        const ago = timeAgo(new Date(s.updated_at));
        item.innerHTML = `
          <span class="s-delete" data-id="${s.id}">✕</span>
          <div class="s-title">${escapeHtml(s.title || 'New conversation')}</div>
          <div class="s-time">${ago}</div>`;
        item.addEventListener('click', () => {
          window.location.href = '/static/chat.html?session=' + s.id;
        });
        item.querySelector('.s-delete').addEventListener('click', async (e) => {
          e.stopPropagation();
          await fetch(`/api/sessions/${s.id}`, { method: 'DELETE' });
          loadSessions();
        });
        list.appendChild(item);
      }
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  }

  fetch('/static/partials/sidebar.html')
    .then(r => r.text())
    .then(html => {
      const mount = document.getElementById('sidebar-mount');
      if (!mount) return;
      mount.innerHTML = html;
      // Mark the active nav link based on current page
      document.querySelectorAll('.sidebar-nav a').forEach(a => {
        const href = a.getAttribute('href');
        a.classList.toggle('active', window.location.pathname.endsWith(href.replace('/static', '')));
      });
      // Load sessions for all pages
      loadSessions();
      // Re-dispatch a custom event so chat.js knows the sidebar is ready
      document.dispatchEvent(new Event('sidebar-ready'));
    });
})();
