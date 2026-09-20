'use strict';
const F01Connected=(()=>{
 function create(data,{language,onIssued}){
  if(!data.runtime)return null;
  const $=id=>document.getElementById(id),t=(th,en)=>language()==='th'?th:en;
  const client=new F01Transport.Client(data.runtime);
  const replacements={
   'ต้นแบบ · ไม่บันทึก':['ทดสอบการบันทึก','Test collection'],
   'ปีการศึกษา 2568 · ตัวอย่าง':[`ปีการศึกษา ${data.reporting_year} · ทดสอบ`,`Academic year ${data.reporting_year-543} · test`],
   'พื้นที่ทดลอง · คำตอบอยู่เฉพาะหน้านี้':['พื้นที่ทดสอบการบันทึก · ใช้ข้อมูลสมมุติเท่านั้น','Test collection · synthetic answers only'],
   'ไม่ส่งหรือบันทึกคำตอบ โหลดหน้าใหม่แล้วข้อมูลจะหาย รหัสและ QR เป็นตัวอย่าง ใช้รับสิทธิ์จริงไม่ได้':['คำตอบจะบันทึกในฐานพัฒนาเมื่อยืนยัน รหัสทดสอบใช้รับชั่วโมงหรือรางวัลจริงไม่ได้ เก็บรหัสกู้ผลในแท็บนี้ไม่เกิน 24 ชั่วโมง; คำตอบที่ยังไม่ส่งจะหายเมื่อโหลดใหม่','Confirmation saves answers to the development database. Test receipts cannot earn credits or prizes. A recovery token stays in this tab for up to 24 hours; unsent answers are lost on reload.'],
   'ภาษาอังกฤษในต้นแบบเป็นร่างสำหรับตรวจทานก่อนใช้จริง':['รอบทดสอบใช้คำถามและคำแปลจากรุ่นที่ตรึงไว้ในฐานพัฒนา โปรดใช้ข้อมูลสมมุติ','This test uses wording pinned in the development database. Use synthetic answers only.'],
   'ไม่ระบุชื่อ รหัส อีเมล เบอร์โทร หรือรายละเอียดที่บอกว่าเป็นใคร รหัสเข้าร่วมที่เสนอจะไม่เปิดเผยคำตอบหรือคะแนนแก่ผู้ตรวจสิทธิ์':['ไม่ระบุชื่อ รหัส อีเมล เบอร์โทร หรือข้อมูลที่บอกตัวตนในคำตอบ หลักฐานไม่แสดงคำตอบหรือคะแนน การแยกทะเบียนคำเชิญออกจากตัวบุคคลยังอยู่ระหว่างพัฒนา','Keep identifying details out of answers. Receipts contain no answers or scores. Separation of invitation records from identity is still under development.'],
   'ระบบตรวจความครบถ้วนก่อนแสดงหลักฐานตัวอย่าง':['ตรวจครบก่อนบันทึกและออกหลักฐานการเข้าร่วม','Check completeness before saving and issuing a receipt.'],
   'จบการทดลอง':['บันทึกสำเร็จแล้ว','SAVED SUCCESSFULLY'],
   'ตอบข้อบังคับครบแล้ว คำตอบไม่ได้ถูกส่งหรือบันทึก':['คำตอบและหลักฐานบันทึกสำเร็จในฐานพัฒนาแล้ว เก็บหลักฐานไว้กับท่าน','Your answers and receipt have been saved in the development database. Keep your receipt private.'],
   'หลักฐานการเข้าร่วมตัวอย่าง':['หลักฐานการเข้าร่วม · ทดสอบ','Participation receipt · test'],
   'รหัสตัวอย่าง (ใช้ซ้ำในการสาธิต)':['รหัสอ้างอิงการเข้าร่วม · เก็บเป็นความลับ','Participation reference · keep private'],
   'QR มีเพียงข้อมูลหลักฐานตัวอย่าง ไม่มีคำตอบหรือคะแนน ไม่ใช่ลิงก์ตรวจสิทธิ์จริง':['QR เปิดหน้าตรวจสถานะหลักฐาน ไม่มีคำตอบหรือคะแนน อุปกรณ์ที่สแกนต้องเข้าถึงที่อยู่ของระบบทดสอบได้','The QR opens receipt verification without answers or scores. The scanning device must have access to the preview server address.'],
   'เป็นแนวทางออกแบบ ยังไม่มีบริการบันทึก ตรวจสิทธิ์ หรือจับรางวัลในต้นแบบนี้ อย่าเผยแพร่หลักฐานจริงให้ผู้อื่น':['รหัสนี้มีผลเฉพาะฐานทดสอบ ระบบภาระงานและการให้รางวัลจริงยังไม่ได้เชื่อมต่อ อย่าเผยแพร่หลักฐานให้ผู้อื่น','This receipt is valid only in the test database. Live workload and prize services are not connected. Do not share your receipt.'],
   'ต้นแบบ F01 · รุ่น 03':['F01 · ทดสอบการเชื่อมต่อ 04','F01 · integration test 04'],
   'ต้นแบบ: ไม่ส่งหรือบันทึกคำตอบ หลักฐานไม่มีผลใช้สิทธิ์':['เมื่อยืนยันจะบันทึกคำตอบในฐานพัฒนา และไม่สามารถย้อนแก้ไขคำตอบที่ส่งแล้ว','Confirmation saves to the development database. Submitted answers cannot be edited.']
  };
  document.querySelectorAll('[data-th][data-en]').forEach(n=>{const pair=replacements[n.dataset.th];if(pair){n.dataset.th=pair[0];n.dataset.en=pair[1];}});
  if(data.runtime.unlinked){const notice=document.querySelector('.instruction-side p');notice.dataset.th='คำเชิญนี้ไม่บันทึกผู้รับรหัส ไม่ระบุชื่อ รหัสบุคคล หรือข้อมูลที่บอกตัวตนในคำตอบ หลักฐานไม่แสดงคำตอบหรือคะแนน ข้อมูลเวลาและโครงสร้างพื้นฐานยังอาจเชื่อมโยงเหตุการณ์ได้';notice.dataset.en='This invitation does not record its recipient. Keep names, personal IDs and identifying details out of answers. Receipts contain no answers or scores. Timing and infrastructure data may still correlate events.';}
  if(data.runtime.public){const step=document.querySelector('[data-en="Open your invitation"]');if(step){step.dataset.th='เลือกกลุ่มและแบบประเมิน';step.dataset.en='Choose group and assessment';}const notice=document.querySelector('.instruction-side p');notice.dataset.th='ไม่ต้องลงทะเบียนหรือรับคำเชิญ กรุณาไม่กรอกชื่อหรือข้อมูลที่ระบุตัวบุคคล หลักฐานยืนยันการส่งสำเร็จ ไม่ยืนยันตัวผู้ตอบ ผู้ตรวจภาระงานหรือรางวัลตรวจตัวบุคคลแยกภายหลัง';notice.dataset.en='No registration or invitation is required. Avoid names and identifying details. Proof confirms successful submission, not respondent identity. Workload or reward verifiers check identity separately.';const back=document.createElement('a');back.href='/survey/public/';back.className='secondary nx-action-link';back.dataset.th='เลือกแบบประเมินอื่น';back.dataset.en='Other assessments';back.textContent='เลือกแบบประเมินอื่น';document.querySelector('.receipt-actions').append(back);}
  if(data.runtime.public&&data.privacy){const privacy=document.createElement('p');privacy.className='preserve-lines';privacy.textContent=data.privacy;document.querySelector('.instruction-side').append(privacy);}
  const context=document.createElement('p');context.className='muted';document.querySelector('.meta').after(context);
  const panel=document.createElement('section');panel.className='connection-panel';panel.hidden=true;panel.tabIndex=-1;panel.setAttribute('aria-label','สถานะการบันทึก / Submission status');
  const message=document.createElement('p');message.setAttribute('role','status');message.setAttribute('aria-live','polite');
  const actions=document.createElement('div');actions.className='connection-actions';const recover=document.createElement('button');recover.type='button';recover.className='primary';const link=document.createElement('a');link.href=data.runtime.holder;actions.append(recover,link);panel.append(message,actions);document.querySelector('.workspace').before(panel);
  let error='',busy=false,svg='';
  const dynamic=(node,value)=>{node.removeAttribute('data-th');node.removeAttribute('data-en');node.textContent=value;};
  function localize(){
   context.textContent=t(data.context_th,data.context_en);
   recover.textContent=t('ตรวจผลการบันทึกอีกครั้ง','Check submission status');link.textContent=t('เปิดหน้าตรวจหลักฐาน','Open receipt verification');
   panel.hidden=client.state==='editing'&&!error||client.state==='issued'&&!error;
   document.body.classList.toggle('connected-locked',client.state!=='editing');
   recover.hidden=client.state!=='uncertain';recover.disabled=busy;
   $('finish').disabled=client.state!=='editing';
   const stateText={preparing:t('กำลังเตรียมการส่ง…','Preparing submission…'),submitting:t('กำลังบันทึก กรุณารอสักครู่…','Saving your answers. Please wait…'),uncertain:t('ยังยืนยันผลการบันทึกไม่ได้ โปรดตรวจผลอีกครั้ง ระบบจะไม่ส่งคำตอบซ้ำ','The submission is not yet confirmed. Check its status again. Your answers will not be resubmitted.')};
   message.textContent=error||stateText[client.state]||'';
   if(client.state==='issued'){
    const r=client.receipt;document.querySelector('.demo-stamp').textContent='TEST · NOT FOR LIVE CLAIMS';
    const info=document.querySelector('.receipt-info');dynamic(info.querySelector('h3'),t(r.label_th,r.label_en));
    const ps=info.querySelectorAll(':scope > p');dynamic(ps[0],r.instrument);dynamic(ps[1],t(`ปีการศึกษา ${r.reporting_year_be}`,`Academic year ${r.reporting_year_be-543}`));info.querySelector('code').textContent=client.token;
    $('back-review').hidden=true;
    const verify=$('verify-issued');if(verify)verify.textContent=t('ตรวจหลักฐาน / ดาวน์โหลดใหม่','Verify receipt / download again');
    const attachment=$('server-download');if(attachment)attachment.querySelector('button').textContent=t('ดาวน์โหลดไฟล์ SVG จากระบบ','Download SVG from server');
   }
  }
  async function issued(){
   error='';onIssued();localize();
   $('download-receipt').disabled=true;
   try{const result=await client.post('qr',{receipt_token:client.token});svg=result.svg;
    const image=new Image();image.alt=t('QR ตรวจสถานะหลักฐานทดสอบ','QR for test receipt verification');image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);$('receipt-qr').replaceChildren(image);$('download-receipt').disabled=false;
   }catch(_){$('download-status').textContent=t('บันทึกสำเร็จ แต่ยังโหลด QR ไม่ได้ กรุณาเก็บรหัสด้านบน หรือเปิดหน้าตรวจหลักฐาน','Saved, but the QR could not be loaded. Keep the code above or open receipt verification.');}
   let verify=$('verify-issued');if(!verify){verify=document.createElement('a');verify.id='verify-issued';document.querySelector('.receipt-actions').append(verify);}verify.href=data.runtime.holder+'#'+client.token;verify.textContent=t('ตรวจหลักฐาน / ดาวน์โหลดใหม่','Verify receipt / download again');
   if(!$('server-download')){const form=F01ReceiptAttachment(data.runtime);form.id='server-download';form.elements.receipt_token.value=client.token;form.querySelector('button').textContent=t('ดาวน์โหลดไฟล์ SVG จากระบบ','Download SVG from server');document.querySelector('.receipt-actions').append(form);}
  }
  async function submit(answers){
   if(client.state!=='editing')return;error='';busy=true;
   const pending=client.submit(F01Transport.envelope(data.questions,answers));localize();panel.focus();
   // prepare and submit remain serialized in Client; display both as busy.
   try{await pending;await issued();}
   catch(e){error=client.state==='editing'?t('ยังไม่บันทึก: กรุณาตรวจคำตอบหรือเปิดใช้พื้นที่เก็บข้อมูลของแท็บ แล้วลองยืนยันอีกครั้ง','Not saved: check your answers or enable tab storage, then confirm again'):'';if(e.details?.missing_question_ids)error=t('ยังไม่บันทึก ข้อที่ต้องตอบ: ','Not saved. Required items: ')+e.details.missing_question_ids.join(', ');}
   finally{busy=false;localize();}
  }
  recover.addEventListener('click',async()=>{busy=true;error='';localize();try{const r=await client.recover();if(r.status==='issued')await issued();else if(r.status!=='not_confirmed')error=t('หลักฐานไม่พร้อมใช้งาน: ','Receipt unavailable: ')+r.status;}catch(_){error=t('ยังติดต่อระบบไม่ได้ กรุณาตรวจการเชื่อมต่อแล้วตรวจผลอีกครั้ง','Unable to reach the service. Check your connection and try checking status again.');}finally{busy=false;localize();}});
  window.addEventListener('beforeunload',e=>{if(['preparing','submitting','uncertain'].includes(client.state)){e.preventDefault();e.returnValue='';}});
  async function download(){if(client.state!=='issued'||!svg)return;try{await F01ReceiptDownload(client.receipt,client.token,svg,language());$('download-status').textContent=t('สร้างไฟล์แล้ว ตรวจในรายการดาวน์โหลด','Receipt prepared. Check your downloads.');}catch(_){$('download-status').textContent=t('ดาวน์โหลดไม่สำเร็จ โปรดเก็บรหัสอ้างอิงด้านบน','Download failed. Please keep the reference above.');}}
  return {submit,localize,download,client};
 }
 return {create};
})();

