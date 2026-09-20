/* Progressive layout helpers; never change form names, values or submission rules. */
(() => {
  'use strict';
  const english = () => document.documentElement.lang === 'en';
  function reviewCount(form) {
    const boxes = [...form.querySelectorAll('input[name="checked"]')];
    const selected = boxes.filter(box => box.checked).length;
    const output = form.querySelector('[data-review-count]');
    if (output) {
      output.hidden = false;
      output.textContent = english() ? `${selected} selected on this page` : `เลือกแล้ว ${selected} รายการในหน้านี้`;
    }
    const all = form.querySelector('[data-review-select-all]');
    if (all) {
      all.disabled = !boxes.length;
      all.checked = boxes.length > 0 && selected === boxes.length;
      all.indeterminate = selected > 0 && selected < boxes.length;
    }
  }
  function init() {
    document.querySelectorAll('.nx-management [data-question-toggle]').forEach(button => {
      if (button.dataset.ready) return;
      const rows = [...button.closest('.nx-question-directory').querySelectorAll('.nx-question-row')];
      if (!rows.length) return;
      button.hidden = false; button.dataset.ready = '1';
      const sync = () => {
        const expanded = rows.every(row => row.open);
        button.setAttribute('aria-expanded', String(expanded));
        button.textContent = expanded ? (english() ? 'Collapse all' : 'ย่อทั้งหมด') : (english() ? 'Expand all' : 'ขยายทั้งหมด');
      };
      button.addEventListener('click', () => { const open = !rows.every(row => row.open); rows.forEach(row => { row.open = open; }); sync(); });
      rows.forEach(row => row.addEventListener('toggle', sync)); sync();
    });
    document.querySelectorAll('.nx-management [data-add-choice]').forEach(button => {
      if (button.dataset.ready) return;
      button.dataset.ready = '1';
      const section = button.closest('.nx-choice-section');
      // Empty extra rows stay in the formset; errors, existing choices and entered text stay visible.
      const unused = [...section.querySelectorAll('.choice-editor')].filter(row =>
        !row.querySelector('.errorlist, [aria-invalid="true"]') &&
        !['id','code','label_th','score'].some(name => row.querySelector(`[name$="-${name}"]`)?.value.trim()) &&
        !row.querySelector('[name$="-DELETE"]')?.checked);
      unused.forEach(row => { row.hidden = true; });
      button.hidden = !unused.length;
      button.addEventListener('click', () => {
        const row = unused.shift();
        if (!row) return;
        row.hidden = false;
        row.querySelector('input:not([type="hidden"]):not(:disabled),textarea:not(:disabled)')?.focus();
        // Keep focus usable after revealing the final server-provided extra row.
        if (!unused.length) button.hidden = true;
      });
    });
    document.querySelectorAll('[data-review-form]').forEach(reviewCount);
  }
  document.addEventListener('change', event => {
    const form = event.target.closest('[data-review-form]');
    // The existing select-all handler runs first and preserves page-scoped selection.
    if (form) reviewCount(form);
  });
  document.addEventListener('portal:updated', init);
  window.addEventListener('pageshow', init);
  init();
})();
