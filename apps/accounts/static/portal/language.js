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
  const data = new FormData(form);
  data.set('language', button.value);
  button.disabled = true;
  try {
    const saved = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin'});
    if (!saved.ok) throw new Error('language');
    const page = await fetch(location.href, {credentials: 'same-origin'});
    if (!page.ok) throw new Error('page');
    const next = new DOMParser().parseFromString(await page.text(), 'text/html');
    for (const selector of ['header', 'main', 'footer']) {
      document.querySelector(selector).replaceWith(next.querySelector(selector));
    }
    document.documentElement.lang = next.documentElement.lang;
    document.title = next.title;
    [...document.querySelectorAll('main form')].forEach((f, i) => {
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
    document.querySelector(`[data-language-form] button[value="${button.value}"]`)?.focus({preventScroll:true});
  } catch {
    alert(document.documentElement.lang === 'en' ? 'Unable to change language. Your inputs are retained. Please try again.' : 'เปลี่ยนภาษาไม่สำเร็จ ข้อมูลที่กรอกยังอยู่ กรุณาลองอีกครั้ง');
    button.disabled = false;
  }
});
