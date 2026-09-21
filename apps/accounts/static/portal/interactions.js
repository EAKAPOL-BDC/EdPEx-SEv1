// Progressive enhancement: forms retain normal POST and server-side permission checks.
(() => {
  const english = () => document.documentElement.lang === 'en';
  function preview() {
    const form = document.querySelector('.grant-form');
    if (!form) return;
    const output = form.querySelector('[data-grant-preview]');
    const member = form.elements.namedItem('membership');
    const role = form.elements.namedItem('role');
    if (!member.value || !role.value) { output.hidden = true; return; }
    const expiry = form.elements.namedItem('active_until').value;
    const children = form.elements.namedItem('include_descendants').checked;
    output.hidden = false;
    output.textContent = (english() ? 'Review: ' : 'สรุปก่อนบันทึก: ') +
      member.selectedOptions[0].textContent + ' · ' + role.selectedOptions[0].textContent + ' · ' +
      (expiry ? expiry.replace('T', ' ') + ' (UTC+7)' : (english() ? 'No expiry' : 'ไม่กำหนดวันสิ้นสุด')) +
      (children ? (english() ? ' · Includes child scopes' : ' · รวมขอบเขตย่อย') : '');
  }
  function init() {
    document.querySelectorAll('[data-enhanced]').forEach(e => { e.hidden = false; });
    document.querySelectorAll('form[aria-busy="true"]').forEach(form => {
      form.removeAttribute('aria-busy');
      form.querySelectorAll('[data-submitting]').forEach(b => {
        b.disabled = false; b.textContent = b.dataset.originalText;
        delete b.dataset.submitting;
      });
    });
    preview();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-pick-expiry], [data-clear-expiry]');
    if (!button) return;
    const input = button.closest('form').elements.namedItem('active_until');
    if (button.hasAttribute('data-clear-expiry')) {
      input.value = ''; input.dispatchEvent(new Event('input', {bubbles:true}));
    } else {
      input.focus();
      try { input.showPicker?.(); } catch { /* Native input remains usable. */ }
    }
  });
  document.addEventListener('input', preview);
  document.addEventListener('change', preview);
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('main form') || form.method.toLowerCase() !== 'post' || event.defaultPrevented) return;
    if (form.getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
    if (form.querySelector('.danger') && !window.confirm(english() ?
      'Revoke this role? The history will be retained.' : 'ต้องการเพิกถอนบทบาทนี้หรือไม่? ประวัติเดิมจะยังคงอยู่')) {
      event.preventDefault(); return;
    }
    form.setAttribute('aria-busy', 'true');
    const button = event.submitter;
    if (button && !button.name) {
      button.dataset.originalText = button.textContent;
      button.dataset.submitting = 'true'; button.disabled = true;
      button.textContent = english() ? 'Saving…' : 'กำลังบันทึก…';
    }
  });
  document.addEventListener('portal:updated', init);
  window.addEventListener('pageshow', init);
  init();
})();
