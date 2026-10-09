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
  {
    const f=fixture();const imagePath='/api/v1/catalogue-browser/reference-image?provider_id=OP16-077';
    const blob=new f.w.Blob(['image'],{type:'image/png'});const calls=[];
    f.w.fetch=async(path,options)=>{calls.push({path,...options});return {ok:true,blob:async()=>blob};};
    assert.equal(await f.scanner.requestImage(imagePath),blob);
    assert.equal(calls[0].headers.Authorization,'Bearer test-token');
    await assert.rejects(f.scanner.requestImage('https://evil.test/image'),/Invalid artwork/);assert.equal(calls.length,1);
    f.w.fetch=async()=>({ok:true,blob:async()=>new f.w.Blob(['html'],{type:'text/html'})});
    await assert.rejects(f.scanner.requestImage(imagePath),/Invalid artwork/);f.finish();checks++;
  }
  {
    const f=fixture(),pending=deferred();f.w.fetch=()=>pending.promise;
    const result=f.scanner.requestImage('/api/v1/catalogue-browser/reference-image?provider_id=OP16-077');await tick();
    f.session.value={access_token:'other-token',user:{id:'account-b'}};
    pending.resolve({ok:true,blob:async()=>new f.w.Blob(['image'],{type:'image/png'})});
    await assert.rejects(result,/account changed/);f.finish();checks++;
  }
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
    assert.ok(f.calls.find(call => call.url.includes('q=new')).url.startsWith('/api/v1/catalogue-browser/products?'));
    assert.ok(f.calls.find(call => call.url.includes('q=new')).url.includes('owned=all'));
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
  // Modes are visible, and a completed capture keeps its original type.
  {
    const f = fixture('seller', async () => result({candidates:[{...result().candidates[0],
      candidate_snapshot:{...result().candidates[0].candidate_snapshot, product_type:'SEALED'}}]}));
    assert.deepEqual([...f.scanner.dialog.querySelectorAll('[data-mode]')].map(n => n.textContent), ['RAW','GRADED','SEALED']);
    await f.scanner.recognise('photo'); assert.equal(f.scanner.items[0].selected, null);
    f.scanner.setMode('SEALED'); await f.scanner.recognise('photo');
    assert.equal(f.scanner.ready(f.scanner.items[1]), true);
    f.scanner.setMode('RAW'); assert.equal(f.scanner.items[1].mode, 'SEALED');
    f.finish(); checks += 1;
  }
  for (const role of ['seller','founder']) {
    const f = fixture(role, async url => url.endsWith('/scan') ? {
      observation:{grader:'BGS',certificate_number:'123456789',grade:'9.5',card_name:'Card one',card_number:'OP11-118'},
      conflicts:[],catalogue_search_seed:'OP11-118',provider_error:'PROVIDER_NOT_CONFIGURED',
    } : url.includes('catalogue') ? {items:[{id:'card-1',name:'Card one',product_type:'CARD',market_value_minor:1500}]}
      : {inventory:{inventory_code:'INV-SLAB',identity_confirmed:false}});
    f.scanner.setMode('GRADED'); await f.scanner.recognise('photo');
    const item = f.scanner.items[0]; assert.equal(item.selected, null);
    f.scanner.openDetails(item); assert.equal(f.scanner.edit.grade, '9.5');
    assert.doesNotMatch(f.scanner.details.querySelector('.dr-scan-detail-identity').textContent, /£15/);
    await f.scanner.confirmDetails(); assert.equal(f.scanner.ready(item), true);
    f.scanner.showReview(); await f.scanner.saveAll();
    const save = f.calls.find(call => call.headers?.['Idempotency-Key']);
    assert.equal(save.url, role === 'seller' ? '/api/v1/owner/graded-certificate-intake' : '/api/v1/inventory/graded-intake');
    assert.deepEqual(JSON.parse(save.body), {selected_catalogue_id:'card-1',grading_company:'BGS',grade:'9.5',certificate_number:'123456789',language:null});
    assert.equal(f.calls.some(call => call.url.endsWith('/feedback')), false);
    f.finish(); checks += 1;
  }
  {
    const f = fixture('seller', async () => ({provider:'PSA',certificate_number:'12345678',grade:'10',verified:true}));
    f.scanner.manualSlab(); const item=f.scanner.items[0];
    item.slab={conflicts:['grade']}; f.scanner.edit.selected={catalogue_id:'card-1'};
    f.scanner.edit.grade='10'; f.scanner.edit.certificate_number='12345678';
    await f.scanner.lookupSlab();
    assert.ok(f.scanner.details.querySelector('[data-details-save]').disabled);
    assert.deepEqual(item.slab.conflicts,['grade']);
    f.finish(); checks += 1;
  }
  {
    const pending=deferred(); const f=fixture('seller', () => pending.promise);
    const resolving=f.scanner.recognise('photo'); f.scanner.setMode('GRADED');
    assert.equal(f.scanner.mode,'RAW'); pending.resolve(result()); await resolving;
    assert.equal(f.scanner.items[0].mode,'RAW');
    f.finish(); checks += 1;
  }
  // An unreadable number can be human-confirmed against the governed reference.
  // Missing prices do not block this path; condition remains an explicit choice.
  for (const role of ['seller', 'founder']) {
    const reference = {provider:'Punk Records', system_code:'ONE_PIECE_CARD_GAME', language:'Japanese', provider_id:'OP12-106_p2'};
    const data = result({run:{id:'run-law', decision:'NEEDS_REVIEW', top_catalogue_id:null}, candidates:[{
      id:'law-candidate', rank:1, score:.98125, source_kind:'PROVIDER', catalogue_id:null,
      market_value_minor:null, reference_selection:reference,
      candidate_snapshot:{name:'Trafalgar Law',base_card_id:'OP12-106',language:'Japanese',art_treatment:'Parallel'}
    }]});
    const f = fixture(role, async (url, options) => {
      if (url.endsWith('/resolve')) return data;
      if (url.endsWith('/references/select')) return {catalogue_id:'law-printing',selected:{card_number:'OP12-106'}};
      if (url.endsWith('/recognition-intake') || url.endsWith('/inventory/intake')) return {inventory:{inventory_code:'INV-LAW'}};
      if (url.endsWith('/materialize')) throw new Error('Must not use exact-OCR materialization');
      return {};
    });
    await f.scanner.recognise('law-photo'); const item=f.scanner.items[0]; f.scanner.openDetails(item);
    const confirm=f.scanner.details.querySelector('[data-details-save]');
    assert.equal(confirm.textContent,'Choose condition to continue');
    confirm.click(); await tick();
    assert.equal(f.dom.window.document.activeElement.getAttribute('aria-label'),'Condition');
    assert.equal(f.calls.length,1,'No write before condition is chosen');
    assert.match(f.scanner.details.textContent,/Market value unavailable/);
    const condition=f.scanner.details.querySelector('select'); condition.value='Near Mint';
    condition.dispatchEvent(new f.w.Event('change'));
    assert.equal(confirm.textContent,'Looks Good');
    await f.scanner.confirmDetails(); f.scanner.showReview();
    assert.equal(f.scanner.find('[data-action="save"]').disabled,false);
    await f.scanner.saveAll();
    assert.equal(item.status,'added');
    const selected=f.calls.find(call=>call.url.endsWith('/references/select'));
    assert.deepEqual(JSON.parse(selected.body),reference);
    const feedback=f.calls.find(call=>call.url.endsWith('/feedback'));
    assert.equal(JSON.parse(feedback.body).outcome,'CORRECTED_BY_SEARCH');
    assert.equal(item.selected.market_value_minor,null);
    f.finish(); checks+=1;
  }
  // Closest printings are shown first; low-scoring alternatives remain reachable.
  {
    const data=result(); data.candidates=[.86421,.85971,.74595,.62,.55,.2].map((score,index)=>({
      ...data.candidates[0],id:'candidate-'+index,rank:index+1,score,candidate_snapshot:{name:'Choice '+index}}));
    const f=fixture('seller',async()=>data); await f.scanner.recognise('photo'); f.scanner.openDetails(f.scanner.items[0]);
    assert.equal(f.scanner.details.querySelectorAll('.dr-scan-alternative').length,2);
    [...f.scanner.details.querySelectorAll('button')].find(b=>b.textContent==='Show other suggestions').click();
    assert.equal(f.scanner.details.querySelectorAll('.dr-scan-alternative').length,6);
    f.finish(); checks+=1;
  }
  // Each thumbnail can switch raw/graded without saving until explicit confirmation.
  for (const role of ['seller', 'founder']) {
    const f=fixture(role,async url => url.endsWith('/resolve') ? result() : {inventory:{inventory_code:'INV-GRADED'}});
    const item=await matched(f.scanner,2); f.scanner.openDetails(item);
    const press=company=>f.scanner.details.querySelector('[data-grader="'+company+'"]').click();
    press('PSA');
    assert.equal(item.mode,'RAW','The unfinished grading choice is local');
    assert.equal(f.scanner.edit.quantity,1);
    assert.doesNotMatch(f.scanner.details.querySelector('.dr-scan-detail-identity').textContent,/£15/);
    assert.ok(f.scanner.details.querySelector('[data-details-save]').disabled);
    const grade=f.scanner.details.querySelector('[aria-label="Grade"]');
    assert.ok(![...grade.options].some(option=>option.value==='9.5'));
    grade.value='10';grade.dispatchEvent(new f.w.Event('change'));
    const certificate=f.scanner.details.querySelector('[aria-label="Certificate number"]');
    certificate.value='12345678';certificate.dispatchEvent(new f.w.Event('input'));
    press('BGS');
    assert.equal(f.scanner.edit.certificate_number,'','Never transfer a certificate to another grader');
    assert.equal(f.scanner.edit.grade,'');
    assert.ok([...f.scanner.details.querySelector('[aria-label="Grade"]').options].some(option=>option.value==='10 BLACK LABEL'));
    press(''); assert.equal(f.scanner.edit.quantity,2); assert.equal(f.scanner.edit.condition,'Near Mint');
    press('TAG');
    const tagGrade=f.scanner.details.querySelector('[aria-label="Grade"]');tagGrade.value='Pristine 10';tagGrade.dispatchEvent(new f.w.Event('change'));
    const tagCert=f.scanner.details.querySelector('[aria-label="Certificate number"]');tagCert.value='A1234567';tagCert.dispatchEvent(new f.w.Event('input'));
    await f.scanner.confirmDetails();
    assert.equal(item.mode,'GRADED');assert.equal(item.condition,null);assert.equal(item.quantity,1);
    assert.equal(f.scanner.totals().value,null,'Raw market value must not inflate slab total');
    f.scanner.showReview();await f.scanner.saveAll();
    const saved=f.calls.find(call=>call.headers?.['Idempotency-Key']);
    assert.deepEqual(JSON.parse(saved.body),{selected_catalogue_id:'card-1',grading_company:'TAG',grade:'Pristine 10',certificate_number:'A1234567',language:'English'});
    assert.equal(f.calls.some(call=>call.url.endsWith('/feedback')),false);
    assert.equal(saved.url,role==='seller'?'/api/v1/owner/graded-certificate-intake':'/api/v1/inventory/graded-intake');
    f.finish();checks+=1;
  }
  // A second photo starts before the first completes; results stay on their own thumbnails.
  {
    const first=deferred(),second=deferred();let count=0;
    const f=fixture('seller',()=>++count===1?first.promise:second.promise);
    const p1=f.scanner.recognise('photo-one');await tick();
    assert.equal(f.scanner.find('[data-action="gallery"]').disabled,false);
    const p2=f.scanner.recognise('photo-two');await tick();
    await f.scanner.recognise('over-capacity');
    assert.equal(f.scanner.items.length,2);assert.equal(count,2);
    assert.equal(f.scanner.find('[data-action="gallery"]').disabled,true);
    second.resolve(result({run:{id:'run-two',decision:'EXACT_CANDIDATE',top_catalogue_id:'card-1'}}));await p2;
    assert.equal(f.scanner.items[1].run.id,'run-two');assert.equal(f.scanner.items[0].status,'processing');
    assert.equal(f.scanner.find('[data-action="gallery"]').disabled,false);
    f.scanner.openDetails(f.scanner.items[1]);assert.ok(f.scanner.edit);
    first.reject(new Error('First photo failed'));await p1;
    assert.equal(f.scanner.items[0].status,'unresolved');assert.equal(f.scanner.items[1].run.id,'run-two');
    assert.equal(f.scanner.inFlight,0);f.finish();checks+=1;
  }
  // Failed retries discard old evidence; a previous successful run cannot be confirmed again.
  {
    let fail=false;const f=fixture('seller',async()=>{if(fail)throw new Error('Offline');return result();});
    const item=await matched(f.scanner);fail=true;await f.scanner.recognise('photo',item);
    f.scanner.openDetails(item);assert.equal(item.run,null);assert.equal(item.selected,null);
    assert.equal(f.scanner.details.querySelector('[data-details-save]').disabled,true);
    f.finish();checks+=1;
  }
  // Both roles search the complete released catalogue, with independent language/game filters.
  for(const role of ['seller','founder']) {
    const rows=[{key:'r:first',source_kind:'REFERENCE',provider:'Bandai Official',provider_id:'OP16-041_p1',
      name:'Buggy',card_number:'OP16-041',language:'English',system_code:'ONE_PIECE_CARD_GAME',product_type:'CARD',image_url:'https://example.test/buggy.png'}];
    const f=fixture(role,async url=>url.endsWith('/resolve')?result():url.endsWith('/games')?{items:[
      {system_code:'POKEMON_TCG',game:'Pokémon',languages:['English','Japanese']},
      {system_code:'ONE_PIECE_CARD_GAME',game:'One Piece',languages:['English','Japanese']}]}:
      url.includes('/products?')?{items:rows,has_more:!url.includes('offset=1')}:
      url.endsWith('/references/select')?{catalogue_id:'buggy'}:{});
    const item=await matched(f.scanner);f.scanner.openDetails(item);f.scanner.openSearch();await tick();
    assert.equal(f.scanner.details.querySelectorAll('.dr-scan-game').length,2);
    const game=f.scanner.details.querySelector('[aria-label="Game"]');game.value='ONE_PIECE_CARD_GAME';game.dispatchEvent(new f.w.Event('change'));await tick();
    const language=f.scanner.details.querySelector('[aria-label="Language"]');language.value='Japanese';language.dispatchEvent(new f.w.Event('change'));await tick();
    const search=f.calls.filter(call=>call.url.includes('/products?')).at(-1);
    assert.ok(search.url.includes('owned=all'));assert.ok(search.url.includes('language=Japanese'));assert.ok(search.url.includes('system_code=ONE_PIECE_CARD_GAME'));
    assert.equal(f.scanner.details.querySelectorAll('.dr-scan-search-result').length,1);
    f.scanner.details.querySelector('.dr-scan-search-more').click();await tick();
    assert.ok(f.calls.some(call=>call.url.includes('offset=1')));
    f.scanner.details.querySelector('.dr-scan-search-result').click();await tick();
    assert.equal(f.scanner.edit.selected.reference_selection.provider_id,'OP16-041_p1');
    assert.equal(f.calls.some(call=>call.method==='POST'&&!call.url.endsWith('/resolve')),false,'Choosing a result does not yet write');
    await f.scanner.confirmDetails();assert.equal(item.selected.catalogue_id,'buggy');
    assert.ok(f.calls.some(call=>call.url.endsWith('/references/select')));
    f.finish();checks+=1;
  }
  // Slabs without a raw recognition run can select a released reference before certificate intake.
  for (const role of ['seller','founder']) {
    const f=fixture(role,async url=>url.endsWith('/select')?{catalogue_id:'new-slab-card'}:{inventory:{inventory_code:'INV-NEW-SLAB'}});
    f.scanner.manualSlab();f.scanner.edit.grade='9';f.scanner.edit.certificate_number='12345678';
    await f.scanner.chooseSearch({key:'r:slab',name:'Slab card',source_kind:'REFERENCE',provider:'Bandai Official',
      provider_id:'OP16-041_p1',system_code:'ONE_PIECE_CARD_GAME',language:'English'});
    await f.scanner.confirmDetails();f.scanner.showReview();await f.scanner.saveAll();
    const link=f.calls.find(call=>call.url==='/api/v1/catalogue-browser/select');assert.deepEqual(JSON.parse(link.body),{key:'r:slab',confirmed:true});
    const save=f.calls.find(call=>call.headers?.['Idempotency-Key']);assert.equal(JSON.parse(save.body).selected_catalogue_id,'new-slab-card');
    f.finish();checks+=1;
  }
  // Closing grading details cancels the local change; sealed products never expose graders.
  {
    const f=fixture('seller',async()=>result());const item=await matched(f.scanner,3);
    f.scanner.openDetails(item);f.scanner.chooseGrader('CGC');f.scanner.closeDetails();
    assert.equal(item.mode,'RAW');assert.equal(item.quantity,3);assert.equal(item.grading_company,undefined);
    f.scanner.openDetails(item);assert.equal(f.scanner.edit.mode,'RAW');
    item.selected.candidate_snapshot.product_type='SEALED';f.scanner.renderDetails();
    assert.equal(f.scanner.details.querySelector('.dr-scan-graders'),null);
    f.finish();checks+=1;
  }
  // Manual provider lookup preserves the grade entered and leaves the draft uncommitted.
  {
    const f=fixture('seller',async()=>({provider:'TAG',certificate_number:'A1234567',verified:false,status:'MANUAL_VERIFICATION_REQUIRED'}));
    f.scanner.manualSlab();f.scanner.chooseGrader('TAG');
    Object.assign(f.scanner.edit,{grade:'Pristine 10',certificate_number:'A1234567',selected:{catalogue_id:'card'}});
    await f.scanner.lookupSlab();
    assert.equal(f.scanner.edit.grade,'Pristine 10');assert.equal(f.scanner.edit.slab.verified,false);
    assert.equal(f.scanner.edit.item.grading_company,'PSA','Lookup must not commit the draft choice');
    f.finish();checks+=1;
  }
  await tick();
  console.log('Scanner flow: ' + checks + ' interaction, permission and retry scenarios passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
