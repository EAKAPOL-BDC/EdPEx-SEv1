'use strict';
(()=>{
 const config=JSON.parse(document.getElementById('preview-data').textContent).runtime,$=id=>document.getElementById(id),codePattern=/^NXA1-[0-9a-f]{64}$/;
 let lang='th',state='idle',busy=false;
 const messages={idle:['',''],opening:['กำลังเปิดแบบประเมิน…','Opening your assessment…'],invalid:['กรุณาระบุรหัส NXA1- ให้ครบตามคำเชิญ','Enter the complete NXA1- invitation code.'],unavailable:['รหัสนี้ไม่พร้อมใช้ อาจใช้แล้ว หมดอายุ หรือรอบปิด กรุณาตรวจหลักฐานเดิมหรือติดต่อผู้จัดรอบ','This code is unavailable. It may be used, expired, or closed. Check an existing receipt or contact the collection organizer.'],network:['ยังเปิดไม่ได้ โปรดตรวจการเชื่อมต่อแล้วลองอีกครั้ง','Unable to open. Check your connection and retry.'],limited:['ลองหลายครั้งแล้ว กรุณารอ 10 นาที','Too many attempts. Please wait 10 minutes.']};
 const raw=location.hash.slice(1);history.replaceState(null,'',location.pathname);
 if(codePattern.test(raw))$('entry-code').value=raw;
 function render(){document.documentElement.lang=lang;document.querySelectorAll('[data-th][data-en]').forEach(n=>n.textContent=n.dataset[lang]);for(const l of ['th','en'])$('entry-'+l).setAttribute('aria-pressed',String(lang===l));$('entry-status').textContent=messages[state][lang==='th'?0:1];$('entry-start').disabled=busy;$('entry-code').disabled=busy;}
 for(const l of ['th','en'])$('entry-'+l).addEventListener('click',()=>{lang=l;render();});
 $('entry-code').addEventListener('input',()=>{state='idle';render();});
 $('entry-start').addEventListener('click',async()=>{
  if(busy)return;const code=$('entry-code').value.trim();if(!codePattern.test(code)){state='invalid';render();return;}
  busy=true;state='opening';render();const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
  try{const response=await fetch(config.enter,{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'Content-Type':'application/json','X-CSRFToken':config.csrf},body:JSON.stringify({invitation_code:code}),signal:controller.signal});
   if(response.ok){const result=await response.json();if(result.next!=='/survey/participation/form/')throw Error('unexpected_destination');$('entry-code').value='';location.replace(result.next+(lang==='en'?'?lang=en':''));return;}
   state=response.status===429?'limited':response.status>=500?'network':'unavailable';
  }catch(_){state='network';}finally{clearTimeout(timeout);busy=false;render();}
 });render();
})();
