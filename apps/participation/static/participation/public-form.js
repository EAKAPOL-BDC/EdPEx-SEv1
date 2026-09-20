(() => {
  'use strict';
  const form = document.getElementById('public-response');
  if (!form) return;
  form.elements.enhanced_js.value = '1';
  const rules = JSON.parse(document.getElementById('public-question-rules')?.textContent || '[]');
  const rulesById = new Map(rules.map(q => [q.id, q]));
  const read = name => {
    const control = [...form.elements].find(e => e.name === name && !e.disabled && (e.type !== 'radio' || e.checked));
    const raw = control?.value || '';
    return raw.startsWith('value:') ? raw.slice(6) : raw.startsWith('state:') ? '' : raw;
  };
  function updateQuestions() {
    let changed = false;
    form.querySelectorAll('[data-question-id]').forEach(card => {
      const id = card.dataset.questionId;
      const q = rulesById.get(id);
      const rule = q?.visibility || {};
      let show = true;
      if (rule.op === 'eq') show = read(rule.question_id) === String(rule.value);
      if (rule.op === 'context_role_and_information') show = (rule.information || []).includes(read('F04-P03'));
      if (id.startsWith('F04-') && !id.startsWith('F04-P') && read('F04-P03') === 'none') show = false;
      if (id === 'F02-P04-month') show = read('F02-P04') === 'month_year';
      if (id.endsWith('-reason')) show = [...form.elements].some(e => e.name === id.slice(0,-7) && e.checked && e.value === 'state:not_applicable');
      if (card.hidden === show) changed = true;
      card.hidden = !show;
      card.querySelectorAll('input,select,textarea').forEach(e => {e.disabled = !show;});
      if (q?.type === 'integer_scale') card.classList.add('rating-question');
    });
    form.querySelectorAll('[data-question-section]').forEach(section => {
      const empty = ![...section.querySelectorAll('[data-question-id]')].some(c => !c.hidden);
      section.dataset.conditionHidden = empty ? 'yes' : 'no';
      form.querySelectorAll('[data-section-link]').forEach(link => {if (link.dataset.sectionLink === section.dataset.questionSection) link.hidden = empty;});
      if (empty) section.hidden = true;
    });
    if (changed) {
      const status = document.getElementById('dynamic-status');
      if (status) status.textContent = document.documentElement.lang === 'en' ? 'Questions updated automatically. Your other answers remain on this page.' : 'ปรับคำถามที่เกี่ยวข้องให้แล้ว คำตอบข้ออื่นยังอยู่ในหน้านี้';
    }
    document.dispatchEvent(new Event('portal:updated'));
  }
  form.addEventListener('change', event => {
    updateQuestions();
    if (event.target.name === 'F04-P03' && read('F04-P03') !== 'none') {
      const section = [...form.querySelectorAll('[data-question-section]')].find(s => s.dataset.conditionHidden !== 'yes' && !['P','O'].includes(s.dataset.questionSection));
      if (section) [...form.querySelectorAll('[data-section-link]')].find(link => link.dataset.sectionLink === section.dataset.questionSection)?.click();
    }
  });
  updateQuestions();
  document.querySelectorAll('[data-public-language]').forEach(button => button.addEventListener('click', () => {
    const target = new URL(form.action || location.href);
    target.searchParams.set('lang', button.dataset.publicLanguage);
    form.action = target.href;
    // POST the current values to re-render translated fields without browser storage.
    form.requestSubmit(form.querySelector('[name="action"][value="update"]'));
  }));
  form.addEventListener('submit', event => {
    if (event.submitter?.value !== 'submit') return;
    // Keep the submitter enabled until the browser builds the successful controls.
    if (form.dataset.submitting === 'yes') {event.preventDefault(); return;}
    form.dataset.submitting = 'yes';
    setTimeout(() => {document.querySelectorAll('button[type="submit"]').forEach(b => {b.disabled = true;});}, 0);
  });
  window.addEventListener('pageshow', () => {delete form.dataset.submitting; form.querySelectorAll('button[type="submit"]').forEach(b => {b.disabled = false;});});
})();
