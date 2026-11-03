const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '../../backend/app/static');
const source = fs.readFileSync(path.join(root, 'scan-photos.js'), 'utf8');
const scannerSource = fs.readFileSync(path.join(root, 'scanner-flow.js'), 'utf8');
const valueSource = fs.readFileSync(path.join(root, 'reference-value-display.js'), 'utf8');
const capture = 'data:image/jpeg;base64,' + Buffer.from('exact captured physical photograph').toString('base64');
let checks = 0;
function fixture() {
  const dom = new JSDOM('<button id="launch">Scan</button>', {url:'https://example.test', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLDialogElement.prototype.showModal = function(){this.open=true;};
  w.HTMLDialogElement.prototype.close = function(){this.open=false;};
  w.HTMLMediaElement.prototype.play = async()=>{};
  w.URL.createObjectURL=()=> 'blob:photo'; w.URL.revokeObjectURL=()=>{};
  w.fetch=async()=>({ok:false});
  w.eval(source);
  return {w,dom,photos:w.DropRateScanPhotos,close:()=>dom.window.close()};
}
const receipt = (side='FRONT', status='READY') => ({id:'asset-'+side,side,version:2,
  shopify_file_status:status,approval_status:'PENDING',rights_status:'PENDING'});
async function bytes(w, blob) {
  return new Promise((resolve,reject)=>{const reader=new w.FileReader();reader.onload=()=>resolve(Buffer.from(reader.result));reader.onerror=reject;reader.readAsArrayBuffer(blob);});
}

(async()=>{
  // A scan is transmitted as the original file bytes, scoped to its exact copy.
  {
    const f=fixture(),draft=f.photos.create(capture),calls=[];
    const result=await f.photos.attach({inventory:{id:'copy-1',version:4},drafts:[draft],request:async(url,options)=>{
      calls.push({url,options});assert.equal(options.method,'POST');assert.equal(options.headers['Content-Type'],'image/jpeg');
      assert.equal((await bytes(f.w,options.body)).toString(),'exact captured physical photograph');
      const parsed=new URL(url,'https://example.test');assert.equal(parsed.pathname,'/api/v1/owner/inventory/copy-1/photo/upload');
      assert.equal(parsed.searchParams.get('side'),'FRONT');assert.equal(parsed.searchParams.get('version'),'4');
      assert.equal(parsed.searchParams.get('rights_confirmed'),'true');assert.equal(parsed.searchParams.get('request_key'),draft.requestKey);
      return {asset:receipt()};
    }});
    assert.equal(result.complete,true);assert.equal(result.saved,1);assert.equal(draft.asset.approval_status,'PENDING');
    assert.equal(calls.length,1);f.close();checks++;
  }
  // A lost response uses the same upload receipt and bytes; no inventory call.
  {
    const f=fixture(),draft=f.photos.create(capture),urls=[];let attempts=0;
    const options={inventory:{id:'copy-2',version:3},drafts:[draft],request:async url=>{
      urls.push(url);if(++attempts===1)throw new Error('Connection interrupted');return {asset:receipt()};}};
    assert.equal((await f.photos.attach(options)).complete,false);assert.equal(draft.dataUrl,capture);
    assert.equal((await f.photos.attach(options)).complete,true);assert.equal(urls[0],urls[1]);f.close();checks++;
  }
  // Received files resume processing instead of creating another Shopify file.
  {
    const f=fixture(),draft=f.photos.create(capture),calls=[];
    const result=await f.photos.attach({inventory:{id:'copy-3',version:1},drafts:[draft],request:async url=>{
      calls.push(url);return url.endsWith('/photos/refresh')?{items:[receipt()]}:{asset:receipt('FRONT','NOT_UPLOADED')};}});
    assert.equal(result.complete,true);assert.equal(calls.length,2);
    await f.photos.attach({inventory:{id:'copy-3',version:1},drafts:[draft],request:async()=>{throw new Error('Already saved photo must not be uploaded again');}});
    f.close();checks++;
  }
  // A receipt cannot be silently reused for a different physical copy.
  {
    const f=fixture(),draft=f.photos.create(capture);
    await f.photos.attach({inventory:{id:'copy-first',version:1},drafts:[draft],request:async()=>({asset:receipt()})});
    await assert.rejects(f.photos.attach({inventory:{id:'copy-other',version:1},drafts:[draft],
      request:async()=>{throw new Error('A receipt cannot move to another physical copy');}}),/another saved copy/);
    f.close();checks++;
  }
  // Extra barcode/interior evidence stays identification-only unless selected.
  {
    const f=fixture(),drafts=f.photos.sync([capture,capture+'AAAA']);
    assert.deepEqual(Array.from(f.photos.choice(drafts[0]).querySelectorAll('option'),option=>option.value),
      ['FRONT','BACK','IDENTIFICATION_ONLY']);
    assert.throws(()=>f.photos.validate([f.photos.create(capture,'OTHER')]),/Choose how to use each photo/);
    const sameImages=f.photos.sync([capture,capture]);
    const synced=f.photos.sync([capture,capture],sameImages);
    assert.equal(synced[0].side,'FRONT');assert.equal(synced[1].side,'IDENTIFICATION_ONLY');
    assert.notEqual(synced[0],synced[1]);
    const choice=f.photos.choice(drafts[0]).querySelector('select'),originalKey=drafts[0].requestKey;
    choice.value='BACK';choice.dispatchEvent(new f.w.Event('change'));
    assert.notEqual(drafts[0].requestKey,originalKey,'A different side needs a different exact receipt key');
    drafts[0].side='FRONT';
    assert.equal(drafts[0].side,'FRONT');assert.equal(drafts[1].side,'IDENTIFICATION_ONLY');
    const firstKey=drafts[0].requestKey;assert.equal(f.photos.sync([capture],drafts)[0].requestKey,firstKey);
    drafts[0].side='IDENTIFICATION_ONLY';
    assert.equal((await f.photos.attach({drafts,request:async()=>{throw new Error('Identification-only should not upload');}})).saved,0);
    drafts[0].side='FRONT';drafts[1].side='FRONT';assert.throws(()=>f.photos.validate(drafts),/one photo for each side/);
    f.close();checks++;
  }
  // Selecting the same image twice must not merge its independent photo drafts
  // when the book form redraws after a side choice or partial upload receipt.
  {
    const f=fixture();let drafts=f.photos.sync([capture,capture]);
    const front=drafts[0],back=drafts[1],keys=drafts.map(draft=>draft.requestKey);
    assert.notEqual(front,back);assert.notEqual(keys[0],keys[1]);
    const select=f.photos.choice(back).querySelector('select');
    select.value='BACK';select.dispatchEvent(new f.w.Event('change'));
    assert.notEqual(back.requestKey,keys[1],'Changing the side creates a distinct receipt key');
    keys[1]=back.requestKey;
    front.asset=receipt('FRONT');back.error='Back upload interrupted';
    drafts=f.photos.sync([capture,capture],drafts);
    assert.equal(drafts[0],front);assert.equal(drafts[1],back);
    assert.deepEqual(Array.from(drafts,draft=>draft.side),['FRONT','BACK']);
    assert.deepEqual(Array.from(drafts,draft=>draft.requestKey),Array.from(keys));
    assert.equal(drafts[0].asset.side,'FRONT');assert.equal(drafts[1].asset,null);
    assert.equal(drafts[1].error,'Back upload interrupted');
    const calls=[];
    const result=await f.photos.attach({inventory:{id:'duplicate-photo-copy',version:1},drafts,request:async url=>{
      const query=new URL(url,'https://example.test').searchParams;calls.push(url);
      assert.equal(query.get('side'),'BACK');assert.equal(query.get('request_key'),keys[1]);
      return {asset:receipt('BACK')};}});
    assert.equal(result.complete,true);assert.equal(calls.length,1);
    drafts=f.photos.sync([capture,capture],drafts);
    assert.equal(drafts[0],front);assert.equal(drafts[1],back);
    assert.notEqual(drafts[0].asset,drafts[1].asset);
    assert.deepEqual(Array.from(drafts,draft=>draft.asset.side),['FRONT','BACK']);
    // Even an already-aliased prior array cannot reuse one receipt twice.
    const repaired=f.photos.sync([capture,capture],[front,front]);
    assert.equal(repaired[0],front);assert.notEqual(repaired[1],front);
    assert.notEqual(repaired[1].requestKey,front.requestKey);assert.equal(repaired[1].asset,null);
    assert.equal(repaired[1].side,'IDENTIFICATION_ONLY');
    f.close();checks++;
  }
  // A second side failing keeps the first receipt, and retry sends only that side.
  {
    const f=fixture(),drafts=[f.photos.create(capture),f.photos.create(capture,'BACK')];let failBack=true;const sides=[];
    const options={inventory:{id:'copy-4',version:1},drafts,request:async url=>{
      const side=new URL(url,'https://example.test').searchParams.get('side');sides.push(side);
      if(side==='BACK'&&failBack)throw new Error('Back upload interrupted');return {asset:receipt(side)};}};
    assert.equal((await f.photos.attach(options)).saved,1);failBack=false;assert.equal((await f.photos.attach(options)).complete,true);
    assert.deepEqual(sides,['FRONT','BACK','BACK']);f.close();checks++;
  }
  // Account changes stop the next upload and cannot accept a stale response.
  {
    const f=fixture(),drafts=[f.photos.create(capture),f.photos.create(capture,'BACK')];let active=true,calls=0;
    await assert.rejects(f.photos.attach({inventory:{id:'copy-5',version:1},drafts,active:()=>active,request:async()=>{
      calls++;active=false;return {asset:receipt()};}}),/account changed/);
    assert.equal(calls,1);assert.equal(drafts[0].asset,null);f.close();checks++;
  }
  // Existing successful intake is kept when photo upload fails. The photo-only
  // retry never repeats feedback or intake and clears bytes only after success.
  for (const quantity of [1,3]) {
    const f=fixture(),calls=[];let intakeCount=0,failPhoto=true;
    f.w.eval(valueSource);f.w.eval(scannerSource);
    const scan=new f.w.DropRateScanner.Scanner({role:'seller',session:()=>({access_token:'test',user:{id:'owner-a'}}),
      afterSave:async()=>{},viewInventory:()=>{},request:async(url,options)=>{
        calls.push(url);
        if(url==='/api/v1/recognition/resolve')return {run:{id:'run-1',decision:'EXACT_CANDIDATE',top_catalogue_id:'card-1'},
          candidates:[{id:'candidate-1',catalogue_id:'card-1',rank:1,source_kind:'CATALOGUE',market_value_minor:1000,
            candidate_snapshot:{name:'Physical card',game:'One Piece',language:'English',product_type:'CARD'}}]};
        if(url.endsWith('/feedback'))return {};
        if(url==='/api/v1/owner/recognition-intake'){intakeCount++;return {inventory:{id:'copy-'+intakeCount,inventory_code:'INV-'+intakeCount,version:1}};}
        if(url.includes('/photo/upload?')){if(failPhoto)throw new Error('Network dropped');return {asset:receipt()};}
        throw new Error('Unexpected request '+url);
      }});
    await scan.recognise(capture);const item=scan.items[0];item.quantity=quantity;scan.showReview();
    assert.match(scan.review.textContent,/Adding confirms you can use this photo|Your photo is saved to the first copy/);
    await scan.saveAll();assert.equal(item.status,'added');assert.equal(item.photoPending,true);
    assert.equal(intakeCount,quantity);assert.equal(item.photo,capture);assert.match(scan.review.textContent,/Item added.*Network dropped/);
    failPhoto=false;await scan.retryScanPhoto(item);assert.equal(intakeCount,quantity);
    assert.equal(item.status,'added');assert.equal(item.photoPending,false);assert.equal(item.photo,null);assert.equal(item.photoDraft.dataUrl,null);
    assert.equal(calls.filter(url=>url.endsWith('/feedback')).length,1);
    assert.ok(calls.filter(url=>url.includes('/photo/upload?')).every(url=>url.startsWith('/api/v1/owner/inventory/copy-1/')));
    scan.destroy();f.close();checks++;
  }
  // One photo retry must not hide another item's remaining photo failure.
  {
    const f=fixture();f.w.eval(valueSource);f.w.eval(scannerSource);let intakes=0;const allowed=new Set();
    const scan=new f.w.DropRateScanner.Scanner({role:'seller',session:()=>({access_token:'test',user:{id:'owner-a'}}),
      afterSave:async()=>{},viewInventory:()=>{},request:async(url)=>{
        if(url==='/api/v1/recognition/resolve')return {run:{id:'run',decision:'EXACT_CANDIDATE',top_catalogue_id:'card'},
          candidates:[{id:'candidate',catalogue_id:'card',rank:1,source_kind:'CATALOGUE',candidate_snapshot:{name:'Synthetic card',language:'English',product_type:'CARD'}}]};
        if(url.endsWith('/feedback'))return {};
        if(url==='/api/v1/owner/recognition-intake')return {inventory:{id:'copy-'+(++intakes),inventory_code:'INV-'+intakes,version:1}};
        if(url.includes('/photo/upload?')){if(!allowed.has(url.split('/')[5]))throw new Error('Photo interrupted');return {asset:receipt()};}
        throw new Error('Unexpected request '+url);
      }});
    await scan.recognise(capture);await scan.recognise(capture);scan.showReview();await scan.saveAll();
    assert.equal(intakes,2);assert.ok(scan.items.every(item=>item.status==='added'&&item.photoPending));
    allowed.add('copy-1');await scan.retryScanPhoto(scan.items[0]);
    assert.equal(scan.items[0].photoPending,false);assert.equal(scan.items[1].photoPending,true);
    assert.match(scan.find('.dr-scan-save-message').textContent,/1 photo still needs retrying/);
    allowed.add('copy-2');await scan.retryScanPhoto(scan.items[1]);
    assert.match(scan.find('.dr-scan-save-message').textContent,/Photo saved for review/);
    assert.doesNotMatch(scan.find('.dr-scan-save-message').textContent,/needs? retrying/);
    assert.equal(intakes,2);scan.destroy();f.close();checks++;
  }
  console.log(`Scan photo checks passed: ${checks} upload, recovery, owner isolation and inventory hand-off groups.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
