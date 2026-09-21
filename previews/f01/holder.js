'use strict';
(()=>{
 const data=JSON.parse(document.getElementById('preview-data').textContent),$=id=>document.getElementById(id),client=new F01Transport.Client(data.runtime);
 let lang='th',result=null,svg='',state='idle',busy=false;
 const t=(th,en)=>lang==='th'?th:en;
 const attachment=F01ReceiptAttachment(data.runtime);$('holder-download').after(attachment);attachment.hidden=true;
 // Fragments are not sent in HTTP requests. Scrub before any verification call.
 const fragment=location.hash.slice(1);history.replaceState(null,'',location.pathname);
 if(F01Transport.tokenOK(fragment))$('holder-token').value=fragment;else if(client.token)$('holder-token').value=client.token;
 const messages={idle:['',''],checking:['กำลังตรวจหลักฐาน…','Checking receipt…'],issued:['พบหลักฐานที่บันทึกสำเร็จแล้ว','A committed receipt was found.'],not_confirmed:['ยังไม่พบหลักฐานที่ยืนยันแล้ว อาจกำลังบันทึกหรือยังไม่สำเร็จ โปรดตรวจอีกครั้ง ห้ามใช้สถานะนี้เป็นเหตุส่งคำตอบซ้ำ','No committed receipt found yet. The submission may still be pending or unsuccessful. Check again; this is not permission to resubmit.'],revoked:['หลักฐานถูกเพิกถอน','This receipt has been revoked.'],expired:['หลักฐานหมดอายุ','This receipt has expired.'],unavailable:['หลักฐานไม่พร้อมใช้งาน','This receipt is unavailable.'],error:['ยังตรวจไม่ได้ โปรดตรวจการเชื่อมต่อแล้วลองอีกครั้ง','Unable to check. Check your connection and retry.'],invalid:['กรุณาระบุรหัส NXR1- ตามหลักฐานให้ครบ','Enter the complete NXR1- code from your receipt.'],qr_error:['พบหลักฐานแล้ว แต่ยังโหลด QR ไม่ได้ กรุณาเก็บรหัสแล้วลองตรวจใหม่','Receipt found, but QR loading failed. Keep your code and check again.'],forgotten:['ล้างรหัสจากแท็บแล้ว ไฟล์ที่ดาวน์โหลดไว้ยังคงอยู่','Code cleared from this tab. Downloaded files remain.']};
 function localize(){document.documentElement.lang=lang;document.querySelectorAll('[data-th][data-en]').forEach(n=>n.textContent=n.dataset[lang]);for(const l of ['th','en'])$('holder-'+l).setAttribute('aria-pressed',String(lang===l));$('holder-status').textContent=(messages[state]||messages.error)[lang==='th'?0:1];$('holder-check').disabled=busy;$('holder-forget').disabled=busy;$('holder-token').disabled=busy;
  attachment.hidden=!result;attachment.elements.receipt_token.value=result?client.token:'';attachment.querySelector('button').textContent=t('ดาวน์โหลดไฟล์ SVG จากระบบ','Download SVG from server');
  if(result){$('holder-title').textContent=t(result.label_th,result.label_en);$('holder-meta').textContent=`${result.instrument} · ${result.reporting_year_be} BE / ${result.reporting_year_be-543} CE`;$('holder-code').textContent=client.token;$('holder-expiry').textContent=t('ใช้ได้ถึง: ','Expires: ')+result.expires_at.slice(0,10);$('holder-realm').textContent=result.realm==='test'?'TEST · NOT FOR LIVE CLAIMS':'PARTICIPATION';}
 }
 for(const l of ['th','en'])$('holder-'+l).addEventListener('click',()=>{lang=l;localize();});
 $('holder-check').addEventListener('click',async()=>{
  if(busy)return;const token=$('holder-token').value.trim();result=null;svg='';$('holder-result').hidden=true;$('holder-download').hidden=true;$('holder-qr').replaceChildren();
  if(!F01Transport.tokenOK(token)){state='invalid';localize();return;}
  busy=true;state='checking';client.token=token;localize();
  try{const r=await client.recover();state=r.status;if(r.status==='issued'){result=r;$('holder-result').hidden=false;try{F01Transport.remember(sessionStorage,token);}catch(_){}try{const qr=await client.post('qr',{receipt_token:token});svg=qr.svg;const image=new Image();image.alt='QR';image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);$('holder-qr').replaceChildren(image);$('holder-download').hidden=false;}catch(_){state='qr_error';}}}catch(_){state='error';}finally{busy=false;localize();}
 });
 $('holder-token').addEventListener('input',()=>{result=null;svg='';$('holder-result').hidden=true;$('holder-download').hidden=true;state='idle';localize();});
 $('holder-forget').addEventListener('click',()=>{try{sessionStorage.removeItem(F01Transport.KEY);}catch(_){}client.token=null;result=null;svg='';$('holder-token').value='';$('holder-result').hidden=true;$('holder-download').hidden=true;$('holder-qr').replaceChildren();state='forgotten';localize();});
 $('holder-download').addEventListener('click',async()=>{if(!result||!svg)return;$('holder-download').disabled=true;try{await F01ReceiptDownload(result,client.token,svg,lang);$('holder-status').textContent=t('สร้างไฟล์หลักฐานแล้ว ตรวจในรายการดาวน์โหลด','Receipt file prepared. Check your downloads.');}catch(_){state='error';localize();}finally{$('holder-download').disabled=false;}});
 localize();
})();
