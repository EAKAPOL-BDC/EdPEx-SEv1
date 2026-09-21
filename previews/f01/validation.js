/* F01 preview policy: only section O (suggestions) is optional. */
const F01Validation = (() => {
  const section = q => q.id.split('-')[1][0];
  const visible = (q, answers) => q.rule.op !== 'eq' || answers.get(q.rule.question_id) === q.rule.value;
  const required = q => !q.fixed && section(q) !== 'O';
  function valid(q, value) {
    if (q.fixed) return true;
    if (q.type === 'text') return typeof value === 'string' && value.trim().length > 0 && value.length <= 500;
    const options = new Set(q.options.map(option => option.value));
    if (q.type === 'multi_choice') return Array.isArray(value) && value.length > 0 &&
      new Set(value).size === value.length && value.every(item => options.has(item));
    return typeof value === 'string' && options.has(value);
  }
  function inspect(questions, answers) {
    const active = questions.filter(q => !q.fixed && visible(q, answers));
    const missing = active.filter(q => !valid(q, answers.get(q.id)));
    return {active, done: active.length - missing.length,
      requiredMissing: missing.filter(required), optionalMissing: missing.filter(q => !required(q))};
  }
  return {visible, required, valid, inspect};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = F01Validation;
