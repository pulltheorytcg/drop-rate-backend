const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../../backend/app/static/scanner-flow.js'), 'utf8');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const tick = () => new Promise(resolve => setImmediate(resolve));
let checks = 0;

function fixture(role = 'seller', request = async () => ({})) {
  const dom = new JSDOM('<button id="launch">Scan</button>', {url:'https://example.test', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLDialogElement.prototype.showModal = function(){ this.open = true; };
  w.HTMLDialogElement.prototype.close = function(){ this.open = false; };
  w.HTMLMediaElement.prototype.play = async () => {};
  w.URL.createObjectURL = () => 'blob:preview';
  w.URL.revokeObjectURL = () => {};
  w.fetch = async () => ({ok:false});
  w.eval(source);
  const session = {value:{access_token:'test-token',user:{id:'account-a'}}};
  const calls = [];
  const scanner = new w.DropRateScanner.Scanner({role, session: () => session.value,
    request: async (url, options) => { calls.push({url,...options}); return request(url, options); },
    afterSave: async () => {}, viewInventory: () => { scanner.inventoryOpened = true; }});
  return {dom, w, scanner, calls, session, finish: () => { scanner.destroy(); dom.window.close(); }};
}

function result(overrides = {}) {
  return {run:{id:'run-1',decision:'EXACT_CANDIDATE',top_catalogue_id:'card-1'}, candidates:[{
    id:'candidate-1',catalogue_id:'card-1',rank:1,source_kind:'CATALOGUE',market_value_minor:1500,
    image_url:'https://example.test/card.png',candidate_snapshot:{name:'Card one',game:'One Piece',
      card_number:'OP11-118',language:'English',variant:'Standard art',product_type:'CARD'},
  }], ...overrides};
}

async function matched(scanner, quantity = 1) {
  await scanner.recognise('data:image/jpeg;base64,AA==');
  const item = scanner.items[0]; item.condition = 'Near Mint'; item.quantity = quantity; return item;
}

(async () => {
  // A real pending state is visible immediately; unresolved responses cannot enter inventory.
  {
    const pending = deferred(); const f = fixture('seller', () => pending.promise);
    const promise = f.scanner.recognise('data:image/jpeg;base64,AA==');
    assert.equal(f.scanner.items.length, 1);
    assert.match(f.scanner.find('.dr-scan-strip').textContent, /Loading/);
    assert.ok(f.scanner.find('.dr-scan-tile').disabled);
    f.scanner.showReview();
    assert.ok(f.scanner.find('[data-action="save"]').disabled);
    pending.resolve(result({run:{id:'run-1',decision:'NEEDS_REVIEW'}})); await promise;
    assert.equal(f.scanner.items[0].selected, null);
    assert.ok(f.scanner.find('[data-action="save"]').disabled);
    await f.scanner.saveAll(); assert.equal(f.calls.length, 1);
    assert.match(f.scanner.find('.dr-scan-review-total').textContent, /—/);
    f.finish(); checks += 1;
  }
  // Both roles use their existing intake endpoint, never an owner supplied by the browser.
  for (const role of ['seller', 'founder']) {
    const f = fixture(role, async url => url.endsWith('/resolve') ? result() : url.endsWith('/intake') || url.endsWith('/recognition-intake')
      ? {inventory:{inventory_code:'INV-1',identity_confirmed:false}} : {});
    const item = await matched(f.scanner);
    f.scanner.showReview(); await f.scanner.saveAll();
    const save = f.calls.find(call => call.headers?.['Idempotency-Key']);
    assert.equal(save.url, role === 'seller' ? '/api/v1/owner/recognition-intake' : '/api/v1/inventory/intake');
    const body = JSON.parse(save.body);
    assert.equal(body.condition, 'Near Mint'); assert.equal(body.owner_id, undefined);
    assert.equal(body.identity_confirmed, role === 'seller' ? undefined : false);
    assert.equal(item.status, 'added'); assert.equal(item.photo, null);
    assert.ok(f.calls.findIndex(call => call.url.endsWith('/feedback')) < f.calls.indexOf(save));
    assert.match(f.scanner.find('.dr-scan-save-message').textContent, /review is still required/);
    await f.scanner.saveAll(); assert.equal(f.scanner.inventoryOpened, true);
    f.finish(); checks += 1;
  }
  // Partial multi-copy save, lost response and double click: identical keys and payload on retry.
  {
    const firstFeedback = deferred(); let fail = true, saves = 0;
    const f = fixture('seller', async url => {
      if (url.endsWith('/resolve')) return result();
      if (url.endsWith('/feedback')) return firstFeedback.promise;
      if (url.endsWith('/recognition-intake')) {
        saves += 1;
        if (saves === 2 && fail) throw new Error('Connection lost after send');
        return {inventory:{inventory_code:'INV-' + saves}};
      }
      return {};
    });
    const item = await matched(f.scanner, 3); f.scanner.showReview();
    const saving = f.scanner.saveAll(); await f.scanner.saveAll();
    await tick();
    assert.equal(f.calls.filter(call => call.url.endsWith('/feedback')).length, 1);
    f.scanner.remove(item); f.scanner.openDetails(item);
    assert.equal(f.scanner.items.length, 1); assert.equal(f.scanner.edit, null);
    firstFeedback.resolve({}); await saving;
    assert.equal(item.status, 'save-error'); assert.equal(item.requests[0].result.inventory.inventory_code, 'INV-1');
    assert.ok(!f.scanner.find('[data-action="save"]').disabled);
    assert.equal(f.scanner.find('[data-action="save"]').textContent, 'Retry remaining saves');
    const lost = f.calls.filter(call => call.url.endsWith('/recognition-intake'))[1];
    // Even accidental in-memory edits cannot alter the immutable request after an uncertain save.
    item.condition = 'Damaged'; item.quantity = 12; fail = false;
    await f.scanner.saveAll();
    const attempts = f.calls.filter(call => call.url.endsWith('/recognition-intake'));
    assert.equal(attempts.length, 4); assert.equal(attempts[2].body, lost.body);
    assert.equal(attempts[2].headers['Idempotency-Key'], lost.headers['Idempotency-Key']);
    assert.equal(new Set(attempts.map(call => call.headers['Idempotency-Key'])).size, 3);
    assert.equal(item.status, 'added');
    f.finish(); checks += 1;
  }
  // Exact matches still require a physical condition; changing quantity validates integer bounds.
  {
    const f = fixture('seller', async () => result());
    await f.scanner.recognise('photo'); const item = f.scanner.items[0]; f.scanner.showReview();
    assert.ok(f.scanner.find('[data-action="save"]').disabled);
    f.scanner.openDetails(item);
    const condition = f.scanner.details.querySelector('select'); condition.value = 'Lightly Played';
    condition.dispatchEvent(new f.w.Event('change'));
    const quantity = f.scanner.details.querySelector('input'); quantity.value = '1.5'; quantity.dispatchEvent(new f.w.Event('input'));
    assert.ok(f.scanner.details.querySelector('[data-details-save]').disabled);
    quantity.value = '2'; quantity.dispatchEvent(new f.w.Event('input'));
    await f.scanner.confirmDetails();
    assert.equal(item.condition, 'Lightly Played'); assert.equal(item.quantity, 2);
    assert.equal(f.calls.length, 1, 'Detail confirmation alone does not write inventory or feedback');
    assert.match(f.scanner.find('.dr-scan-review-total').textContent, /£30.00/);
    f.finish(); checks += 1;
  }
  // Search corrections are explicit; stale search results cannot overwrite the newer query.
  {
    const old = deferred(), latest = deferred();
    const f = fixture('seller', async (url, options) => {
      if (url.endsWith('/resolve')) return result();
      if (url.includes('q=old')) return old.promise;
      if (url.includes('q=new')) return latest.promise;
      if (url.endsWith('/references/select')) return {catalogue_id:'new-canonical'};
      if (url.endsWith('/recognition-intake')) return {inventory:{inventory_code:'INV-CORRECTED'}};
      return {};
    });
    const item = await matched(f.scanner); f.scanner.openDetails(item); f.scanner.openSearch();
    const oldPromise = f.scanner.search('old', f.scanner.searchRevision);
    f.scanner.searchRevision += 1;
    const latestPromise = f.scanner.search('new', f.scanner.searchRevision);
    const row = {name:'Correct printing',requires_materialization:true,provider:'reference-provider',system_code:'ONE_PIECE_CARD_GAME',
      language:'English',provider_id:'provider-1',card_number:'OP11-118',variant:'Alternate art'};
    latest.resolve({items:[row]}); await latestPromise;
    old.resolve({items:[{id:'wrong',name:'Stale choice'}]}); await oldPromise;
    assert.match(f.scanner.details.textContent, /Correct printing/); assert.doesNotMatch(f.scanner.details.textContent, /Stale choice/);
    assert.ok(f.calls.find(call => call.url.includes('q=new')).url.includes('run_id=run-1'));
    await f.scanner.chooseSearch(row); await f.scanner.confirmDetails(); f.scanner.showReview(); await f.scanner.saveAll();
    const feedback = f.calls.find(call => call.url.endsWith('/feedback'));
    assert.equal(JSON.parse(feedback.body).outcome, 'CORRECTED_BY_SEARCH');
    assert.equal(JSON.parse(feedback.body).selected_catalogue_id, 'new-canonical');
    f.finish(); checks += 1;
  }
  // Unverified sealed candidates cannot be confirmed through the raw-card chooser.
  {
    const data = result(); data.run.decision = 'NEEDS_REVIEW'; data.candidates[0].candidate_snapshot.product_type = 'SEALED';
    const f = fixture('seller', async () => data); await f.scanner.recognise('photo');
    f.scanner.openDetails(f.scanner.items[0]);
    assert.ok(f.scanner.details.querySelector('[data-details-save]').disabled);
    assert.equal(f.scanner.ready(f.scanner.items[0]), false);
    f.finish(); checks += 1;
  }
  // Failed runs need a successful rescan before inventory; retry replaces the pending scan.
  {
    let failed = true;
    const f = fixture('seller', async () => failed ? result({run:{id:'run-failed',decision:'FAILED'}}) : result());
    await f.scanner.recognise('photo'); const item = f.scanner.items[0];
    f.scanner.openDetails(item); f.scanner.edit.condition = 'Near Mint'; f.scanner.updateDetailsSave();
    assert.ok(f.scanner.details.querySelector('[data-details-save]').disabled);
    assert.match(f.scanner.details.textContent, /Retry this photo/);
    failed = false; f.scanner.closeDetails(); await f.scanner.recognise(item.photo, item);
    assert.equal(f.scanner.items.length, 1); assert.equal(item.run.id, 'run-1');
    f.finish(); checks += 1;
  }
  // Stable empty backgrounds do not scan; physical removal is required between auto captures.
  {
    const f = fixture(); const s = f.scanner;
    s.stream = {getTracks: () => []}; s.view = 'camera';
    Object.defineProperty(s.video, 'videoWidth', {value: 1920});
    let present = false, captured = 0;
    s.frame = () => ({present, fingerprint: new Uint8Array(560).fill(100)});
    s.capture = () => { captured += 1; s.awaitingRemoval = true; s.stableFrames = 0; };
    s.stableFrames = 0; s.presenceFrames = 0; s.absenceFrames = 0;
    for (let i = 0; i < 10; i++) s.tick(); assert.equal(captured, 0);
    present = true; for (let i = 0; i < 6; i++) s.tick(); assert.equal(captured, 1);
    for (let i = 0; i < 10; i++) s.tick(); assert.equal(captured, 1);
    present = false; s.tick(); s.tick(); present = true;
    for (let i = 0; i < 6; i++) s.tick(); assert.equal(captured, 2);
    f.finish(); checks += 1;
  }
  // Session changes and logout discard pending recognition, release camera and stop further writes.
  {
    const pending = deferred(); const f = fixture('seller', () => pending.promise);
    const recognition = f.scanner.recognise('private-photo');
    f.scanner.destroy(); pending.resolve(result()); await recognition;
    assert.equal(f.scanner.items.length, 0); assert.equal(f.w.document.querySelector('dialog'), null);
    f.finish(); checks += 1;
  }
  {
    const pending = deferred(); const f = fixture('seller', async url => url.endsWith('/resolve') ? result() : pending.promise);
    await matched(f.scanner, 3); f.scanner.showReview(); const save = f.scanner.saveAll();
    f.session.value = {access_token:'other-token',user:{id:'account-b'}};
    pending.resolve({}); await save;
    assert.equal(f.calls.filter(call => call.url.endsWith('/recognition-intake')).length, 0);
    f.finish(); checks += 1;
  }
  // A refresh response cannot replace a different login or send the old batch under its token.
  {
    const pending = deferred(); const f = fixture();
    const expiredToken = 'header.' + Buffer.from(JSON.stringify({sub:'account-a',exp:1})).toString('base64url') + '.signature';
    f.session.value = {access_token:expiredToken,refresh_token:'old-refresh',user:{id:'account-a'}};
    f.scanner.options.refreshSession = () => pending.promise;
    let saved = 0; f.scanner.options.saveSession = value => { saved += 1; f.session.value = value; };
    const work = f.scanner.request('/api/v1/inventory/intake', {method:'POST'});
    f.session.value = {access_token:'new-account-token',user:{id:'account-b'}};
    pending.resolve({access_token:'refreshed-a',user:{id:'account-a'}});
    await assert.rejects(work, /account changed/);
    assert.equal(saved, 0); assert.equal(f.calls.length, 0);
    f.finish(); checks += 1;
  }
  // A late camera permission grant after closing never leaves hardware streaming.
  {
    const pending = deferred(); const f = fixture(); let stopped = 0;
    Object.defineProperty(f.w.navigator, 'mediaDevices', {value:{getUserMedia: () => pending.promise}});
    const opening = f.scanner.open(); f.scanner.close();
    pending.resolve({getTracks: () => [{stop: () => {stopped += 1;}}]}); await opening;
    assert.equal(stopped, 1); assert.equal(f.scanner.stream, null);
    f.finish(); checks += 1;
  }
  // Permission denial leaves gallery usable, and surfaces the actual blocked state.
  {
    const f = fixture(); Object.defineProperty(f.w.navigator, 'mediaDevices', {value:{getUserMedia: async () => {
      throw Object.assign(new Error('Permission denied'), {name:'NotAllowedError'});
    }}});
    await f.scanner.open();
    assert.match(f.scanner.find('.dr-scan-status').textContent, /Allow camera access/);
    assert.equal(f.scanner.find('[data-action="gallery"]').disabled, false);
    f.finish(); checks += 1;
  }
  // Torch is offered only when the active track supports it, and is stopped with the camera.
  {
    const f = fixture(); const constraints = []; let stopped = 0;
    const track = {getCapabilities: () => ({torch:true}), applyConstraints: async value => constraints.push(value), stop: () => {stopped += 1;}};
    Object.defineProperty(f.w.navigator, 'mediaDevices', {value:{getUserMedia: async () => ({getTracks: () => [track],getVideoTracks: () => [track]})}});
    await f.scanner.open();
    assert.equal(f.scanner.find('[data-action="torch"]').hidden, false);
    await f.scanner.toggleTorch(); assert.equal(constraints[0].advanced[0].torch, true);
    assert.equal(f.scanner.find('[data-action="torch"]').textContent, 'Torch on');
    f.scanner.close(); assert.equal(stopped, 1); assert.equal(f.scanner.torchOn, false);
    f.finish(); checks += 1;
  }
  await tick();
  console.log('Scanner flow: ' + checks + ' interaction, permission and retry scenarios passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
