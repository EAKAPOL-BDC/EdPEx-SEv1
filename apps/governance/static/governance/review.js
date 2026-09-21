(() => {
  function init() {
    const root = document.querySelector('[data-confirmation-review]');
    if (root) {
      const english = document.documentElement.lang === 'en';
      root.querySelector('.review-jump').setAttribute('aria-label', english ? 'Review sections' : 'หมวดข้อมูลที่ตรวจ');
      document.title = english ? 'NEXORA · Review before confirming' : 'NEXORA · ตรวจรายการก่อนยืนยัน';
    }
    if (!root || root.dataset.reviewBound) return;
    root.dataset.reviewBound = 'true';
    const form = root.querySelector('[data-review-form]');
    const ack = form.elements.operation_ack;
    const button = root.querySelector('[data-review-confirm]');
    const timer = root.querySelector('[data-review-countdown]');
    const end = Date.parse(root.dataset.expiresAt);
    function update() {
      const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      const expired = Number.isFinite(end) && remaining === 0;
      button.disabled = !ack.checked || expired || form.getAttribute('aria-busy') === 'true';
      root.querySelector('[data-review-hint]').hidden = ack.checked || expired;
      root.querySelector('[data-review-expired]').hidden = !expired;
      timer.hidden = !Number.isFinite(end);
      timer.textContent = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
      return expired;
    }
    ack.addEventListener('change', update);
    form.addEventListener('submit', event => {
      if (event.submitter?.name === 'operation_edit') return;
      if (update() || !ack.checked) event.preventDefault();
    });
    update();
    const interval = setInterval(() => {
      if (!root.isConnected || update()) clearInterval(interval);
    }, 1000);
    window.addEventListener('pageshow', update);
  }
  init(); document.addEventListener('portal:updated', init);
})();
