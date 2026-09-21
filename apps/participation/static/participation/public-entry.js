(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('public-catalog').textContent);
  const el = id => document.getElementById(id);
  const config = el('entry-config');
  const state = {lang: 'th', category: '', group: '', level: '', programme: '', year: '', rows: [], busy: false};
  const text = value => value[state.lang];
  const wording = (th, en) => state.lang === 'en' ? en : th;
  const icons = ['◎', '◇', '✧', '♡', '↔', '◈'];
  const levels = {bachelor: {th: 'ปริญญาตรี', en: 'Bachelor’s'}, master: {th: 'ปริญญาโท', en: 'Master’s'}, doctoral: {th: 'ปริญญาเอก', en: 'Doctoral'}};
  function node(tag, className, content) { const n = document.createElement(tag); if (className) n.className = className; if (content) n.textContent = content; return n; }
  function status(th = '', en = '') { el('entry-status').textContent = wording(th, en); }
  function focus(id) { el(id).focus({preventScroll: true}); el(id).scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'}); }
  function group() { return data.categories.flatMap(c => c.groups).find(g => g.code === state.group); }
  function invalidate() { state.rows = []; el('assessments').hidden = true; status(); }
  function renderCategories() {
    el('categories').replaceChildren(...data.categories.map((c, index) => {
      const button = node('button', 'category-card'); button.type = 'button'; button.setAttribute('aria-pressed', String(state.category === c.key));
      const icon = node('span', 'category-icon', icons[index]); icon.setAttribute('aria-hidden', 'true');
      const arrow = node('span', 'category-arrow', '↗'); arrow.setAttribute('aria-hidden', 'true');
      button.append(icon, arrow, node('strong', '', text(c.name)), node('small', '', text(c.hint)));
      button.addEventListener('click', () => { state.category = c.key; state.group = c.groups.length === 1 ? c.groups[0].code : ''; state.level = ''; state.programme = ''; state.year = ''; invalidate(); renderCategories(); renderContext(); focus('context-title'); }); return button;
    }));
  }
  function selectOptions(id, rows, current, placeholder) {
    const select = el(id); select.replaceChildren();
    select.append(new Option(placeholder, ''));
    rows.forEach(([key, name]) => select.append(new Option(name, key)));
    select.value = current;
  }
  function renderStudy() {
    const g = group(); const available = g?.levels || []; el('study').hidden = !available.length;
    if (available.length === 1) state.level = available[0];
    selectOptions('level', available.map(key => [key, text(levels[key])]), state.level, wording('เลือกระดับ', 'Choose a level'));
    selectOptions('programme', (data.programmes[state.level] || []).map(p => [p.key, text(p.name)]), state.programme, wording('เลือกหลักสูตร', 'Choose a programme'));
    selectOptions('year', (data.years[state.level] || []).map(y => [y, wording('ชั้นปีที่ '+y.replace('+', ' ขึ้นไป'), 'Year '+y)]), state.year, wording('เลือกชั้นปี', 'Choose a year'));
    el('level').disabled = available.length === 1;
    el('programme').disabled = !state.level; el('year').disabled = !state.level;
    el('group-hint').textContent = g ? text(g.hint) : '';
  }
  function renderContext() {
    const category = data.categories.find(c => c.key === state.category);
    el('context-panel').hidden = !category;
    if (!category) return;
    el('context-title').textContent = text(category.name);
    el('groups').replaceChildren(...category.groups.map(g => {
      const label = node('label', 'group-choice'); const radio = node('input'); radio.type = 'radio'; radio.name = 'public-group'; radio.value = g.code; radio.checked = state.group === g.code;
      const copy = node('span'); copy.append(node('strong', '', text(g.name)), node('small', '', g.code)); label.append(radio, copy);
      radio.addEventListener('change', () => {state.group = g.code; state.level = ''; state.programme = ''; state.year = ''; invalidate(); renderStudy();}); return label;
    })); renderStudy();
  }
  function context() { return {group: state.group, level: state.level, programme: state.programme, year: state.year}; }
  async function post(url, payload) {
    const response = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.querySelector('input').value}, body: JSON.stringify(payload)});
    if (!response.ok) throw new Error(response.status === 429 ? 'rate' : 'unavailable');
    return response.json();
  }
  function renderRows() {
    el('staff-note').hidden = !['ST1', 'ST2'].includes(state.group);
    if (!state.rows.length) {
      const empty = node('div', 'empty-state'); empty.append(node('h3', '', wording('ยังไม่มีแบบประเมินที่เปิดรับสำหรับกลุ่มนี้', 'No open assessments for this group')),
        node('p', '', wording('ตรวจกลุ่มและหลักสูตรอีกครั้ง หรือกลับมาเมื่อเจ้าหน้าที่เปิดรอบ ไม่จำเป็นต้องสมัครสมาชิก', 'Check your group and programme, or return when staff publish a collection. No registration is needed.')));
      el('form-cards').replaceChildren(empty); return;
    }
    el('form-cards').replaceChildren(...state.rows.map(row => {
      const card = node('article', 'form-card'); const copy = node('div');
      copy.append(node('span', 'form-badge', row.instrument+' · '+row.year+(row.realm === 'test' ? wording(' · รอบทดสอบ', ' · TEST') : '')), node('h3', '', text(row.title)), node('p', '', text(row.context)),
        node('p', '', wording('ปิดรับ ', 'Closes ')+new Intl.DateTimeFormat(state.lang === 'th' ? 'th-TH' : 'en-GB', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok'}).format(new Date(row.closes))+' (UTC+7)'));
      const start = node('button', 'primary', wording('เริ่มประเมิน →', 'Start assessment →')); start.type = 'button';
      start.addEventListener('click', async () => {
        if (state.busy) return; state.busy = true; start.disabled = true; status(wording('', ''), '');
        try { const result = await post(config.dataset.start, {binding_id: row.id, context: context()}); location.assign(result.next+'?lang='+state.lang); }
        catch (_) {status('แบบประเมินอาจปิดรับหรือการเชื่อมต่อขัดข้อง กรุณาตรวจรายการอีกครั้ง', 'The assessment may have closed or the connection failed. Refresh the list and retry.'); start.disabled = false; state.busy = false;}
      }); card.append(copy, start); return card;
    }));
  }
  function renderLanguage() {
    document.documentElement.lang = state.lang;
    document.title = 'NEXORA · '+wording('เข้าร่วมประเมิน', 'Participate');
    document.querySelectorAll('[data-th][data-en]').forEach(n => {
      const words = n.dataset[state.lang].split('|'); n.replaceChildren(document.createTextNode(words[0]));
      if (words[1]) n.append(document.createElement('br'), node('em', '', words[1]));
    });
    document.querySelectorAll('[data-lang]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === state.lang)));
    renderCategories(); renderContext(); if (!el('assessments').hidden) renderRows();
  }
  document.querySelectorAll('[data-lang]').forEach(b => b.addEventListener('click', () => {state.lang = b.dataset.lang; renderLanguage();}));
  el('level').addEventListener('change', e => {state.level = e.target.value; state.programme = ''; state.year = ''; invalidate(); renderStudy();});
  for (const id of ['programme', 'year']) el(id).addEventListener('change', e => {state[id] = e.target.value; invalidate();});
  el('change-category').addEventListener('click', () => focus('choose-title'));
  el('back-context').addEventListener('click', () => focus('context-title'));
  el('find-forms').addEventListener('click', async () => {
    if (state.busy) return;
    const g = group();
    if (!g || (g.levels.length && (!state.level || !state.programme || !state.year))) { status('กรุณาเลือกกลุ่ม หลักสูตร และชั้นปีที่เกี่ยวข้องให้ครบ', 'Choose your group and all applicable study details.'); focus('entry-status'); return; }
    state.busy = true; el('find-forms').disabled = true; status('กำลังตรวจแบบประเมินที่เปิดรับ…', 'Finding open assessments…');
    const selected = JSON.stringify(context());
    try { const result = await post(config.dataset.choices, context()); if (selected !== JSON.stringify(context())) return; state.rows = result.collections; el('assessments').hidden = false; renderRows(); status(); focus('forms-title'); }
    catch (_) {status('ยังตรวจรายการไม่ได้ กรุณารอสักครู่แล้วลองใหม่', 'Unable to load assessments. Wait a moment and retry.');}
    finally {state.busy = false; el('find-forms').disabled = false;}
  });
  renderLanguage();
})();
