const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const base = path.join(__dirname, '../../backend/app/static');
const tick = () => new Promise(resolve => setImmediate(resolve));
const unhandled = [];
process.on('unhandledRejection', error => unhandled.push(error));

(async () => {
  let checks = 0;
  for (const [formId, messageId] of [
    ['login-form', 'login-message'],
    ['request-reset-form', 'reset-message'],
    ['new-password-form', 'password-message'],
    ['bulk-form', 'bulk-message'],
  ]) {
    for (const failure of ['http', 'network']) {
      const dom = new JSDOM(fs.readFileSync(path.join(base, 'index.html'), 'utf8'), {
        url: 'https://example.test/', runScripts: 'outside-only',
      });
      const w = dom.window;
      const run = code => vm.runInContext(code, dom.getInternalVMContext());
      w.HTMLDialogElement.prototype.close = function () { this.open = false; };
      run(fs.readFileSync(path.join(base, 'hub-session.js'), 'utf8'));
      run(fs.readFileSync(path.join(base, 'app.js'), 'utf8').replace(/\ninitialise\(\);\s*$/, '\n'));
      run(`state.config = {supabase_url:'https://example.test', supabase_anon_key:'test'};
           state.session = {access_token:'test'};
           saveSession = () => {}; openDashboard = async () => {}; reloadDashboard = async () => {};`);
      for (const id of ['login-email', 'reset-email']) w.document.getElementById(id).value = 'test@example.test';
      for (const id of ['login-password', 'new-password', 'confirm-password']) w.document.getElementById(id).value = 'test-only-password';
      w.document.getElementById('bulk-total').value = '0';
      const form = w.document.getElementById(formId);
      const button = form.querySelector('button[type=submit]');
      const originalLabel = button.textContent;
      const errorText = failure === 'http' ? 'Request rejected' : 'Network connection lost';
      let calls = 0;
      w.fetch = async () => {
        calls++;
        if (failure === 'network') throw new Error(errorText);
        return {ok:false, status:formId === 'bulk-form' ? 400 : 401, json:async () => ({detail:errorText})};
      };
      const event = new w.Event('submit', {bubbles:true, cancelable:true});
      form.dispatchEvent(event);
      assert.equal(event.currentTarget, null, 'DOM clears currentTarget after dispatch');
      assert.equal(button.disabled, true, 'prevent duplicate requests while pending');
      await tick(); await tick();
      assert.equal(calls, 1, `${formId}: ${w.document.getElementById(messageId).textContent}`);
      assert.equal(w.document.getElementById(messageId).textContent, errorText);
      assert.equal(button.disabled, false, `${formId}: retry enabled after ${failure} failure`);
      assert.equal(button.textContent, originalLabel);
      // A second submission succeeds and also releases the busy state.
      w.fetch = async () => { calls++; return {ok:true, json:async () => ({})}; };
      form.dispatchEvent(new w.Event('submit', {bubbles:true, cancelable:true}));
      await tick(); await tick();
      assert.equal(calls, 2);
      assert.equal(button.disabled, false);
      assert.equal(button.textContent, originalLabel);
      assert.deepEqual(unhandled, []);
      dom.window.close(); checks++;
    }
  }
  console.log(`Async form recovery: ${checks} HTTP/network failure and successful retry cases passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
