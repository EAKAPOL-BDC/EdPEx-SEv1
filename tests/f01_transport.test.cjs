const test=require('node:test'),assert=require('node:assert/strict');
global.F01Validation=require('../previews/f01/validation.js');
const T=require('../previews/f01/transport.js');
const token='NXR1-'+'a'.repeat(64),config={prepare:'/prepare',submit:'/submit',status:'/status',csrf:'test',revision:0};
const storage=()=>{const values=new Map();return{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}};
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
test('fetch is called without binding a client object as its native receiver',async()=>{
 const c=new T.Client(config,{storage:storage(),fetcher:async function(){'use strict';assert.equal(this,undefined);return response({status:'not_confirmed'});}});
 await c.post('status',{receipt_token:token});
});
test('lost acknowledgement retains token without answers and never repeats submit',async()=>{
 const saved=storage(),calls=[];const client=new T.Client(config,{storage:saved,fetcher:async(url,opts)=>{calls.push(url);if(url==='/prepare')return response({status:'prepared',receipt_token:token,issuance_ticket:'signed'});if(url==='/submit')throw Error('offline');return response({status:'issued',realm:'test'});}});
 await assert.rejects(client.submit({'F01-O01':{status:'answered',value:'PRIVATE TEXT'}}));assert.equal(client.state,'uncertain');assert.equal(T.read(saved),token);assert.ok(!saved.getItem(T.KEY).includes('PRIVATE'));await assert.rejects(client.submit({}));assert.equal(calls.filter(x=>x==='/submit').length,1);await client.recover();assert.equal(client.state,'issued');
});
test('not confirmed never permits resubmission; reload retains recovery',async()=>{
 const saved=storage();T.remember(saved,token);const client=new T.Client(config,{storage:saved,fetcher:async()=>response({status:'not_confirmed'})});await client.recover();assert.equal(client.state,'uncertain');await assert.rejects(client.submit({}));
});
test('validation rejection permits correction; storage denied prevents submission',async()=>{
 const saved=storage();let sends=0;const fetcher=async url=>url==='/prepare'?response({status:'prepared',receipt_token:token,issuance_ticket:'signed'}):(sends++,response({error:'required_answers_missing'},422));const c=new T.Client(config,{storage:saved,fetcher});await assert.rejects(c.submit({}));assert.equal(c.state,'editing');assert.equal(T.read(saved),null);
 const denied={getItem:()=>null,removeItem:()=>{},setItem:()=>{throw Error('denied')}};const d=new T.Client(config,{storage:denied,fetcher});await assert.rejects(d.submit({}));assert.equal(sends,1);assert.equal(d.state,'editing');
});
test('double click makes one submit and issued result disables future submits',async()=>{
 let count=0;const c=new T.Client(config,{storage:storage(),fetcher:async url=>{if(url==='/prepare')return response({status:'prepared',receipt_token:token,issuance_ticket:'signed'});count++;return response({status:'issued',realm:'test'},201)}});const first=c.submit({});await assert.rejects(c.submit({}));await first;assert.equal(count,1);await assert.rejects(c.submit({}));
});
test('payload uses statuses and omits hidden branches and fixed context',()=>{
 const qs=[{id:'F01-S01',type:'integer_scale',rule:{op:'in_group'},options:[{value:'4',status:'answered'},{value:'NA',status:'not_applicable'}]}, {id:'F01-D01-FIX',type:'text',rule:{op:'eq',question_id:'F01-D01',value:'Y'},options:[]}];
 assert.deepEqual(T.envelope(qs,new Map([['F01-S01','4'],['F01-D01-FIX','hidden']])),{'F01-S01':{status:'answered',value:4}});assert.deepEqual(T.envelope(qs,new Map([['F01-S01','NA']])),{'F01-S01':{status:'not_applicable'}});
});
test('recovery token expires and invalid stored content is ignored',()=>{
 const saved=storage();saved.setItem(T.KEY,JSON.stringify({token,at:0}));assert.equal(T.read(saved,86400001),null);saved.setItem(T.KEY,'not json');assert.equal(T.read(saved),null);
});
