const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const source = fs.readFileSync(path.join(__dirname,'../apps/accounts/static/portal/usability.js'),'utf8');
function setup(body) {
  const dom = new JSDOM('<html lang="th"><body>'+body+'</body></html>',{runScripts:'outside-only',url:'https://example.test/'});
  dom.window.eval(source); return dom;
}
function unloading(w){const e=new w.Event('beforeunload',{cancelable:true});w.dispatchEvent(e);return e.defaultPrevented;}
test('unsaved POST data warns, canceled submits keep warning, successful submits clear it',async()=>{
  const d=setup('<main><form method="post"><input name="value"></form></main>');const w=d.window;const f=w.document.querySelector('form');
  assert.equal(unloading(w),false);
  w.document.querySelector('input').dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(unloading(w),true);
  const prevent=e=>e.preventDefault();f.addEventListener('submit',prevent);
  f.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await Promise.resolve();assert.equal(unloading(w),true);
  f.removeEventListener('submit',prevent);f.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await Promise.resolve();assert.equal(unloading(w),false);d.window.close();
});
test('GET filters never become unsaved answers; table is keyboard accessible',()=>{
  const d=setup('<main><form method="get"><input name="q"></form><div class="table-scroll"><table></table></div></main>');
  d.window.document.querySelector('input').dispatchEvent(new d.window.Event('change',{bubbles:true}));assert.equal(unloading(d.window),false);
  assert.equal(d.window.document.querySelector('.table-scroll').getAttribute('tabindex'),'0');d.window.close();
});
test('field errors link to focus; error summaries are not duplicated; Escape closes menu',()=>{
  const d=setup('<button data-menu-toggle aria-expanded="true">Menu</button><main class="workspace-shell menu-open"><form method="post"><label for="x">Name</label><input id="x" aria-invalid="true"><ul class="errorlist"><li>Required</li></ul></form></main>');
  const w=d.window;w.document.dispatchEvent(new w.Event('portal:updated'));assert.equal(w.document.querySelectorAll('.ui-error-summary').length,1);
  w.document.querySelector('.ui-error-summary a').click();assert.equal(w.document.activeElement.id,'x');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(w.document.querySelector('[data-menu-toggle]').getAttribute('aria-expanded'),'false');
  assert.equal(unloading(w),true);w.close();
});
