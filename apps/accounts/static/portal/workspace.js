// Progressive presentation only. Answers remain in one native POST form.
(() => {
  const english = () => document.documentElement.lang === 'en';
  let activeSection = '';
  function showSection(form, key, focus = false) {
    const sections = [...form.querySelectorAll('[data-question-section]')].filter(s => s.dataset.conditionHidden !== 'yes');
    const index = sections.findIndex(s => s.dataset.questionSection === key);
    if (index < 0) return;
    activeSection = key;
    const marker = form.querySelector('input[name="ui_section"]');
    if (marker) marker.value = key;
    form.querySelectorAll('[data-condition-hidden="yes"]').forEach(s => {s.hidden = true;});
    sections.forEach((section, i) => {
      section.hidden = i !== index;
      const caption = section.querySelector('.question-section-heading .section-caption');
      if (caption) caption.textContent = (english() ? 'SECTION ' : 'หมวดที่ ') + `${i + 1} / ${sections.length}`;
      const link = [...form.querySelectorAll('[data-section-link]')].find(a => a.dataset.sectionLink === section.dataset.questionSection);
      if (link?.querySelector('span')) link.querySelector('span').textContent = String(i + 1).padStart(2, '0');
    });
    form.querySelectorAll('[data-section-link]').forEach(link => {
      if (link.dataset.sectionLink === key) link.setAttribute('aria-current', 'step');
      else link.removeAttribute('aria-current');
    });
    form.querySelector('[data-section-prev]').disabled = index === 0;
    form.querySelector('[data-section-next]').disabled = index === sections.length - 1;
    form.querySelector('[data-section-position]').textContent = `${index + 1} / ${sections.length}`;
    if (focus) sections[index].querySelector('h2').focus();
  }
  function updateProgress(form) {
    const containers = [...form.querySelectorAll('[data-answer-input]')].filter(box => !box.closest('[data-question-id]')?.hidden && !box.closest('[data-question-id]')?.dataset.questionId.includes('-O'));
    const controls = containers.map(box => box.querySelector('input:checked') || box.querySelector('select, textarea, input:not([type=radio]):not([type=checkbox]):not([type=hidden])'));
    const chosen = controls.filter(field => field && field.value.trim() !== '').length;
    const count = form.querySelector('[data-answer-count]');
    if (count) count.textContent = `${chosen} / ${containers.length}`;
    const progress = form.querySelector('progress');
    if (progress) { progress.max = containers.length || 1; progress.value = chosen; }
    controls.filter(field => field?.value === 'not_applicable').forEach(field => {
      const extras = field.closest('.question-card')?.querySelector('.answer-extras');
      if (extras) extras.open = true;
    });
  }

  function init() {
    document.documentElement.classList.add('js');
    document.querySelectorAll('[data-section-form]').forEach(form => {
      form.querySelectorAll('[data-enhanced]').forEach(el => { el.hidden = false; });
      const sections = [...form.querySelectorAll('[data-question-section]')].filter(s => s.dataset.conditionHidden !== 'yes');
      if (!sections.length) return;
      const invalid = (form.querySelector('[aria-invalid="true"]') || form.querySelector('.errorlist'))?.closest('[data-question-section]');
      const current = form.querySelector('[name=ui_section]')?.value || activeSection;
      const chosen = invalid?.dataset.questionSection ||
        sections.find(s => s.id === window.location.hash.slice(1))?.dataset.questionSection ||
        sections.find(s => s.dataset.questionSection === current)?.dataset.questionSection || sections[0].dataset.questionSection;
      showSection(form, chosen);
      updateProgress(form);
    });
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-section-link]');
    if (link) {
      event.preventDefault();
      showSection(link.closest('[data-section-form]'), link.dataset.sectionLink, true);
    }
    const step = event.target.closest('[data-section-prev], [data-section-next]');
    if (step) {
      const form = step.closest('[data-section-form]');
      const sections = [...form.querySelectorAll('[data-question-section]')].filter(s => s.dataset.conditionHidden !== 'yes');
      const index = sections.findIndex(s => !s.hidden) + (step.hasAttribute('data-section-next') ? 1 : -1);
      if (sections[index]) showSection(form, sections[index].dataset.questionSection, true);
    }
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-result-query]')) {
      const query = event.target.value.trim().toLocaleLowerCase();
      const rows = [...document.querySelectorAll('.result-grid .operator-series')];
      rows.forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase().includes(query); });
      document.querySelector('[data-result-count]').textContent =
        (english() ? 'Showing ' : 'แสดง ') + rows.filter(row => !row.hidden).length + ' / ' + rows.length;
    }
    const form = event.target.closest('[data-section-form]');
    if (!form) return;
    updateProgress(form);
    const hint = form.querySelector('[data-save-hint]');
    if (hint) hint.textContent = english() ? 'Unsaved changes on this page' : 'มีคำตอบที่ยังไม่ได้บันทึกในหน้านี้';
  });
  document.addEventListener('portal:updated', init);
  window.addEventListener('pageshow', init);
  init();
})();

// Review applies only to the pairs rendered on this page; never to hidden pages.
document.addEventListener('change', event => {
  if (!event.target.matches('[data-review-select-all]')) return;
  const form = event.target.closest('form');
  form.querySelectorAll('input[name="checked"]').forEach(box => { box.checked = event.target.checked; });
});
