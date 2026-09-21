'use strict';
document.querySelector('[data-print-batch]')?.addEventListener('click',()=>window.print());
// The portal's shared interactions.js owns submit locking and pageshow recovery.
// The server independently rejects stale/replayed batch requests under a DB lock.
