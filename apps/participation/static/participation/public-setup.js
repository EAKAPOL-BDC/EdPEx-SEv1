document.addEventListener('DOMContentLoaded', () => {
  const group = document.getElementById('id_group_code');
  const programme = document.getElementById('id_programme_key');
  if (!group || !programme || programme.tagName !== 'SELECT') return;
  const originals = Array.from(programme.options, o => ({value:o.value, text:o.textContent}));
  function update() {
    const levels = {'C1':['bachelor'], 'C2.1':['master','doctoral'], 'C2.2':['doctoral']}[group.value] || [];
    const old = programme.value;
    programme.replaceChildren(...originals.filter(o => !o.value || levels.includes(o.value.split(':')[0])).map(o => new Option(o.text, o.value)));
    if (Array.from(programme.options).some(o => o.value === old)) programme.value = old;
    programme.required = levels.length > 0;
  }
  group.addEventListener('change', update); update();
});
