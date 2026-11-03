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

  let projects = [];
  let activeProjectId = localStorage.getItem('taarya.activeProjectId');

  function selectProject(projectId) {
    activeProjectId = projectId;
    if (projectId) localStorage.setItem('taarya.activeProjectId', projectId);
    else localStorage.removeItem('taarya.activeProjectId');
    document.querySelectorAll('.project-row').forEach((row) => {
      row.setAttribute('aria-current', String(row.dataset.projectId === projectId));
    });
    window.dispatchEvent(new CustomEvent('taarya:project-selected', { detail: { projectId } }));
    loadProjectItems(projectId);
  }

  async function loadProjectItems(projectId) {
    const list = document.getElementById('project-items-list');
    if (!list) return;
    list.replaceChildren();
    if (!projectId) {
      list.innerHTML = '<span class="project-items-empty">Create or select a project</span>';
      return;
    }
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/items`);
      if (!response.ok) throw new Error(`Saved items unavailable (${response.status})`);
      const items = await response.json();
      if (!items.length) {
        list.innerHTML = '<span class="project-items-empty">Pinned sources and saved searches appear here</span>';
        return;
      }
      items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'project-item-row';
        row.dataset.itemId = item.id;
        const icon = document.createElement('span');
        icon.className = 'material-icons';
        icon.textContent = ({ star: 'star', paper: 'article', search: 'search', region: 'place' })[item.item_type] || 'bookmark';
        const title = document.createElement('span');
        title.className = 'project-item-title';
        title.textContent = item.title;

        const unpinBtn = document.createElement('button');
        unpinBtn.className = 'project-item-unpin-btn';
        unpinBtn.type = 'button';
        unpinBtn.title = 'Unpin item';
        unpinBtn.setAttribute('aria-label', `Unpin ${item.title}`);
        const unpinIcon = document.createElement('span');
        unpinIcon.className = 'material-icons';
        unpinIcon.textContent = 'close';
        unpinBtn.append(unpinIcon);

        unpinBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          unpinBtn.disabled = true;
          try {
            const delRes = await fetch(`/api/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(item.id)}`, {
              method: 'DELETE'
            });
            if (!delRes.ok) throw new Error(`Unpin failed (${delRes.status})`);
            row.remove();
            if (!list.querySelectorAll('.project-item-row').length) {
              list.innerHTML = '<span class="project-items-empty">Pinned sources and saved searches appear here</span>';
            }
          } catch (err) {
            console.error('[Projects] Could not unpin item:', err);
            unpinBtn.disabled = false;
          }
        });

        row.append(icon, title, unpinBtn);
        list.append(row);
      });
    } catch (error) {
      list.innerHTML = '<span class="project-items-empty">Could not load saved items</span>';
      console.error('[Projects] Items failed to load:', error);
    }
  }
  window.TaarYaProjectsRefresh = () => loadProjectItems(activeProjectId);

  async function loadProjects() {
    const list = document.getElementById('project-list');
    if (!list) return;
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) throw new Error(`Projects unavailable (${response.status})`);
      projects = await response.json();
      list.replaceChildren();
      const browserCount = document.getElementById('project-browser-count');
      if (browserCount) browserCount.textContent = `${projects.length} projects`;
      const mobileSelect = document.getElementById('mobile-project-select');
      if (mobileSelect) mobileSelect.replaceChildren();
      if (!projects.length) {
        const empty = document.createElement('div');
        empty.className = 'project-list-empty';
        empty.textContent = 'Create a project to collect chats, searches, and sources.';
        list.append(empty);
        if (mobileSelect) mobileSelect.add(new Option('No project', ''));
        const name = document.getElementById('active-project-name');
        if (name) name.textContent = 'No project selected';
        selectProject(null);
        return;
      }
      const requestedProject = new URLSearchParams(window.location.search).get('project');
      if (requestedProject && projects.some((project) => project.id === requestedProject)) {
        activeProjectId = requestedProject;
      } else if (!projects.some((project) => project.id === activeProjectId)) {
        activeProjectId = projects[0].id;
      }
      projects.forEach((project) => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'project-row';
        row.dataset.projectId = project.id;
        row.setAttribute('aria-current', String(project.id === activeProjectId));
        const icon = document.createElement('span');
        icon.className = 'material-icons';
        icon.textContent = 'folder';
        const name = document.createElement('span');
        name.className = 'project-row-name';
        name.textContent = project.name;
        const count = document.createElement('span');
        count.className = 'project-row-count';
        count.textContent = project.session_count || '0';
        row.append(icon, name, count);
        row.addEventListener('click', () => selectProject(project.id));
        list.append(row);
        if (mobileSelect) mobileSelect.add(new Option(project.name, project.id));
      });
      if (mobileSelect) mobileSelect.value = activeProjectId;
      const activeName = document.getElementById('active-project-name');
      if (activeName) activeName.textContent = projects.find((project) => project.id === activeProjectId)?.name || 'Research workspace';
      localStorage.setItem('taarya.activeProjectId', activeProjectId);
      loadProjectItems(activeProjectId);
      window.dispatchEvent(new CustomEvent('taarya:projects-ready', { detail: { projects, projectId: activeProjectId } }));
    } catch (error) {
      list.innerHTML = '<div class="project-list-empty">Projects could not be loaded. Check the service status.</div>';
      console.error('[Projects] List failed to load:', error);
    }
  }

  const isChatPage = window.location.pathname.endsWith('/chat.html');
  const sidebarPartial = isChatPage
    ? '/static/partials/workspace-sidebar.html'
    : '/static/partials/sidebar.html';

  fetch(sidebarPartial)
    .then(r => r.text())
    .then(async (html) => {
      const mount = document.getElementById('sidebar-mount');
      if (!mount) return;
      mount.innerHTML = html;
      mount.querySelector('.sidebar')?.classList.remove('collapsed');
      // Mark the active nav link based on current page
      document.querySelectorAll('.sidebar-nav a').forEach(a => {
        const href = a.getAttribute('href');
        a.classList.toggle('active', window.location.pathname.endsWith(href.replace('/static', '')));
      });
      if (!isChatPage) loadSessions();
      const newSessionButton = document.getElementById('new-chat-btn');
      if (newSessionButton && !isChatPage) {
        newSessionButton.addEventListener('click', () => {
          window.location.href = '/static/chat.html?new=1';
        });
      }
      const dialog = document.getElementById('project-create-dialog');
      const createButton = document.getElementById('new-project-btn');
      const cancelButton = document.getElementById('project-cancel-btn');
      const form = document.getElementById('project-create-form');
      [createButton, document.getElementById('mobile-new-project')].forEach((button) => {
        button?.addEventListener('click', () => dialog?.showModal());
      });
      document.getElementById('mobile-project-select')?.addEventListener('change', (event) => {
        if (event.target.value) selectProject(event.target.value);
      });
      cancelButton?.addEventListener('click', () => dialog?.close());
      form?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const errorEl = document.getElementById('project-create-error');
        const submit = document.getElementById('project-submit-btn');
        errorEl.hidden = true;
        submit.disabled = true;
        try {
          const response = await fetch('/api/projects', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: document.getElementById('project-name').value,
              description: document.getElementById('project-description').value,
            }),
          });
          const project = await response.json();
          if (!response.ok) throw new Error(project.detail || `Project creation failed (${response.status})`);
          document.getElementById('project-create-form').reset();
          dialog.close();
          activeProjectId = project.id;
          await loadProjects();
          selectProject(project.id);
          if (!isChatPage) window.location.href = `/static/chat.html?project=${encodeURIComponent(project.id)}`;
        } catch (error) {
          errorEl.textContent = error.message;
          errorEl.hidden = false;
        } finally {
          submit.disabled = false;
        }
      });
      // Load the active project before chat.js fetches its sessions.
      await loadProjects();
      document.dispatchEvent(new Event('sidebar-ready'));
    });
})();
