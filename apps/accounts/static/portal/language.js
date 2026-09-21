// Preserve unsent form values in memory, including passwords; never persist them.
document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (!form.matches('[data-language-form]')) return;
  event.preventDefault();
  const button = event.submitter;
  if (!button) return;
  const values = [...document.querySelectorAll('main form')].map(f =>
    [...f.elements].filter(e => e.name && e.name !== 'csrfmiddlewaretoken')
      .map(e => ({name: e.name, type: e.type, value: e.value, checked: e.checked,
        selected: e.multiple ? [...e.selectedOptions].map(o => o.value) : null})));
  const positions = ['.workspace-body', '#workspace-navigation'].map(selector => ({
    selector, top: document.querySelector(selector)?.scrollTop || 0, left: document.querySelector(selector)?.scrollLeft || 0,
  }));
  const data = new FormData(form);
  data.set('language', button.value);
  button.disabled = true;
  try {
    const saved = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin'});
    if (!saved.ok) throw new Error('language');
    const page = await fetch(location.href, {credentials: 'same-origin'});
    if (!page.ok) throw new Error('page');
    const next = new DOMParser().parseFromString(await page.text(), 'text/html');
    // A confirmation is a POST response. GET of this URL is the blank input
    // form, not the review. Keep its exact DOM, payload, acknowledgement and
    // expiring ticket. Calculation previews also preserve their signed cutoff and
    // save action; their translated copy responds to the document language in CSS.
    const reviewing = !!document.querySelector('[data-confirmation-review], [data-calculation-preview]');
    const regions = reviewing ? ['body > header', 'body > footer'] : ['body > header', 'body > main', 'body > footer'];
    for (const selector of regions) {
      document.querySelector(selector).replaceWith(next.querySelector(selector));
    }
    document.documentElement.lang = next.documentElement.lang;
    document.title = next.title;
    if (!reviewing) [...document.querySelectorAll('main form')].forEach((f, i) => {
      for (const previous of values[i] || []) {
        const fields = [...f.elements].filter(field => field.name === previous.name && field.type === previous.type);
        if (previous.type === 'checkbox' || previous.type === 'radio') {
          // namedItem returns RadioNodeList for repeated names, including checkbox groups.
          for (const field of fields) if (field.value === previous.value) field.checked = previous.checked;
        } else if (previous.selected) {
          for (const field of fields) for (const option of field.options) option.selected = previous.selected.includes(option.value);
        } else {
          for (const field of fields) field.value = previous.value;
        }
      }
    });
    document.dispatchEvent(new Event('portal:updated'));
    for (const position of positions) {
      const region = document.querySelector(position.selector);
      if (region) { region.scrollTop = position.top; region.scrollLeft = position.left; }
    }
    document.querySelector(`[data-language-form] button[value="${button.value}"]`)?.focus({preventScroll:true});
  } catch {
    alert(document.documentElement.lang === 'en' ? 'Unable to change language. Your inputs are retained. Please try again.' : 'เปลี่ยนภาษาไม่สำเร็จ ข้อมูลที่กรอกยังอยู่ กรุณาลองอีกครั้ง');
    button.disabled = false;
  }
});
