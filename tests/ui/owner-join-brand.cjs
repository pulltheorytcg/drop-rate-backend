'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'backend/app/static/owner-join.html'), 'utf8');
const login = fs.readFileSync(path.join(root, 'backend/app/static/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'backend/app/static/owner-join.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'backend/app/static/owner-join.css'), 'utf8');
const expectedIds = ['owner-invite-loading','owner-invite-invalid','owner-invite-invalid-message','owner-join-form','owner-invite-summary','owner-join-social-auth','owner-join-google','owner-join-apple','owner-join-name','owner-join-email','owner-join-password','owner-join-confirm-password','owner-join-ack','owner-join-message','owner-show-existing-login','owner-existing-login-form','owner-existing-summary','owner-existing-social-auth','owner-existing-google','owner-existing-apple','owner-existing-email','owner-existing-password','owner-existing-ack','owner-existing-message','owner-back-to-join'];
async function settle(predicate) {
  for (let i = 0; i < 50; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail('Registration did not reach the expected state');
}
function mount({invited=false,invalid=false,providers={}}={}) {
  const dom = new JSDOM(html, {url:'https://hub.example.test/owner/join'+(invited?'?invite=synthetic-invite':''),runScripts:'outside-only'});
  const calls=[];
  dom.window.fetch=async(url,options={})=>{
    calls.push({url:String(url),method:options.method||'GET'});
    let data;
    if (url==='/api/v1/public-config') data={supabase_url:'https://auth.example.test',publishable_key:'synthetic-public-key'};
    else if (String(url).endsWith('/auth/v1/settings')) data={external:providers};
    else if (String(url).startsWith('/api/v1/public/owner-invites/')) {
      if(invalid) return {ok:false,json:async()=>({detail:'This invitation has expired.'})};
      data={commission_bps:1250,acknowledgement_version:1,invited_name:'Fixture Seller',invited_email_masked:'f***@example.test',expires_at:'2100-01-01T00:00:00Z'};
    } else throw new Error('Unexpected network operation: '+url);
    return {ok:true,json:async()=>data};
  };
  dom.window.eval(source);
  return {dom,doc:dom.window.document,calls};
}
(async()=>{
  const shell=new JSDOM(html).window.document;
  const loginDoc=new JSDOM(login).window.document;
  const ids=[...shell.querySelectorAll('[id]')].map(n=>n.id);
  assert.equal(new Set(ids).size,ids.length);
  expectedIds.forEach(id=>assert.ok(shell.getElementById(id),id));
  assert.ok(shell.querySelector('#auth-view.auth-layout'));
  for(const selector of ['.collector-auth-logo','.collector-auth-grails img']) {
    assert.equal(shell.querySelector(selector).getAttribute('src'),loginDoc.querySelector(selector).getAttribute('src'));
  }
  assert.equal(shell.querySelector('.brand-copy h1').textContent,loginDoc.querySelector('.brand-copy h1').textContent);
  assert.equal(shell.querySelector('link[href*="collector-worlds.css"]').getAttribute('href'),loginDoc.querySelector('link[href*="collector-worlds.css"]').getAttribute('href'));
  assert.match(css,/input\[type="checkbox"\]/);
  assert.match(css,/font-size: 16px/);
  assert.match(css,/:focus-visible/);
  assert.ok(shell.querySelector('#owner-join-ack[required]'));
  assert.ok(shell.querySelector('#owner-existing-ack[required]'));
  assert.equal(shell.querySelector('#owner-join-password').getAttribute('minlength'),'12');
  assert.ok(shell.querySelector('.owner-entry-includes:not([open])'));
  assert.ok(shell.querySelector('#owner-invite-summary').closest('details')===null);
  const pub=mount();
  await settle(()=>!pub.doc.getElementById('owner-join-form').classList.contains('hidden'));
  assert.match(pub.doc.getElementById('owner-invite-summary').textContent,/10/);
  assert.ok(pub.doc.getElementById('owner-join-social-auth').classList.contains('hidden'));
  pub.doc.getElementById('owner-join-password').value='LongPassword123!';
  pub.doc.getElementById('owner-join-confirm-password').value='DifferentPassword123!';
  pub.doc.getElementById('owner-join-form').dispatchEvent(new pub.dom.window.Event('submit',{bubbles:true,cancelable:true}));
  assert.match(pub.doc.getElementById('owner-join-message').textContent,/do not match/);
  assert.equal(pub.calls.filter(x=>x.method!=='GET').length,0);
  pub.dom.window.close();
  const invitation=mount({invited:true,providers:{google:true}});
  await settle(()=>!invitation.doc.getElementById('owner-join-form').classList.contains('hidden'));
  assert.match(invitation.doc.getElementById('owner-invite-summary').textContent,/12.50/);
  assert.equal(invitation.doc.getElementById('owner-join-name').value,'Fixture Seller');
  assert.ok(!invitation.doc.getElementById('owner-join-google').classList.contains('hidden'));
  assert.ok(invitation.doc.getElementById('owner-join-apple').classList.contains('hidden'));
  invitation.doc.getElementById('owner-join-email').value='fixture@example.test';
  invitation.doc.getElementById('owner-join-ack').checked=true;
  invitation.doc.getElementById('owner-show-existing-login').click();
  assert.ok(!invitation.doc.getElementById('owner-existing-login-form').classList.contains('hidden'));
  assert.equal(invitation.doc.getElementById('owner-existing-email').value,'fixture@example.test');
  assert.ok(invitation.doc.getElementById('owner-existing-ack').checked);
  invitation.doc.getElementById('owner-back-to-join').click();
  assert.ok(!invitation.doc.getElementById('owner-join-form').classList.contains('hidden'));
  assert.equal(invitation.calls.filter(x=>x.method!=='GET').length,0);
  invitation.dom.window.close();
  const invalid=mount({invited:true,invalid:true});
  await settle(()=>!invalid.doc.getElementById('owner-invite-invalid').classList.contains('hidden'));
  assert.match(invalid.doc.getElementById('owner-invite-invalid-message').textContent,/expired/);
  assert.equal(invalid.doc.querySelector('.owner-entry-back').getAttribute('href'),'/app');
  assert.ok(invalid.doc.getElementById('owner-join-form').classList.contains('hidden'));
  invalid.dom.window.close();
  console.log('Owner join branding: shared shell, required controls, public preview, password mismatch, invitation continuation, provider visibility and invalid invitation passed (mocked network).');
})().catch(e=>{console.error(e);process.exitCode=1;});
