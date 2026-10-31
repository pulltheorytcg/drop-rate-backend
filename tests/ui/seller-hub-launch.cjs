'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
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
  assert.equal(layout.querySelectorAll('.feature-card-list .feature-card').length, 5, 'five routine tools appear in the mobile feature carousel');
  assert.ok(!layout.querySelector('.feature-card-auction').closest('.feature-card-list'), 'auction lens retains its own full-width mobile spotlight');
  assert.equal(layout.querySelectorAll('.mobile-swipe-hint').length, 2, 'collection and feature rows have visible swipe directions on phones');
  assert.equal(layout.querySelector('.collection-grid').getAttribute('tabindex'), '0', 'collecting carousel supports keyboard scrolling');
  assert.equal(layout.querySelector('.feature-card-list').getAttribute('tabindex'), '0', 'feature carousel supports keyboard scrolling');
  assert.ok(layout.querySelector('.hero-lede-mobile').textContent.includes('Easier selling is on the way'));
  const tickerGroups = Array.from(layout.querySelectorAll('.ticker-track .ticker-group'));
  assert.equal(tickerGroups.length, 2, 'continuous ticker repeats one identical group for a seamless loop');
  assert.equal(tickerGroups[0].textContent, tickerGroups[1].textContent, 'both marquee halves are identical');
  assert.equal(layout.querySelector('.ticker-track').getAttribute('aria-hidden'), 'true', 'repeated moving copy must not be announced twice');
  assert.ok(layout.querySelector('.ticker').getAttribute('aria-label').includes('One connected collection'), 'ticker message remains accessible without animation');
  const tickerStyles = fs.readFileSync(path.join(root, 'backend/app/static/seller-hub-launch.css'), 'utf8');
  assert.match(tickerStyles, /animation:ticker-scroll 38s linear infinite/, 'ticker scrolls continuously');
  assert.match(tickerStyles, /@media\(prefers-reduced-motion:reduce\)\{\s*\.ticker-track\{animation:none/, 'reduced-motion users get a still ticker');
  assert.match(tickerStyles, /\.feature-card-list\{display:contents\}/, 'desktop features retain their original grid positions');
  assert.match(tickerStyles, /\.collection-grid\{[^}]*scroll-snap-type:x mandatory/, 'mobile collection photos scroll and snap horizontally');
  assert.match(tickerStyles, /\.feature-card-list\{[^}]*scroll-snap-type:x mandatory/, 'mobile feature cards scroll and snap horizontally');
  assert.match(tickerStyles, /\.feature-card-list\{[^}]*align-items:stretch/, 'mobile feature cards stretch to the same height as the longest card');
  assert.match(tickerStyles, /\.process-section\{display:none\}/, 'mobile hides the repeated how-it-works section');
  assert.ok(layout.querySelector('img[src="/assets/brand-assets/seller-hub-approved.webp"]'));
  const badges = Array.from(layout.querySelectorAll('.topbar .store-badge'));
  assert.equal(badges.length, 2, 'both mobile platform badges appear only in the Seller Hub header');
  assert.ok(badges.every(badge => badge.getAttribute('href') === '#early-access'), 'unreleased apps must direct visitors to the launch list');
  assert.ok(badges.every(badge => badge.getAttribute('aria-label').includes('coming soon')), 'download buttons must not promise an available app');
  assert.deepEqual(badges.map(badge => badge.querySelector('strong').textContent), ['App Store', 'Google Play']);
  assert.equal(layout.querySelectorAll('.grail-showcase .grail-card img').length, 3, 'three photographed and verifiable graded cards replace the large hero logo');
  assert.equal(layout.querySelectorAll('.hero-art .floating-card').length, 0, 'decorative overlays cannot obscure graded cards, headings or captions');
  assert.equal(layout.querySelectorAll('.hero-art .seller-hub-mark').length, 0, 'large hero logo was removed');
  assert.deepEqual(
    Array.from(layout.querySelectorAll('.grail-showcase .grail-card img'), image => image.getAttribute('src')),
    ['/assets/collection-photos/eevee-psa10-front.webp', '/assets/collection-photos/luffy-psa10-front.webp', '/assets/collection-photos/charizard-psa10-front.webp'],
  );
  for (const image of layout.querySelectorAll('.grail-showcase .grail-card img')) {
    assert.ok(fs.existsSync(path.join(root, 'backend/app/static', image.getAttribute('src').replace('/assets/', ''))), 'referenced slab photo must be shipped');
  }
  assert.ok(Array.from(layout.querySelectorAll('.grail-showcase .grail-card img')).every(image => image.alt.includes('Actual Drop Rate product photograph')));
  assert.ok(layout.querySelector('.grail-note').textContent.includes('REAL DROP RATE PRODUCT PHOTOS'));
  assert.ok(!layout.querySelector('.grail-showcase').textContent.includes('BLACK LABEL'), 'never invent slab certifications');
  const gallery = Array.from(layout.querySelectorAll('.collection-grid .collection-tile'));
  assert.equal(gallery.length, 6, 'show actual photo categories including Pokémon, One Piece, sealed, slabs, comics and manga');
  for (const tile of gallery) {
    const image = tile.querySelector('img');
    assert.ok(image && image.getAttribute('loading') === 'lazy');
    assert.ok(fs.existsSync(path.join(root, 'backend/app/static', image.getAttribute('src').replace('/assets/', ''))), 'all collection photos ship with the page');
  }
  assert.ok(layout.querySelector('.collection-photo-note').textContent.includes('illustrative, not a claim of stock'));
  assert.ok(layout.querySelector('.collection-mobile-disclosure').textContent.includes('illustrative, not stock photos'));
  assert.ok(layout.querySelector('.collection-photo-credits-mobile').querySelectorAll('a').length >= 3, 'mobile visitors can expand credited photo sources');
  const imageManifest = JSON.parse(fs.readFileSync(path.join(root, 'backend/app/static/collection-photos/sources.json'), 'utf8'));
  for (const item of imageManifest.images) {
    const bytes = fs.readFileSync(path.join(root, 'backend/app/static/collection-photos', item.file));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), item.sha256, `photo ${item.file} matches recorded source hash`);
  }
  assert.deepEqual(new Set(imageManifest.images.map(item => item.kind)), new Set([
    'real_merchant_inventory_photo', 'merchant_used_manufacturer_product_image_not_physical_photo', 'editorial_photo_not_inventory',
  ]));
  const sellFeature = Array.from(layout.querySelectorAll('.feature-card')).find(card => /Sell with Drop Rate/.test(card.textContent));
  assert.ok(sellFeature, 'prelaunch selling feature is explicit');
  for (const channel of ['Drop Rate store', 'eBay', 'Whatnot']) assert.ok(sellFeature.textContent.includes(channel), `planned channel ${channel} is named`);
  assert.ok(sellFeature.textContent.includes('PLANNED'));
  const auction = layout.querySelector('.feature-card-auction');
  assert.ok(auction.textContent.includes('Live Auction Lens'));
  assert.ok(auction.textContent.includes('screen recording, with your permission'));
  assert.ok(auction.textContent.includes('under, around or over market value'));
  assert.ok(auction.textContent.includes('PLANNED CONCEPT'));
  assert.ok(auction.textContent.includes('No live prices shown'), 'never fabricate the market value in a concept image');
  assert.ok(layout.querySelector('a[href="#collectibles"]'), 'new photo gallery is reachable in the header');
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
