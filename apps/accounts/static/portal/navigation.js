/* Navigation state only, in memory. No answers or account data are stored. */
(() => {
  'use strict';
  const mobile = window.matchMedia('(max-width: 1023px)');
  const groups = new Map();
  const parts = () => ({
    shell: document.querySelector('.workspace-shell'),
    sidebar: document.getElementById('workspace-navigation'),
    toggle: document.querySelector('[data-menu-toggle]'),
    backdrop: document.querySelector('.sidebar-backdrop'),
  });
  const background = () => document.querySelectorAll('.site-header, .nx-footer, .workspace-body, .mobile-menu-bar');
  function focusable(sidebar) {
    return [...sidebar.querySelectorAll('a[href], button:not([disabled]), summary')].filter(el => {
      const group = el.closest('details');
      return !el.hidden && (!group || group.open || el === group.querySelector('summary'));
    });
  }
  function setOpen(open, returnFocus = true) {
    const { shell, sidebar, toggle, backdrop } = parts();
    if (!shell || !sidebar || !toggle) return;
    open = Boolean(open && mobile.matches);
    shell.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    if (backdrop) backdrop.hidden = !open;
    background().forEach(el => { el.inert = open; });
    sidebar.inert = mobile.matches && !open;
    if (mobile.matches && !open) sidebar.setAttribute('aria-hidden', 'true');
    else sidebar.removeAttribute('aria-hidden');
    if (open) {
      sidebar.setAttribute('role', 'dialog');
      sidebar.setAttribute('aria-modal', 'true');
      (sidebar.querySelector('[data-menu-close]') || focusable(sidebar)[0])?.focus();
    } else {
      sidebar.removeAttribute('role');
      sidebar.removeAttribute('aria-modal');
      if (returnFocus && mobile.matches) toggle.focus();
    }
  }
  function initialize() {
    const { shell, sidebar } = parts();
    if (!shell || !sidebar) return;
    shell.setAttribute('data-navigation-ready', '');
    sidebar.querySelectorAll('[data-nav-group]').forEach(group => {
      if (groups.has(group.dataset.navGroup)) group.open = groups.get(group.dataset.navGroup);
      if (group.querySelector('[aria-current="page"]')) group.open = true;
    });
    setOpen(false, false);
    if (!mobile.matches) {
      const active = sidebar.querySelector('[aria-current="page"]');
      if (active) {
        const outer = sidebar.getBoundingClientRect();
        const inner = active.getBoundingClientRect();
        if (inner.bottom > outer.bottom) sidebar.scrollTop += inner.bottom - outer.bottom + 20;
      }
    }
  }
  document.addEventListener('click', event => {
    if (event.target.closest('[data-menu-toggle]')) {
      const { shell } = parts();
      setOpen(!shell?.classList.contains('menu-open'));
    } else if (event.target.closest('[data-menu-close]')) {
      setOpen(false);
    } else if (event.target.closest('#workspace-navigation a[href]') && mobile.matches) {
      setOpen(false);
    }
  });
  document.addEventListener('toggle', event => {
    if (event.target.matches?.('[data-nav-group]')) groups.set(event.target.dataset.navGroup, event.target.open);
  }, true);
  document.addEventListener('keydown', event => {
    const { shell, sidebar } = parts();
    if (!mobile.matches || !shell?.classList.contains('menu-open')) return;
    if (event.key === 'Escape') {
      event.preventDefault(); setOpen(false); return;
    }
    if (event.key !== 'Tab') return;
    const entries = focusable(sidebar);
    const first = entries[0], last = entries[entries.length - 1];
    if (!first) return;
    if (event.shiftKey && (document.activeElement === first || !sidebar.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !sidebar.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  mobile.addEventListener('change', () => {
    const { sidebar, toggle } = parts();
    const wasInMenu = sidebar?.contains(document.activeElement);
    setOpen(false, false);
    if (wasInMenu) {
      if (mobile.matches) toggle?.focus();
      else (sidebar.querySelector('[aria-current="page"]') || sidebar.querySelector('a'))?.focus();
    }
  });
  document.addEventListener('portal:updated', initialize);
  window.addEventListener('pageshow', initialize);
  initialize();
})();
