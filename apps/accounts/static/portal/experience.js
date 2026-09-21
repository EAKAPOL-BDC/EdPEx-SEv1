/* No credential values are read, stored or sent by this presentation layer. */
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  const english = () => document.documentElement.lang === 'en';
  const label = (th, en) => english() ? en : th;
  const root = () => document.querySelector('.nx-experience');
  function motion() {
    const page = root(); if (!page) return;
    const off = paused || reduced.matches;
    page.dataset.motion = off ? 'off' : 'on';
    page.toggleAttribute('data-background', document.hidden);
    const button = page.querySelector('[data-motion-toggle]');
    if (button) {
      button.hidden = reduced.matches;
      button.setAttribute('aria-pressed', String(paused));
      button.textContent = paused ? label('เปิดการเคลื่อนไหว', 'Resume motion') : label('หยุดการเคลื่อนไหว', 'Pause motion');
    }
  }
  function selectStep(value) {
    const page = root(); if (!page) return;
    page.querySelectorAll('[data-workflow]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.workflow === value)));
    page.querySelectorAll('[data-workflow-panel]').forEach(panel => { panel.hidden = panel.dataset.workflowPanel !== value; });
  }
  function init() {
    motion(); selectStep('0');
    root()?.querySelectorAll('[data-password-toggle]').forEach(button => { button.hidden = false; });
  }
  function say(th, en) {
    const message = root()?.querySelector('[data-companion-message]');
    if (message) message.textContent = label(th, en);
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || !button.closest('.nx-experience')) return;
    if (button.matches('[data-motion-toggle]')) { paused = !paused; motion(); }
    if (button.matches('[data-workflow]')) selectStep(button.dataset.workflow);
    if (button.matches('[data-greet]')) {
      say('ยินดีต้อนรับครับ มาเริ่มต้นทีละขั้นตอนด้วยกัน', 'Welcome! Let’s take it one step at a time.');
      root().setAttribute('data-greeting', '');
    }
    if (button.matches('[data-password-toggle]')) {
      const input = document.getElementById(button.getAttribute('aria-controls'));
      if (!input || input.form !== button.form) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(show));
      button.textContent = show ? label('ซ่อนรหัสผ่าน', 'Hide password') : label('แสดงรหัสผ่าน', 'Show password');
    }
  });
  document.addEventListener('animationend', event => {
    if (event.animationName === 'nx-greet') root()?.removeAttribute('data-greeting');
  });
  document.addEventListener('focusin', event => {
    if (!event.target.closest('.nx-login')) return;
    const password = event.target.name === 'password';
    root()?.toggleAttribute('data-password-focus', password);
    if (password) say('กรอกรหัสผ่าน แล้วเลือกเข้าสู่ระบบเมื่อพร้อม', 'Enter your password, then sign in when ready.');
    else if (event.target.name === 'username') say('ใช้ชื่อผู้ใช้ที่ผู้ดูแลระบบจัดเตรียมให้ครับ', 'Use the username provided by your administrator.');
  });
  document.addEventListener('focusout', event => {
    if (event.target.name === 'password') root()?.removeAttribute('data-password-focus');
  });
  // Restore the native password type before language.js captures unsent fields.
  document.addEventListener('submit', event => {
    if (!event.target.matches('[data-language-form]')) return;
    root()?.querySelectorAll('[data-password-toggle]').forEach(button => {
      const input = document.getElementById(button.getAttribute('aria-controls'));
      if (input && input.form === button.form) input.type = 'password';
      button.setAttribute('aria-pressed', 'false');
      button.textContent = label('แสดงรหัสผ่าน', 'Show password');
    });
  }, true);
  document.addEventListener('visibilitychange', motion);
  reduced.addEventListener('change', motion);
  document.addEventListener('portal:updated', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
