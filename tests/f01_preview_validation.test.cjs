const test = require('node:test');
const assert = require('node:assert/strict');
const policy = require('../previews/f01/validation.js');
const choice = (id, rule={op:'in_group'}) => ({id, type:'single_choice', fixed:null, rule,
  options:[{value:'Y'},{value:'N'},{value:'unable_to_assess'},{value:'U'}]});
const text = (id, rule={op:'in_group'}) => ({id,type:'text',fixed:null,rule,options:[]});
const questions=[choice('F01-S01'),choice('F01-D01'),
  text('F01-D01-FIX',{op:'eq',question_id:'F01-D01',value:'Y'}),text('F01-O01')];
test('only suggestions are optional; hidden follow-ups and fixed context are excluded',()=>{
  const state=policy.inspect([...questions,{...choice('F01-P01'),fixed:'C1'}],new Map());
  assert.deepEqual(state.requiredMissing.map(q=>q.id),['F01-S01','F01-D01']);
  assert.deepEqual(state.optionalMissing.map(q=>q.id),['F01-O01']);
});
test('non-assessment is an explicit answer; no suggestions do not prevent completion',()=>{
  const state=policy.inspect(questions,new Map([['F01-S01','unable_to_assess'],['F01-D01','N']]));
  assert.equal(state.requiredMissing.length,0);
  assert.equal(state.optionalMissing.length,1);
});
test('visible follow-up text is mandatory and whitespace does not satisfy it',()=>{
  const answers=new Map([['F01-S01','Y'],['F01-D01','Y'],['F01-D01-FIX','  ']]);
  assert.deepEqual(policy.inspect(questions,answers).requiredMissing.map(q=>q.id),['F01-D01-FIX']);
  answers.set('F01-D01-FIX','ปรับปรุงการสื่อสาร');
  assert.equal(policy.inspect(questions,answers).requiredMissing.length,0);
  answers.set('F01-D01','N');answers.delete('F01-D01-FIX');
  assert.equal(policy.inspect(questions,answers).requiredMissing.length,0);
});
test('invalid values, overlong text and empty or repeated multiselect do not pass',()=>{
  const q={...choice('F01-C02'),type:'multi_choice'};
  for(const value of [[],['Y','Y'],['unlisted'],'Y'])assert.equal(policy.valid(q,value),false);
  assert.equal(policy.valid(q,['Y','N']),true);
  assert.equal(policy.valid(choice('F01-K01'),'unlisted'),false);
  assert.equal(policy.valid(choice('F01-K01'),'U'),true);
  assert.equal(policy.valid(text('F01-D01-FIX'),'ก'.repeat(501)),false);
});
test('clearing an answer invalidates a previously complete result on recheck',()=>{
  const answers=new Map([['F01-S01','Y'],['F01-D01','N']]);
  assert.equal(policy.inspect(questions,answers).requiredMissing.length,0);
  answers.delete('F01-S01');
  assert.equal(policy.inspect(questions,answers).requiredMissing[0].id,'F01-S01');
});
