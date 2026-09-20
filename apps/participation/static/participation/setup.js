/* Guidance only: no requests, storage, automatic purpose selection or submission. */
(() => {
  'use strict';
  const english = () => document.documentElement.lang === 'en';
  const words = (th, en) => english() ? en : th;
  function examples() {
    document.querySelectorAll('[data-example-target]').forEach(button => {
      const field = document.getElementById(button.dataset.exampleTarget);
      button.hidden = false;
      button.disabled = !field || field.value.trim() !== '';
      button.textContent = button.disabled ? words('มีข้อมูลแล้ว', 'Already filled') : words('ใช้ตัวอย่าง', 'Use example');
      button.title = words('เติมได้เฉพาะช่องว่าง โดยไม่แทนที่ข้อมูลเดิม', 'Fills empty fields only; existing text is preserved');
    });
  }
  function dates() {
    const box = document.querySelector('[data-date-check]');
    if (!box) return;
    const start = document.getElementById('id_open_at');
    const due = document.getElementById('id_due_at');
    const close = document.getElementById('id_close_at');
    const expiry = document.getElementById('id_expires_at');
    box.hidden = false;
    let error = '';
    close.setCustomValidity(''); expiry.setCustomValidity('');
    if (start.value && due.value && close.value && !(start.value <= due.value && due.value <= close.value && start.value < close.value)) {
      error = words('ตรวจวันเปิด ≤ กำหนดส่ง ≤ วันปิด โดยวันปิดต้องหลังวันเปิด', 'Check opens ≤ due ≤ closes, with closing later than opening.');
      close.setCustomValidity(error);
    }
    if (close.value && expiry.value && expiry.value <= close.value) {
      const message = words('วันหมดอายุหลักฐานต้องอยู่หลังวันปิดรอบ', 'Receipt expiry must be later than collection closing.');
      expiry.setCustomValidity(message);
      error = error ? error + ' · ' + message : message;
    }
    const complete = [start, due, close, expiry].every(field => field.value);
    const message = error || (complete ? words('ลำดับวันที่ถูกต้อง โปรดตรวจเวลาที่ต้องการก่อนยืนยัน', 'Date order is correct. Review the intended times before confirming.') : words('กรอกวันที่ให้ครบเพื่อดูลำดับช่วงเวลา', 'Complete the dates to check the schedule.'));
    const status = box.querySelector('[data-date-status]');
    if (status.textContent !== message) status.textContent = message;
    box.classList.toggle('has-date-error', Boolean(error));
    const preview = box.querySelector('[data-date-preview]');
    preview.replaceChildren();
    for (const [field, th, en] of [[start, 'เปิดรับ', 'Opens'], [due, 'กำหนดส่ง', 'Due'], [close, 'ปิดรับ', 'Closes'], [expiry, 'หลักฐานหมดอายุ', 'Proof expires']]) {
      const item = document.createElement('p');
      const label = document.createElement('strong'); label.textContent = words(th, en);
      const value = document.createElement('span');
      // Inputs are wall-clock times in the displayed scope timezone. UTC here
      // preserves those components during formatting, regardless of device zone.
      const date = field.value ? new Date(field.value + 'Z') : null;
      value.textContent = date && !Number.isNaN(date.getTime())
        ? new Intl.DateTimeFormat(english() ? 'en-GB' : 'th-TH', {dateStyle:'medium',timeStyle:'short',timeZone:'UTC',hourCycle:'h23'}).format(date)
        : words('ยังไม่ระบุ', 'Not set');
      item.append(label, value); preview.append(item);
    }
  }
  function init() { examples(); dates(); }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-example-target]');
    if (!button) return;
    const field = document.getElementById(button.dataset.exampleTarget);
    if (!field || field.value.trim()) return;
    field.value = button.dataset.example;
    field.dispatchEvent(new Event('input', {bubbles:true}));
    field.focus();
    const feedback = document.querySelector('[data-example-feedback]');
    if (feedback) feedback.textContent = words('เติมตัวอย่างแล้ว โปรดตรวจและปรับให้ตรงกับรอบของท่าน', 'Example added. Review and adapt it to your collection.');
  });
  document.addEventListener('input', event => {
    if (!event.target.closest('.nx-setup-form')) return;
    examples();
    if (['open_at','due_at','close_at','expires_at'].includes(event.target.name)) dates();
  });
  document.addEventListener('change', event => {
    if (event.target.closest('.nx-setup-form')) dates();
  });
  document.addEventListener('portal:updated', init);
  init();
})();
