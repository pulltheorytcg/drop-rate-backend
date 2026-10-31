'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'backend/app/static/seller-hub-launch.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'backend/app/static/seller-hub-launch.js'), 'utf8');

function mount(responses = []) {
  const dom = new JSDOM(html, { url: 'https://app.droprate.co.uk/', runScripts: 'outside-only' });
  const calls = [];
  dom.window.fetch = async (url, options) => {
    calls.push({ url, options, body: JSON.parse(options.body) });
    if (responses.length) return responses.shift();
    return { ok: true, json: async () => ({ status: 'registered' }) };
  };
  dom.window.eval(source);
  const doc = dom.window.document;
  const email = doc.getElementById('waitlist-email');
  email.value = 'seller@example.com';
  doc.getElementById('waitlist-consent').checked = true;
  return { dom, doc, calls, form: doc.getElementById('seller-hub-waitlist-form') };
}

async function settle(predicate) {
  for (let i = 0; i < 40; i++) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail('Form did not settle');
}

(async () => {
  const layout = new JSDOM(html).window.document;
  const ids = Array.from(layout.querySelectorAll('[id]'), element => element.id);
  assert.equal(new Set(ids).size, ids.length, 'IDs must be unique');
  assert.equal(layout.querySelectorAll('.feature-card').length, 6);
  assert.ok(layout.querySelector('img[src="/assets/brand-assets/seller-hub-approved.webp"]'));
  const badges = Array.from(layout.querySelectorAll('.topbar .store-badge'));
  assert.equal(badges.length, 2, 'both mobile platform badges appear only in the Seller Hub header');
  assert.ok(badges.every(badge => badge.getAttribute('href') === '#early-access'), 'unreleased apps must direct visitors to the launch list');
  assert.ok(badges.every(badge => badge.getAttribute('aria-label').includes('coming soon')), 'download buttons must not promise an available app');
  assert.deepEqual(badges.map(badge => badge.querySelector('strong').textContent), ['App Store', 'Google Play']);
  assert.equal(layout.querySelectorAll('.grail-showcase .grail-card img').length, 3, 'three genuine grail-card artworks replace the large hero logo');
  assert.equal(layout.querySelectorAll('.hero-art .seller-hub-mark').length, 0, 'large hero logo was removed');
  assert.deepEqual(
    Array.from(layout.querySelectorAll('.grail-showcase .grail-card img'), image => image.getAttribute('src')),
    ['/assets/grail-art/umbreon-vmax-215.webp', '/assets/grail-art/goku-fb01-139-p2.webp', '/assets/grail-art/rocks-op17-118-p2.webp'],
  );
  for (const image of layout.querySelectorAll('.grail-showcase .grail-card img')) {
    assert.ok(fs.existsSync(path.join(root, 'backend/app/static', image.getAttribute('src').replace('/assets/', ''))), 'referenced grail artwork must be shipped');
  }
  assert.ok(Array.from(layout.querySelectorAll('.grail-showcase .grail-card img')).every(image => image.alt.includes('reference artwork')));
  assert.ok(layout.querySelector('.grail-note').textContent.includes('NOT INVENTORY'));
  assert.ok(!layout.querySelector('.grail-showcase').textContent.includes('BLACK LABEL'), 'never invent slab certifications');
  assert.ok(layout.querySelector('a[href="/owner/join"]'), 'early seller account route remains available');
  assert.ok(layout.querySelector('a[href="/owner"]'), 'existing seller login remains available');
  assert.ok(layout.getElementById('waitlist-consent').required);
  assert.ok(layout.querySelector('.consent-choice').textContent.includes('Shopify customer list'));
  assert.ok(layout.querySelector('.fine-print').textContent.includes('unrelated store marketing'));
  assert.ok(layout.getElementById('waitlist-email').required);

  const success = mount();
  success.doc.getElementById('waitlist-name').value = 'Jamie';
  success.doc.getElementById('waitlist-interest').value = 'COMICS_MANGA';
  success.form.dispatchEvent(new success.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await settle(() => success.doc.getElementById('waitlist-submit').disabled);
  await settle(() => /on the list/.test(success.doc.getElementById('waitlist-message').textContent));
  assert.equal(success.calls.length, 1);
  assert.equal(success.calls[0].url, '/api/v1/public/seller-hub/waitlist');
  assert.equal(success.calls[0].options.credentials, 'omit');
  assert.equal(success.calls[0].body.email, 'seller@example.com');
  assert.equal(success.calls[0].body.interest, 'COMICS_MANGA');
  assert.equal(success.calls[0].body.consent, true);
  assert.equal(success.calls[0].body.shopify_contact_consent, true);
  success.form.dispatchEvent(new success.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(success.calls.length, 1, 'completed form must not submit twice');
  success.dom.window.close();

  const failure = mount([{ ok: false, status: 503 }]);
  failure.form.dispatchEvent(new failure.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await settle(() => /couldn't save/.test(failure.doc.getElementById('waitlist-message').textContent));
  assert.equal(failure.doc.getElementById('waitlist-submit').disabled, false);
  assert.equal(failure.doc.getElementById('waitlist-email').value, 'seller@example.com');
  failure.form.dispatchEvent(new failure.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await settle(() => /on the list/.test(failure.doc.getElementById('waitlist-message').textContent));
  assert.equal(failure.calls.length, 2);
  failure.dom.window.close();

  const missingConsent = mount();
  missingConsent.doc.getElementById('waitlist-consent').checked = false;
  missingConsent.form.dispatchEvent(new missingConsent.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(missingConsent.calls.length, 0, 'explicit consent is mandatory');
  missingConsent.dom.window.close();

  console.log('Seller Hub launch form: success, retry, consent, semantics passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
