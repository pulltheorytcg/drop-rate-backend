// Live Seller Hub Scan navigation contract. All camera media is stubbed;
// no physical camera, live seller account or API mutation is used in CI.
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');

const root=path.resolve(__dirname,'../../backend/app/static');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

function fixture(){
 const markup=fs.readFileSync(path.join(root,'owner.html'),'utf8').replace(/<script[^>]*><\/script>/g,'');
 const dom=new JSDOM(markup,{url:'https://drop-rate.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,ctx=dom.getInternalVMContext();
 w.scrollTo=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.HTMLMediaElement.prototype.play=async()=>{};
 w.fetch=async()=>({ok:true,json:async()=>({})});
 const run=code=>vm.runInContext(code,ctx);
 for(const filename of ['hub-session.js','owner-portal.js','scanner-flow.js','owner-recognition.js']){
  const source=fs.readFileSync(path.join(root,filename),'utf8')
    .replace(/\ninitialise\(\);\s*$/,'');
  run(source);
 }
 run(`state.session={access_token:'owner-token',user:{id:'seller-a'}};
      document.getElementById('owner-portal-view').classList.remove('hidden');
      document.getElementById('owner-auth-view').classList.add('hidden');`);
 const calls=[];
 let recognitionStatus=deferred();
 run(`apiRequest=async(path)=>{
   window.__recognitionRequests||=[];
   window.__recognitionRequests.push(path);
   if(path==='/api/v1/recognition/status')return window.__recognitionStatus;
   if(path==='/api/v1/grading-certificates/status')return {configured:true};
   return {};
 };`);
 w.__recognitionStatus=recognitionStatus.promise;
 return {
  w,run,calls,
  nav:()=>w.document.querySelector('.owner-nav-item[data-owner-view="scan"]'),
  jump:()=>w.document.querySelector('[data-owner-jump="scan"]'),
  scanner:()=>w.dropRateScanner,
  connect:getUserMedia=>Object.defineProperty(w.navigator,'mediaDevices',{configurable:true,value:{getUserMedia:(constraints)=>{calls.push(constraints);return getUserMedia(constraints);}}}),
  ready:()=>recognitionStatus.resolve({configured:true,vision_model:'verified-vision'}),
  finish:()=>{recognitionStatus.resolve({configured:true,vision_model:'verified-vision'});w.dropRateScanner?.destroy();dom.window.close();}
 };
}
const track=()=>({stopped:0,stop(){this.stopped++;},getCapabilities:()=>({torch:false})});
const stream=t=>({getTracks:()=>[t],getVideoTracks:()=>[t]});

(async()=>{
 let checks=0;
 // A real Scan click starts getUserMedia in that click, not after the
 // recognition-status API request or a second "Open camera" button.
 {
  const f=fixture(),rear=track();f.connect(async()=>stream(rear));
  f.nav().click();
  assert.equal(f.calls.length,1,'Scan navigation must request camera synchronously');
  assert.equal(f.calls[0].video.facingMode.ideal,'environment');
  assert.equal(f.calls[0].audio,false);
  assert.equal(f.w.document.querySelector('.dr-scanner').open,true);
  assert.equal(f.scanner().mode,'RAW');
  assert.ok(f.w.__recognitionRequests.includes('/api/v1/recognition/status'));
  assert.equal(f.w.document.querySelector('#owner-view-scan').classList.contains('hidden'),false);
  await tick();
  assert.ok(f.scanner().stream,'Camera stream should attach without needing status to return');
  assert.equal(f.w.document.querySelector('.dr-scan-camera-resume').hidden,true);
  f.nav().click();assert.equal(f.calls.length,1,'Repeated Scan navigation must not open a second camera');
  // Selecting a different tab must immediately release the hardware.
  f.run("activateOwnerView('inventory',false)");
  assert.ok(rear.stopped>=1);
  assert.equal(f.scanner().dialog.open,false);
  f.ready();await tick();f.finish();checks++;
 }
 // A restored #scan deep link is not a click and must not unexpectedly request camera.
 {
  const f=fixture();f.connect(async()=>stream(track()));
  f.run("activateOwnerView('scan',false)");
  assert.equal(f.calls.length,0);
  assert.equal(f.scanner(),undefined);
  f.ready();await tick();f.finish();checks++;
 }
 // Start camera from secondary Scan buttons too (e.g. welcome/quick actions).
 {
  const f=fixture();const t=track();f.connect(async()=>stream(t));
  f.jump().click();
  assert.equal(f.calls.length,1);
  assert.equal(f.scanner().dialog.open,true);
  await tick();f.scanner().close();assert.ok(t.stopped>=1);
  f.ready();await tick();f.finish();checks++;
 }
 // Permission can arrive after the user leaves: the grant must be stopped
 // and must never leave hardware streaming on a hidden tab.
 {
  const f=fixture(),pending=deferred(),t=track();
  f.connect(()=>pending.promise);
  f.nav().click();assert.equal(f.calls.length,1);
  f.run("activateOwnerView('inventory',false)");
  pending.resolve(stream(t));await tick();await tick();
  assert.equal(f.scanner().stream,null);
  assert.equal(t.stopped,1,'Late camera grant was not released');
  f.ready();await tick();f.finish();checks++;
 }
 // If permission is denied, the scanner keeps an accessible photo fallback.
 {
  const f=fixture();f.connect(async()=>{throw Object.assign(new Error('Denied'),{name:'NotAllowedError'});});
  f.nav().click();assert.equal(f.calls.length,1);
  await tick();await tick();
  assert.match(f.scanner().find('.dr-scan-status').textContent,/Allow camera access/);
  assert.equal(f.scanner().find('[data-action="gallery"]').disabled,false);
  assert.equal(f.scanner().dialog.open,true);
  f.scanner().close();f.ready();await tick();f.finish();checks++;
 }
 // Users can switch cameras or reopen Scan after closing without duplicate
 // streams; pending scans stay available for review.
 {
  const f=fixture(),tracks=[];
  f.connect(async()=>{const t=track();tracks.push(t);return stream(t);});
  f.nav().click();await tick();
  f.scanner().find('[data-action="settings"]').click();
  f.scanner().find('[data-action="switch"]').click();
  await tick();
  assert.equal(f.calls.length,2);
  assert.equal(f.calls[1].video.facingMode.ideal,'user');
  assert.ok(tracks[0].stopped>=1);
  f.scanner().close();assert.ok(tracks[1].stopped>=1);
  f.nav().click();assert.equal(f.calls.length,3);
  await tick();assert.equal(f.scanner().dialog.open,true);
  f.ready();await tick();f.finish();checks++;
 }
 console.log('Seller Scan direct camera: '+checks+' navigation, permissions, late grants, re-entry and camera-switch cases passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
