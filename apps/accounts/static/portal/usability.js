/* UI state stays in memory. No answers, credentials or drafts are persisted here. */
(() => {
  'use strict';
  let dirty = false;
  const english = () => document.documentElement.lang === 'en';
  function editableForm(node) {
    const form = node?.closest?.('main form');
    return form && form.method.toLowerCase() === 'post' && !form.matches('[data-language-form], [data-review-form]');
  }
  document.addEventListener('input', event => { if (editableForm(event.target)) dirty = true; });
  document.addEventListener('change', event => { if (editableForm(event.target)) dirty = true; });
  document.addEventListener('submit', event => {
    if (!editableForm(event.target)) return;
    // Inspect defaultPrevented after the other submit handlers have run.
    queueMicrotask(() => { if (!event.defaultPrevented) dirty = false; });
  });
  window.addEventListener('beforeunload', event => {
    if (!dirty) return;
    event.preventDefault(); event.returnValue = '';
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const shell = document.querySelector('.workspace-shell.menu-open');
    if (shell && !shell.hasAttribute('data-navigation-ready')) {
      shell.classList.remove('menu-open');
      const toggle = document.querySelector('[data-menu-toggle]');
      toggle?.setAttribute('aria-expanded', 'false'); toggle?.focus();
    }
  });
  function enhance() {
    document.querySelectorAll('main .table-scroll').forEach(region => {
      if (!region.hasAttribute('tabindex')) region.tabIndex = 0;
      region.setAttribute('role', 'region');
      if (!region.hasAttribute('aria-label')) region.setAttribute('aria-label', english() ? 'Scrollable data table' : 'ตารางข้อมูล เลื่อนดูได้');
    });
    document.querySelectorAll('main form').forEach(form => {
      if (form.method.toLowerCase() === 'post' && form.querySelector('.errorlist')) dirty = true;
      if (form.querySelector('[data-ui-error-summary]')) return;
      const invalid = [...form.querySelectorAll('[aria-invalid="true"]')].filter(el => el.id && el.type !== 'hidden');
      if (!invalid.length) return;
      const summary = document.createElement('section');
      summary.className = 'ui-error-summary'; summary.dataset.uiErrorSummary = ''; summary.tabIndex = -1; summary.setAttribute('role', 'alert');
      const heading = document.createElement('h2'); heading.textContent = english() ? 'Please check these fields' : 'กรุณาตรวจข้อมูลต่อไปนี้';
      const list = document.createElement('ul');
      invalid.forEach(field => {
        const item = document.createElement('li'); const link = document.createElement('a');
        link.href = '#'+field.id;
        link.textContent = field.labels?.[0]?.textContent?.trim() || (english() ? 'Check this field' : 'ตรวจช่องข้อมูลนี้');
        link.addEventListener('click', event => {
          event.preventDefault();
          const section = field.closest('[data-question-section]');
          if (section?.hidden) {
            [...form.querySelectorAll('[data-section-link]')].find(a => a.dataset.sectionLink === section.dataset.questionSection)?.click();
          }
          field.focus();
        });
        item.append(link); list.append(item);
      });
      summary.append(heading,list); form.prepend(summary);
    });
  }
  document.addEventListener('portal:updated', enhance);
  window.addEventListener('pageshow', enhance);
  enhance();
})();