function F01ReceiptAttachment(runtime){
 const form=document.createElement('form');form.method='POST';form.action=runtime.download;
 for(const [name,value] of [['csrfmiddlewaretoken',runtime.csrf],['receipt_token','']]){const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;form.append(input);}
 const button=document.createElement('button');button.type='submit';button.className='secondary';form.append(button);return form;
}

async function F01ReceiptDownload(receipt,token,svg,lang){
 const canvas=document.createElement('canvas');canvas.width=1400;canvas.height=900;const ctx=canvas.getContext('2d');
 ctx.fillStyle='#faf7fd';ctx.fillRect(0,0,1400,900);ctx.fillStyle='#fff';ctx.fillRect(35,35,1330,830);ctx.fillStyle='#49337f';ctx.font='bold 44px sans-serif';ctx.fillText('NEXORA',75,120);ctx.font='30px sans-serif';ctx.fillText(lang==='th'?'หลักฐานการเข้าร่วม · ทดสอบ':'Participation receipt · test',75,180);
 ctx.fillStyle='#94602b';ctx.font='bold 26px sans-serif';ctx.fillText('TEST · NOT FOR LIVE CLAIMS',75,240);ctx.fillStyle='#2c2539';ctx.font='24px sans-serif';ctx.fillText(`${receipt.instrument} · ${receipt.reporting_year_be} BE / ${receipt.reporting_year_be-543} CE`,75,310);
 const label=lang==='th'?receipt.label_th:receipt.label_en;ctx.fillText(label,75,355,790);ctx.font='20px monospace';ctx.fillText(token.slice(0,37),75,435);ctx.fillText(token.slice(37),75,470);ctx.font='22px sans-serif';ctx.fillText(lang==='th'?'เก็บรหัสเป็นความลับ ไม่มีคำตอบหรือคะแนนในหลักฐาน':'Keep this code private. No answers or scores included.',75,540,790);
 ctx.fillText(lang==='th'?'ลิงก์ทดสอบต้องใช้อุปกรณ์ที่เข้าถึงระบบนี้ได้':'Test link: requires access to this preview server.',75,585,790);ctx.font='20px sans-serif';ctx.fillText('School of Education University of Phayao',75,750);ctx.fillText('Expires: '+receipt.expires_at.slice(0,10),75,795);
 const img=new Image();img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);await img.decode();ctx.imageSmoothingEnabled=false;ctx.drawImage(img,920,270,360,360);
 const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(new Error('image_export_failed')),'image/png'));
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.download='NEXORA-TEST-receipt.png';a.href=url;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}
