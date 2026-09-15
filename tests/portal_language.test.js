// DOM boundary regression: run the production handler with repeated-name controls.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('language refresh preserves checkbox groups, radios, selections and inputs without restoring CSRF', async () => {
  const control = (name, type, value, checked = false) => ({name, type, value, checked});
  const select = values => ({name: 'choices', type: 'select-multiple', multiple: true,
    options: ['a', 'b', 'c'].map(value => ({value, selected: values.includes(value)})),
    get selectedOptions() { return this.options.filter(option => option.selected); }});
  function form(elements) {
    elements.namedItem = name => {
      const matching = elements.filter(e => e.name === name);
      return matching.length === 1 ? matching[0] : matching;
    };
    return {elements};
  }
  const oldForm = form([control('csrfmiddlewaretoken', 'hidden', 'old-csrf'),
    control('duties', 'textarea', 'Unsent duties'), control('expected_F06-K01', 'select-one', '4'),
    control('dimensions', 'checkbox', 'M1', true), control('dimensions', 'checkbox', 'M2', false),
    control('dimensions', 'checkbox', 'M3', true), control('scope', 'radio', 'one', false),
    control('scope', 'radio', 'two', true), control('password', 'password', 'not-persisted'), select(['a', 'c'])]);
  const newForm = form([control('csrfmiddlewaretoken', 'hidden', 'new-csrf'),
    control('duties', 'textarea', ''), control('expected_F06-K01', 'select-one', ''),
    control('dimensions', 'checkbox', 'M1', false), control('dimensions', 'checkbox', 'M2', true),
    control('dimensions', 'checkbox', 'M3', false), control('scope', 'radio', 'one', true),
    control('scope', 'radio', 'two', false), control('password', 'password', ''), select(['b'])]);
  let handler, forms = [oldForm], focused = false;
  const document = {documentElement: {lang: 'th'}, title: 'Old',
    addEventListener: (type, callback) => { handler = callback; },
    querySelectorAll: () => forms,
    querySelector: selector => ({replaceWith: () => { if (selector === 'main') forms = [newForm]; },
      focus: () => { focused = true; }}), dispatchEvent: () => {}};
  const next = {documentElement: {lang: 'en'}, title: 'English', querySelector: () => ({})};
  const posted = new Map();
  const requests = [];
  const context = {document, location: {href: '/workspace/example/assign/member/'}, Event: class {},
    DOMParser: class { parseFromString() { return next; } },
    FormData: class { set(key, value) { posted.set(key, value); } },
    fetch: async (url, options) => { requests.push([url, options]); return {ok: true, text: async () => '<html></html>'}; },
    alert: () => { throw new Error('Language change failed'); }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../apps/accounts/static/portal/language.js'), 'utf8'), context);
  let prevented = false;
  await handler({target: {matches: () => true, action: '/language/'}, submitter: {value: 'en'},
    preventDefault: () => { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(posted.get('language'), 'en');
  assert.equal(requests.length, 2);
  assert.equal(requests[0][1].credentials, 'same-origin');
  assert.equal(newForm.elements[0].value, 'new-csrf');
  assert.equal(newForm.elements[1].value, 'Unsent duties');
  assert.equal(newForm.elements[2].value, '4');
  assert.deepEqual(newForm.elements.slice(3, 6).map(e => [e.value, e.checked]), [['M1', true], ['M2', false], ['M3', true]]);
  assert.deepEqual(newForm.elements.slice(6, 8).map(e => e.checked), [false, true]);
  assert.equal(newForm.elements[8].value, 'not-persisted');
  assert.deepEqual(newForm.elements[9].selectedOptions.map(e => e.value), ['a', 'c']);
  assert.equal(document.documentElement.lang, 'en');
  assert.equal(focused, true);
});
