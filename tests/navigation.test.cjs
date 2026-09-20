const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const source = name => fs.readFileSync(path.join(__dirname,'../apps/accounts/static/portal/',name),'utf8');
const fixture = () => `<header class="site-header"><a href="/">Brand</a></header>
<main class="workspace-shell"><div class="mobile-menu-bar"><button data-menu-toggle aria-expanded="false">Menu</button></div><button data-menu-close class="sidebar-backdrop" hidden></button>
<aside id="workspace-navigation"><button data-menu-close>Close</button><nav><a id="home" href="/workspace/">Home</a><details data-nav-group="forms" open><summary>Forms</summary><a id="current" aria-current="page" href="/forms/">Forms</a></details><details data-nav-group="admin"><summary>Admin</summary><a id="collapsed" href="/admin/">Hidden link</a></details><a id="last" href="#manuals">Manuals</a></nav></aside>
<div class="workspace-body"><form method="post"><input name="answer" value="Draft answer"></form></div></main><footer class="nx-footer">Credit</footer>`;
function setup(small = true) {
  const dom = new JSDOM('<html lang="th"><body>'+fixture()+'</body></html>',{runScripts:'outside-only',url:'https://example.test/workspace/'});
  let resize;const media={matches:small,addEventListener:(type,fn)=>{resize=fn;}};
  dom.window.matchMedia=()=>media;
  // Load the same ordered scripts as the live page: no duplicate menu handlers.
  for (const name of ['workspace.js','usability.js','navigation.js']) dom.window.eval(source(name));
  return {dom,w:dom.window,d:dom.window.document,resize:value=>{media.matches=value;resize();}};
}
test('mobile menu traps keyboard focus and Escape restores the page without changing a draft',()=>{
  const {w,d}=setup();const toggle=d.querySelector('[data-menu-toggle]');const side=d.querySelector('aside');
  assert.equal(side.inert,true);toggle.click();assert.equal(toggle.getAttribute('aria-expanded'),'true');
  assert.equal(side.getAttribute('role'),'dialog');assert.equal(d.querySelector('.workspace-body').inert,true);
  assert.equal(d.querySelector('footer').inert,true);assert.equal(d.activeElement,side.querySelector('button'));
  d.querySelector('#last').focus();d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
  assert.equal(d.activeElement,side.querySelector('button'));
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));assert.equal(d.activeElement.id,'last');
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  assert.equal(toggle.getAttribute('aria-expanded'),'false');assert.equal(d.activeElement,toggle);
  assert.equal(d.querySelector('.workspace-body').inert,false);assert.equal(side.inert,true);assert.equal(side.hasAttribute('aria-modal'),false);
  assert.equal(d.querySelector('[name=answer]').value,'Draft answer');w.close();
});
test('viewport changes restore desktop navigation and remove modal state',()=>{
  const {w,d,resize}=setup(false);assert.equal(d.querySelector('aside').inert,false);
  d.querySelector('#current').focus();resize(true);assert.equal(d.activeElement,d.querySelector('[data-menu-toggle]'));
  d.querySelector('[data-menu-toggle]').click();resize(false);
  assert.equal(d.querySelector('aside').inert,false);assert.equal(d.querySelector('header').inert,false);
  assert.equal(d.querySelector('.sidebar-backdrop').hidden,true);assert.equal(d.activeElement.id,'current');
  assert.equal(d.querySelector('aside').hasAttribute('aria-hidden'),false);w.close();
});
test('backdrop, close button and content replacement keep navigation operable',()=>{
  const {w,d}=setup();d.querySelector('[data-menu-toggle]').click();d.querySelector('.sidebar-backdrop').click();
  assert.equal(d.querySelector('[data-menu-toggle]').getAttribute('aria-expanded'),'false');
  d.body.innerHTML=fixture();d.dispatchEvent(new w.Event('portal:updated'));
  d.querySelector('[data-menu-toggle]').click();d.querySelector('aside [data-menu-close]').click();
  assert.equal(d.querySelector('[data-menu-toggle]').getAttribute('aria-expanded'),'false');
  assert.equal(d.querySelector('.workspace-body').inert,false);
  d.querySelector('[data-menu-toggle]').click();const link=d.querySelector('#last');link.addEventListener('click',event=>event.preventDefault());link.click();
  assert.equal(d.activeElement,d.querySelector('[data-menu-toggle]'));assert.equal(d.querySelector('[data-menu-toggle]').getAttribute('aria-expanded'),'false');w.close();
});
test('language refresh replaces the outer footer, preserves the document footer and scroll position',async()=>{
  const html=lang=>`<html lang="${lang}"><head><title>${lang}</title></head><body><header><form data-language-form method="post" action="/language/"><button value="en">EN</button></form></header><main><div class="workspace-body"><form method="post"><input name="answer" value="${lang}"></form><footer class="manual-document-footer">Manual ${lang}</footer></div></main><footer class="nx-footer">Credit ${lang}</footer></body></html>`;
  const dom=new JSDOM(html('th'),{runScripts:'outside-only',url:'https://example.test/manuals/'});const w=dom.window,d=w.document;
  d.querySelector('[name=answer]').value='unsent';d.querySelector('.workspace-body').scrollTop=350;
  w.fetch=async()=>({ok:true,text:async()=>html('en')});let failed=false;w.alert=()=>{failed=true;};w.eval(source('language.js'));
  const form=d.querySelector('[data-language-form]');form.dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector('button')}));
  await new Promise(resolve=>setTimeout(resolve,0));assert.equal(failed,false);
  assert.equal(d.querySelector('body > footer').textContent,'Credit en');assert.equal(d.querySelector('.manual-document-footer').textContent,'Manual en');
  assert.equal(d.querySelectorAll('.nx-footer').length,1);assert.equal(d.querySelector('[name=answer]').value,'unsent');
  assert.equal(d.querySelector('.workspace-body').scrollTop,350);w.close();
});
test('native admin reserves the footer measured height and updates after wrapping',()=>{
  const dom=new JSDOM('<body class="nx-admin-frame"><div id="container"><footer id="footer">Credit</footer></div></body>',{runScripts:'outside-only'});
  const w=dom.window;let update, height=68;w.ResizeObserver=class{constructor(fn){update=fn;}observe(){}};
  w.document.querySelector('footer').getBoundingClientRect=()=>({height});w.eval(source('admin-frame.js'));
  assert.equal(w.document.body.style.getPropertyValue('--nx-footer-height'),'68px');
  height=111.5;update();assert.equal(w.document.body.style.getPropertyValue('--nx-footer-height'),'112px');
  assert.equal(w.document.body.hasAttribute('data-footer-ready'),true);w.close();
});
