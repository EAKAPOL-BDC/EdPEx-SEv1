(() => {'use strict';
function init(){const root=document.querySelector('.nx-operating-guide');if(!root||root.dataset.ready)return;root.dataset.ready='true';
const chapters=[...root.querySelectorAll('[data-guide-chapter]')],search=root.querySelector('#guide-search');
search.addEventListener('input',()=>{const value=search.value.trim().toLocaleLowerCase();let count=0;chapters.forEach(c=>{const visible=c.textContent.toLocaleLowerCase().includes(value);c.hidden=!visible;if(value&&visible)c.open=true;root.querySelector(`[data-guide-nav="${c.id}"]`).hidden=!visible;if(visible)count++;});root.querySelector('#guide-search-status').textContent=`${count} / ${chapters.length}`;});
root.querySelector('[data-guide-expand]').addEventListener('click',()=>{chapters.forEach(c=>{if(!c.hidden)c.open=true;});});
root.querySelector('[data-guide-print]').addEventListener('click',()=>{chapters.forEach(c=>{c.hidden=false;c.open=true;});search.value='';window.print();});
root.querySelectorAll('[data-guide-nav]').forEach(a=>a.addEventListener('click',()=>{document.getElementById(a.dataset.guideNav).open=true;}));}
document.addEventListener('portal:updated',init);init();})();
