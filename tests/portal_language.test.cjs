const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/accounts/static/portal/language.js', 'utf8');

function harness(marker = '', fail = false) {
  let handler;
  const changed = [], alerts = [], requests = [];
  const previewToken = {name:'preview',type:'hidden',value:'signed-cutoff-and-source'};
  const reason = {name:'reason',type:'textarea',value:'Retain my explanation'};
  const ack = {name:'confirm',type:'checkbox',value:'on',checked:true};
  const oldForm = {elements:[reason,ack,previewToken]};
  const newForm = {elements:[{...reason,value:''},{...ack,checked:false}]};
  let mainReplaced = false;
  const regions = Object.fromEntries(['body > header','body > main','body > footer'].map(key => [key,{
    replaceWith(){changed.push(key);if(key==='body > main')mainReplaced=true;}
  }]));
  const document = {
    documentElement:{lang:'th'}, title:'Result preview',
    addEventListener(name,fn){handler=fn;}, dispatchEvent(){},
    querySelectorAll(){return [mainReplaced?newForm:oldForm];},
    querySelector(selector){
      if(selector.includes('[data-confirmation-review]'))return marker && selector.includes(marker) ? {} : null;
      if(selector.includes('[data-language-form] button'))return {focus(){}};
      return regions[selector] || null;
    },
  };
  const next = {documentElement:{lang:'en'},title:'Prepare results',querySelector:s=>({region:s})};
  vm.runInNewContext(source,{
    document,location:{href:'http://localhost/workspace/test/calculate/'},
    FormData:class{set(){}},Event:class{},DOMParser:class{parseFromString(){return next;}},
    fetch:async(url,options)=>{requests.push({url,method:options.method||'GET'});return {ok:!fail,text:async()=>'<form>blank GET form</form>'};},
    alert:message=>alerts.push(message),
  });
  return {document,oldForm,newForm,changed,alerts,requests,run:()=>handler({
    target:{matches:()=>true,action:'/i18n/setlang/'},submitter:{value:'en'},preventDefault(){}
  })};
}

for(const marker of ['[data-calculation-preview]','[data-confirmation-review]']) {
  test(`${marker}: language switch preserves signed POST, acknowledgement and action`, async()=>{
    const h=harness(marker);await h.run();
    assert.equal(h.document.documentElement.lang,'en');
    assert.deepEqual(h.changed,['body > header','body > footer']);
    assert.equal(h.oldForm.elements.find(x=>x.name==='preview').value,'signed-cutoff-and-source');
    assert.equal(h.oldForm.elements.find(x=>x.name==='confirm').checked,true);
    assert.equal(h.oldForm.elements.find(x=>x.name==='reason').value,'Retain my explanation');
    assert.deepEqual(h.requests.map(x=>x.method),['POST','GET']);
    assert.equal(h.alerts.length,0);
  });
}
test('ordinary GET form still translates and restores entered fields',async()=>{
  const h=harness();await h.run();
  assert.ok(h.changed.includes('body > main'));
  assert.equal(h.newForm.elements[0].value,'Retain my explanation');
  assert.equal(h.newForm.elements[1].checked,true);
});
test('language request failure preserves the preview and shows retry guidance',async()=>{
  const h=harness('[data-calculation-preview]',true);await h.run();
  assert.deepEqual(h.changed,[]);
  assert.equal(h.document.documentElement.lang,'th');
  assert.equal(h.alerts.length,1);
});
