/**
 * TaarYa — Shared Theme Toggle (Dark / Light) + Sidebar Collapse
 *
 * Include this script on any page AFTER the closing </body> or at the
 * bottom of the page.  It will:
 *   1. Restore the saved theme from localStorage (or default to "dark").
 *   2. Wire up any element with id="theme-toggle" to toggle the theme.
 *   3. Set the correct icon (light_mode / dark_mode) on the toggle.
 *   4. Restore sidebar collapsed/expanded state from localStorage.
 *   5. Wire up any element with id="sidebar-toggle" to collapse/expand.
 */
(function () {
  'use strict';

  const THEME_KEY    = 'taarya-theme';
  const SIDEBAR_KEY  = 'taarya-sidebar';

  /* ── Theme ────────────────────────────────────────────── */
  const stored = localStorage.getItem(THEME_KEY) || 'dark';
  document.documentElement.setAttribute('data-theme', stored);

  function updateToggleIcon() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const current = document.documentElement.getAttribute('data-theme');
    btn.innerHTML = current === 'dark'
      ? '<span class="material-icons" style="font-size:20px">light_mode</span>'
      : '<span class="material-icons" style="font-size:20px">dark_mode</span>';
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(THEME_KEY, next);
    updateToggleIcon();
  }

  /* ── Sidebar ──────────────────────────────────────────── */
  function updateSidebarIcon() {
    const btn = document.getElementById('sidebar-toggle');
    if (!btn) return;
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    const collapsed = sidebar.classList.contains('collapsed');
    btn.innerHTML = '<span class="material-icons" style="font-size:18px">'
      + (collapsed ? 'chevron_right' : 'chevron_left') + '</span>';
  }

  function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('collapsed');
    const isCollapsed = sidebar.classList.contains('collapsed');
    localStorage.setItem(SIDEBAR_KEY, isCollapsed ? 'collapsed' : 'expanded');
    updateSidebarIcon();
  }

  function restoreSidebar() {
    const state = localStorage.getItem(SIDEBAR_KEY);
    if (state === 'collapsed') {
      const sidebar = document.querySelector('.sidebar');
      if (sidebar) sidebar.classList.add('collapsed');
    }
  }

  /* ── Init ──────────────────────────────────────────────── */
  // Restore sidebar immediately
  restoreSidebar();

  document.addEventListener('DOMContentLoaded', function () {
    // Theme
    updateToggleIcon();
    var themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

    // Sidebar
    updateSidebarIcon();
    var sidebarBtn = document.getElementById('sidebar-toggle');
    if (sidebarBtn) sidebarBtn.addEventListener('click', toggleSidebar);
  });
})();
