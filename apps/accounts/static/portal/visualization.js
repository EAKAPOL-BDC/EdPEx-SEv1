/* Native presentation controls. No data fetches, answer storage or analytics. */
(() => {
  'use strict';
  const root = document.querySelector('[data-viz-carousel]');
  if (!root) return;
  const slides = Array.from(root.querySelectorAll('[data-viz-slide]'));
  if (!slides.length) return;
  const controls = root.querySelector('[data-viz-controls]');
  const counter = root.querySelector('[data-viz-counter]');
  const play = root.querySelector('[data-viz-play]');
  const previous = root.querySelector('[data-viz-prev]');
  const next = root.querySelector('[data-viz-next]');
  const fullscreen = root.querySelector('[data-viz-fullscreen]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let index = 0;
  let timer = null;
  function show(nextIndex) {
    index = (nextIndex + slides.length) % slides.length;
    slides.forEach((slide, i) => { slide.hidden = i !== index; });
    counter.textContent = `${index + 1} / ${slides.length}`;
  }
  function pause() {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    play.textContent = play.dataset.play;
    play.setAttribute('aria-pressed', 'false');
    counter.setAttribute('aria-live', 'polite');
  }
  previous.addEventListener('click', () => { pause(); show(index - 1); });
  next.addEventListener('click', () => { pause(); show(index + 1); });
  play.addEventListener('click', () => {
    if (timer !== null) { pause(); return; }
    // Rotation starts only through an explicit user action, including when
    // reduced motion is preferred; no animated transitions are applied.
    timer = window.setInterval(() => show(index + 1), 15000);
    play.textContent = play.dataset.pause;
    play.setAttribute('aria-pressed', 'true');
    counter.setAttribute('aria-live', 'off');
  });
  root.addEventListener('focusin', event => {
    if (event.target !== play) pause();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  reducedMotion.addEventListener('change', pause);
  window.addEventListener('pagehide', pause);
  if (document.fullscreenEnabled && root.requestFullscreen) {
    fullscreen.hidden = false;
    fullscreen.addEventListener('click', async () => {
      pause();
      try {
        if (document.fullscreenElement === root) await document.exitFullscreen();
        else await root.requestFullscreen();
      } catch (_) {
        // Browser policy can deny fullscreen; normal presentation stays usable.
        fullscreen.hidden = true;
      }
    });
    document.addEventListener('fullscreenchange', () => {
      fullscreen.textContent = document.fullscreenElement === root ? fullscreen.dataset.close : fullscreen.dataset.open;
    });
  }
  [previous, next, play].forEach(button => { button.disabled = slides.length < 2; });
  show(0);
  controls.hidden = false;
})();
