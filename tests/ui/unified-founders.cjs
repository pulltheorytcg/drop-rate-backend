const {JSDOM} = require('jsdom');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const base = path.join(__dirname, '../../backend/app/static');
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(founder) {
  const source = fs.readFileSync(path.join(base, 'owner.html'), 'utf8');
  const dom = new JSDOM(source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, ''), {
    url: 'https://example.test/owner', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const w = dom.window, doc = w.document, run = code => vm.runInContext(code, dom.getInternalVMContext());
  const errors = [], calls = [];
  w.addEventListener('error', event => errors.push(event.error));
  w.matchMedia = () => ({matches: false, addEventListener() {}});
  w.scrollTo = () => {};
  w.fetch = async () => ({ok: true, json: async () => ({items: []})});
  w.HTMLDialogElement.prototype.showModal = function() {this.open = true;};
  w.HTMLDialogElement.prototype.close = function() {this.open = false;};
  for (const [, file] of source.matchAll(/<script src="\/assets\/([^"?]+)[^"]*"/g)) {
    run(fs.readFileSync(path.join(base, file), 'utf8').replace(/\ninitialise\(\);\s*$/, '\n'));
  }
  let access = founder ? {access_role: 'PLATFORM_ADMIN', portal: 'FOUNDER_HQ', founder_hq_allowed: true, business_allowed: true, display_name: 'Founder'}
    : {access_role: 'OWNER', portal: 'OWNER_PORTAL', founder_hq_allowed: false, business_allowed: false, display_name: 'Seller'};
  let release;
  w.fixtureRequest = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/v1/access/me') return {access};
    if (url === '/api/v1/founder/accounts') {
      if (release === 'defer') return new Promise(resolve => {release = resolve;});
      return {own_owner_id: 'founder', accounts: [{id: 'founder', display_name: 'Founder', owner_type: 'FOUNDER', draft_count: 2},
        {id: 'seller', display_name: '<img src=x>', owner_type: 'CONSIGNOR', active_stock_count: 3}]};
    }
    return {items: [], total: 0, sales: [], payouts: []};
  };
  run(`state.session={access_token:'fixture',user:{id:'account-a'}};apiRequest=window.fixtureRequest;
    reloadOwnerDashboard=loadOwnerInventory=loadOwnerChannels=async()=>{};`);
  return {w, doc, run, calls, errors, setAccess: a => {access = a;}, defer: () => {release = 'defer';}, resolve: data => release(data), close: () => w.close()};
}
(async () => {
  for (const founder of [false, true]) {
    const f = fixture(founder);
    assert.equal(f.doc.querySelector('.founder-settings-entry').hidden, true);
    await f.run('openOwnerPortal()'); await tick();
    assert.equal(f.doc.querySelector('#owner-portal-view').classList.contains('hidden'), false);
    assert.deepEqual([...f.doc.querySelectorAll('.owner-nav-item')].map(el => el.dataset.ownerView), ['overview','inventory','scan','search','selling']);
    assert.equal(f.doc.querySelector('.workspace-brand-caption').textContent, 'Seller Hub');
    assert.equal(f.doc.querySelector('.founder-settings-entry').hidden, !founder);
    assert.ok(f.calls.every(call => !call.url.startsWith('/api/v1/founder/')), 'No business data is fetched just for signing in');
    f.run("activateOwnerView('settings')");
    assert.ok(f.doc.querySelector('#owner-view-settings .founder-settings-entry'));
    f.doc.querySelector('.founder-settings-entry').click(); await tick(); await tick();
    assert.equal(f.w.location.hash, founder ? '#founders' : '#settings');
    if (founder) {
      assert.match(f.doc.querySelector('#accounts-summary').textContent, /2Active|Active accounts2/);
      assert.equal(f.doc.querySelectorAll('.founder-control-card').length, 8);
      const links = [...f.doc.querySelectorAll('.founder-control-card')].map(el => el.getAttribute('href'));
      for (const key of ['inventory','verification','media','dashboard','reports','balance','sales','settings']) assert.ok(links.includes('/founders#'+key));
      f.doc.querySelector('#business-tab-sellers').click(); await tick(); await tick();
      assert.equal(f.doc.querySelectorAll('.business-seller-card').length, 2);
      assert.equal(f.doc.querySelectorAll('.business-seller-card img').length, 0, 'Names are text, never markup');
      f.doc.querySelector('#owner-view-founders > .workspace-back').click();
      assert.equal(f.w.location.hash, '#settings');
      assert.equal(f.doc.activeElement, f.doc.querySelector('.founder-settings-entry'));
      f.run("activateOwnerView('founders')"); await tick(); await tick();
      f.defer(); f.doc.querySelector('#business-refresh').click(); await tick();
      f.run('clearSession()');
      f.resolve({accounts: [{id: 'late', display_name: 'Private late result'}]}); await tick();
      assert.equal(f.doc.querySelector('#accounts-results').textContent, '');
      assert.equal(f.doc.querySelector('.founder-settings-entry').hidden, true);
      assert.equal(f.run('state.access'), null);
      assert.equal(f.doc.querySelector('#owner-view-founders').classList.contains('hidden'), true);
    } else {
      assert.ok(f.calls.every(call => !call.url.startsWith('/api/v1/founder/')));
      f.run("activateOwnerView('founders')"); assert.equal(f.w.location.hash, '#settings');
    }
    assert.ok(f.calls.every(call => !call.options?.method || call.options.method === 'GET'));
    assert.equal(f.errors.length, 0, f.errors.map(String).join('\n'));
    const ids = [...f.doc.querySelectorAll('[id]')].map(el => el.id);
    assert.equal(new Set(ids).size, ids.length);
    f.close();
  }
  // Revocation hides the entry and removes already-rendered business data.
  const f = fixture(true); await f.run('openOwnerPortal()'); await tick();
  f.run("activateOwnerView('founders')"); await tick(); await tick();
  f.setAccess({access_role: 'OWNER', portal: 'OWNER_PORTAL', business_allowed: false});
  f.doc.querySelector('#business-refresh').click(); await tick(); await tick();
  assert.equal(f.doc.querySelector('#business-content').hidden, true);
  assert.equal(f.doc.querySelector('#accounts-results').textContent, '');
  assert.equal(f.w.location.hash, '#settings');
  f.close();
  // Privileged forms keep their existing handlers but return to the shared Hub.
  {
    const source = fs.readFileSync(path.join(base, 'index.html'), 'utf8');
    const dom = new JSDOM(source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, ''), {
      url: 'https://example.test/founders#settings', runScripts: 'outside-only', pretendToBeVisual: true,
    });
    const w = dom.window, doc = w.document, errors = [];
    const run = code => vm.runInContext(code, dom.getInternalVMContext());
    w.addEventListener('error', event => errors.push(event.error));
    w.matchMedia = () => ({matches: false, addEventListener() {}});
    w.scrollTo = () => {}; w.fetch = async () => ({ok: true, json: async () => ({items: []})});
    const main = fs.readFileSync(path.join(base, '../main.py'), 'utf8');
    const files = [...source.matchAll(/<script src="\/assets\/([^"?]+)[^"]*"/g),
      ...main.matchAll(/'<script src="\/assets\/([^"?]+)[^"]*" defer/g)].map(match => match[1]);
    for (const file of [...new Set(files)]) run(fs.readFileSync(path.join(base, file), 'utf8').replace(/\ninitialise\(\);\s*$/, '\n'));
    assert.equal(doc.getElementById('seller-nav').hidden, true);
    assert.deepEqual([...doc.querySelectorAll('.founder-shared-nav a')].map(el => el.getAttribute('href')),
      ['/owner','/owner#inventory','/owner#scan','/owner#search','/owner#selling']);
    assert.equal(doc.querySelector('.founder-dashboard-back').getAttribute('href'), '/owner#founders');
    for (const id of ['shopify-settings-panel','ebay-connect-button','owner-invite-create','pricing-adapter-status']) assert.ok(doc.getElementById(id));
    const notes = doc.getElementById('intake-notes'); notes.value = 'Unsaved founder note';
    run("activateSellerView('inventory',true);activateSellerView('media',true);");
    await tick(); await tick();
    assert.equal(notes.value, 'Unsaved founder note');
    assert.equal(doc.querySelector('.workspace-brand-caption').textContent, 'Seller Hub');
    assert.equal(errors.length, 0, errors.map(String).join('\n'));
    w.close();
  }
  console.log('PASS: shared founder/seller shell, Settings-only founder dashboard, eight existing control destinations, owner denial, revocation, escaping, logout and stale-response cleanup.');
})().catch(error => {console.error(error); process.exitCode = 1;});
