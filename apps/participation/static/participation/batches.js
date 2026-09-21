(() => {'use strict';const form=document.getElementById('batch-form');if(!form)return;
const groups=[...form.querySelectorAll('[name="group_codes"]')],cards=[...form.querySelectorAll('[data-group]')];
function update(){const selected=new Set(groups.filter(x=>x.checked).map(x=>x.value));let count=0;
cards.forEach(card=>{const active=selected.has(card.dataset.group);card.hidden=!active;card.querySelectorAll('input,select').forEach(x=>{x.disabled=!active;if(active&&x.name.startsWith('count_')&&Number(x.value)>0)count++;});});
const en=document.documentElement.lang.startsWith('en');document.getElementById('batch-summary').textContent=en?`${selected.size} groups selected · ${count} counting contexts`:`เลือก ${selected.size} กลุ่ม · ระบุจำนวนแล้ว ${count} รายการ`;
}form.addEventListener('change',update);form.addEventListener('input',event=>{if(event.target.type==='number')update();});update();
})();
