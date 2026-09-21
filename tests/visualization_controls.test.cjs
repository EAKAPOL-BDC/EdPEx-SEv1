/* Unit checks for presentation behavior; these are not browser/layout tests. */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/accounts/static/portal/visualization.js'), 'utf8');

function fixture(count) {
  const events = new Map();
  const element = () => ({hidden:false, disabled:false, textContent:'', attributes:{},dataset:{play:'Play',pause:'Pause'},
    addEventListener(name, fn) { events.set(this.key+':'+name, fn); },
    setAttribute(key, value) { this.attributes[key]=value; }});
  const selectors=['controls','counter','play','prev','next','fullscreen'];
  const nodes=Object.fromEntries(selectors.map(key=>[key,Object.assign(element(),{key})]));
  const slides=Array.from({length:count},element);
  const root=Object.assign(element(),{key:'root',querySelectorAll:()=>slides,
    querySelector:selector=>nodes[selector.slice(10,-1)]});
  const document=Object.assign(element(),{key:'document',hidden:false,querySelector:()=>root,fullscreenEnabled:false});
  const motion=Object.assign(element(),{key:'motion',matches:true});
  let tick=null;
  const window=Object.assign(element(),{key:'window',matchMedia:()=>motion,
    setInterval(fn,delay){assert.equal(delay,15000);tick=fn;return 1;},clearInterval(){tick=null;}});
  vm.runInNewContext(source,{document,window});
  return {nodes,slides,document,run:()=>tick?.(),isPlaying:()=>tick!==null,
    event:(key,name,event={})=>events.get(key+':'+name)?.(event)};
}

test('manual navigation wraps; playback is opt-in and pauses for focus or hidden document',()=>{
  const f=fixture(3);
  assert.deepEqual(f.slides.map(s=>s.hidden),[false,true,true]);
  assert.equal(f.isPlaying(),false);
  f.event('prev','click');assert.equal(f.nodes.counter.textContent,'3 / 3');
  f.event('next','click');assert.equal(f.nodes.counter.textContent,'1 / 3');
  f.event('play','click');assert.equal(f.isPlaying(),true);
  assert.equal(f.nodes.counter.attributes['aria-live'],'off');
  f.run();assert.equal(f.nodes.counter.textContent,'2 / 3');
  f.event('root','focusin',{target:f.nodes.next});assert.equal(f.isPlaying(),false);
  f.event('play','click');f.document.hidden=true;f.event('document','visibilitychange');
  assert.equal(f.isPlaying(),false);assert.equal(f.nodes.play.attributes['aria-pressed'],'false');
  f.event('play','click');f.event('motion','change');assert.equal(f.isPlaying(),false);
});

test('one slide disables navigation and playback; no carousel leaves page untouched',()=>{
  const f=fixture(1);
  for(const key of ['prev','next','play'])assert.equal(f.nodes[key].disabled,true);
  assert.doesNotThrow(()=>vm.runInNewContext(source,{document:{querySelector:()=>null}}));
});
