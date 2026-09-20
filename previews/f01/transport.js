/* Same-origin submission transport. No answers or session IDs in browser storage. */
'use strict';
const F01Transport = (() => {
 const KEY='nexora.participation.recovery.v1', MAX_AGE=24*60*60*1000;
 const tokenOK=value=>typeof value==='string'&&/^NXR1-[0-9a-f]{64}$/.test(value);
 function read(storage,now=Date.now()){
  try{const v=JSON.parse(storage.getItem(KEY));if(v&&tokenOK(v.token)&&Number.isFinite(v.at)&&now-v.at>=0&&now-v.at<MAX_AGE)return v.token;storage.removeItem(KEY);}catch(_){}return null;
 }
 function remember(storage,token){if(!tokenOK(token))throw new Error('invalid_receipt');storage.setItem(KEY,JSON.stringify({token,at:Date.now()}));if(read(storage)!==token)throw new Error('recovery_storage_unavailable');}
 function browserStorage(){try{return sessionStorage;}catch(_){return {getItem:()=>null,removeItem:()=>{},setItem:()=>{throw new Error('recovery_storage_unavailable');}};}}
 function envelope(questions,answers){
  const result={};
  for(const q of questions){
   if(q.fixed||!F01Validation.visible(q,answers))continue;
   const value=answers.get(q.id);if(value===undefined||value==='')continue;
   if(q.type==='multi_choice'||q.type==='text'){result[q.id]={status:'answered',value};continue;}
   const option=q.options.find(o=>o.value===value);if(!option)throw new Error('invalid_answer');
   result[q.id]=option.status==='answered'?{status:'answered',value:q.type==='integer_scale'?Number(value):value}:{status:option.status};
  }return result;
 }
 class Client {
  constructor(config,{fetcher=fetch,storage=browserStorage()}={}){this.config=config;this.fetcher=fetcher;this.storage=storage;this.token=read(storage);this.state=this.token?'uncertain':'editing';this.receipt=null;}
  async post(endpoint,data){
   const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
   try{
    // Native browser fetch must not receive this Client instance as its receiver.
    const fetcher=this.fetcher;
    const response=await fetcher(this.config[endpoint],{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'Content-Type':'application/json','X-CSRFToken':this.config.csrf},body:JSON.stringify(data),signal:controller.signal});
    const result=await response.json();if(!response.ok){const error=new Error(result.error||'request_failed');error.status=response.status;error.details=result;throw error;}return result;
   }finally{clearTimeout(timeout);}
  }
  async submit(answers){
   if(this.state!=='editing')throw new Error('check_status_first');
   this.state='preparing';let candidate;
   try{candidate=await this.post('prepare',{});if(!tokenOK(candidate.receipt_token)||candidate.status!=='prepared'||typeof candidate.issuance_ticket!=='string')throw new Error('invalid_candidate');remember(this.storage,candidate.receipt_token);this.token=candidate.receipt_token;}
   catch(e){this.state='editing';throw e;}
   this.state='submitting';
   try{
    const result=await this.post('submit',{answers,revision:this.config.revision,issuance_ticket:candidate.issuance_ticket,confirmed:true});
    if(result.status!=='issued')throw new Error('unknown_result');
    this.receipt=result;this.state='issued';return result;
   }catch(e){
    // Only explicit pre-commit validation rejections make editing safe. A lost,
    // malformed or timed-out acknowledgement never authorizes a second submit.
    if(e.status===422&&['required_answers_missing','invalid_answers_or_context','invalid_ticket'].includes(e.message)){
     try{this.storage.removeItem(KEY);}catch(_){}this.token=null;this.state='editing';
    }else{this.state='uncertain';}throw e;
   }
  }
  async recover(){
   if(!this.token)throw new Error('receipt_required');
   const result=await this.post('status',{receipt_token:this.token});
   if(result.status==='issued'){this.state='issued';this.receipt=result;}else this.state='uncertain';return result;
  }
 }
 return {Client,envelope,read,remember,tokenOK,KEY};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=F01Transport;
