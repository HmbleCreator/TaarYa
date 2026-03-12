(function () {
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
      // Re-dispatch a custom event so chat.js knows the sidebar is ready
      document.dispatchEvent(new Event('sidebar-ready'));
    });
})();
