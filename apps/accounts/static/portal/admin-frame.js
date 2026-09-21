/* Reserve the measured footer height without changing native admin scrolling. */
(() => {
  const footer = document.querySelector('body.nx-admin-frame:not(.popup) #footer');
  if (!footer || !window.ResizeObserver) return;
  const update = () => {
    document.body.style.setProperty('--nx-footer-height', `${Math.ceil(footer.getBoundingClientRect().height)}px`);
  };
  update();
  document.body.setAttribute('data-footer-ready', '');
  const observer = new ResizeObserver(update);
  observer.observe(footer);
  window.addEventListener('pageshow', update);
})();
