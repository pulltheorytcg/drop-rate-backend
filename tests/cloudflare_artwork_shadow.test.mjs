import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,createHmac} from 'node:crypto';
import {handle} from '../cloudflare/artwork-shadow/worker.mjs';

const secret='A-TEST-SECRET-WITH-AT-LEAST-32-CHARACTERS';
const hash=x=>createHash('sha256').update(x).digest('hex');
const referenceKey=(p,s,l,id)=>'x:'+hash(JSON.stringify([p,s,l,id]));
const image=new Uint8Array(32);
image.set(new TextEncoder().encode('RIFF'),0);
image.set(new TextEncoder().encode('WEBP'),8);
const digest=hash(image);
const base={
  schema_version:1,action:'STAGE_VERIFIED_ARTWORK',
  provider:'ygoprodeck',system_code:'YUGIOH',language:'English',provider_id:'pass-set-rare',
  set_id:'ABC-EN',card_number:'001',rarity:'Rare',finish:'Normal',
  source_manifest_sha256:'a'.repeat(64),rights_review_id:'retailer-license-reviewed',
  content_sha256:digest,size_bytes:image.length,object_key:'drop-rate/private-media/'+digest+'.webp',
  reference_key:referenceKey('ygoprodeck','YUGIOH','English','pass-set-rare')
};
function env({wrongBytes=false,missing=false,type='image/webp',size=image.length}={}) {
  const saved=new Map();
  const r2={get:async key=>(missing?null:({
    size,httpMetadata:{contentType:type},
    arrayBuffer:async()=>wrongBytes?new Uint8Array(32).buffer:image.buffer
  }))};
  const d1={prepare:sql=>({bind:(...args)=>({
    first:async()=>{
      const row=saved.get(args[0]+' '+args[1]);
      return row??null;
    },
    run:async()=>{
      const names=['reference_key','provider','system_code','language','provider_id','set_id','card_number',
        'rarity','finish','source_manifest_sha256','object_key','content_sha256','size_bytes','rights_review_id','state'];
      const row=Object.fromEntries(names.map((k,i)=>[k,args[i]]));
      const key=row.reference_key+' '+row.source_manifest_sha256;
      if(saved.has(key))return {meta:{changes:0}};
      saved.set(key,row);return {meta:{changes:1}};
    }
  })})};
  return {ARTWORK_COMMAND_SECRET:secret,ARTWORK_R2:r2,ARTWORK_D1:d1,saved};
}
async function request(data,env,override={}) {
  const raw=JSON.stringify(data),timestamp=String(Math.floor(Date.now()/1000));
  const hmac='sha256='+createHmac('sha256',secret).update(timestamp+'.'+raw).digest('hex');
  const headers={'content-type':'application/json','x-drop-rate-timestamp':timestamp,
    'x-drop-rate-signature':hmac,...override};
  return handle(new Request('https://internal.example/v1/internal/artwork/shadow',{method:'POST',
    headers,body:raw}),env);
}

test('exact first R2 image byte SHA stages privately in D1, repeat is idempotent',async()=>{
  const e=env();
  const r=await request(base,e);
  assert.equal(r.status,200);
  assert.deepEqual(await r.json(),{accepted:true,state:'SHADOW_ONLY',unchanged:false,
    reference_key:base.reference_key,content_sha256:digest});
  assert.equal(e.saved.size,1);
  const again=await request(base,e);
  assert.equal((await again.json()).unchanged,true);
  assert.equal(e.saved.size,1);
});

test('changed printing under same stable source identity never overwrites',async()=>{
  const e=env();
  await request(base,e);
  const mismatch=await request({...base,card_number:'999'},e);
  assert.equal(mismatch.status,409);
  assert.equal((await mismatch.json()).reason,'SHADOW_IMAGE_CONFLICT');
  assert.equal(e.saved.size,1);
});

test('wrong reference ID, corrupt R2 image, unknown object and invalid format never write',async()=>{
  for(const [change,options] of [
    [{reference_key:'x:'+'0'.repeat(64)},{}],
    [{}, {wrongBytes:true}],
    [{}, {missing:true}],
    [{}, {type:'image/png'}],
    [{}, {size:15}],
    [{object_key:'drop-rate/private-media/'+digest+'.png'},{}],
    [{source_manifest_sha256:'not-a-sha'},{}],
    [{set_id:''},{}],
  ]){
    const e=env(options);
    const r=await request({...base,...change},e);
    assert.ok(r.status>=400);
    assert.equal(e.saved.size,0);
  }
});

test('bad HMAC and expired timestamp never access media or D1',async()=>{
  const e=env();
  e.ARTWORK_R2={get:()=>{throw new Error('must not be accessed')}};
  const r=await request(base,e,{'x-drop-rate-signature':'sha256='+'0'.repeat(64)});
  assert.equal(r.status,401);assert.equal(e.saved.size,0);
  const r2=await request(base,e,{'x-drop-rate-timestamp':'1000000000'});
  assert.equal(r2.status,401);assert.equal(e.saved.size,0);
});

test('non-stage routes and GET requests are closed',async()=>{
  const e=env();
  assert.equal((await handle(new Request('https://internal.example/public/image'),e)).status,404);
  assert.equal((await handle(new Request('https://internal.example/v1/internal/artwork/shadow'),e)).status,405);
  assert.equal(e.saved.size,0);
});

test('no Worker can publish images or change owner prices/Shopify',async()=>{
  const e=env();
  await request(base,e);
  const row=[...e.saved.values()][0];
  assert.equal(row.state,'STAGED_PRIVATE');
  assert.equal('price' in row,false);
  assert.equal('owner_id' in row,false);
  assert.equal('shopify_product_id' in row,false);
});
