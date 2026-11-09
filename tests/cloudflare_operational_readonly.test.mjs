/* Offline Node 22 tests. All identities/inventory are synthetic. */
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import worker, { PATH,OWNER_SQL,INVENTORY_SQL } from "../cloudflare/operational-readonly/worker.mjs";

const KEY="a1".repeat(32);
const GEN="src-"+"b".repeat(32);
const USER1="11111111-1111-4111-8111-111111111111";
const USER2="22222222-2222-4222-8222-222222222222";
const OWNER1="33333333-3333-4333-8333-333333333333";
const OWNER2="44444444-4444-4444-8444-444444444444";
const ITEM1="55555555-5555-4555-8555-555555555551";
const ITEM2="55555555-5555-4555-8555-555555555552";
const ROOT="https://unused-private-worker.invalid";
const originalTime = () => Math.floor(Date.now()/1000);
const payload=(user=USER1,limit=2,cursor=null)=>({
  legacy_user_id:user,limit,cursor,
});
const item=(id=ITEM1,owner=OWNER1)=>({
  id,inventory_code:"INV-PKM-123",catalogue_id:USER1,owner_id:owner,
  condition:"Near Mint",grade:null,language:"English",status:"APPROVED",
  version:1,acquisition_cost_minor:350,currency:"GBP",
  market_value_minor:500,store_price_minor:530,
});

class D1Fake {
  constructor({members=[{owner_id:OWNER1,owner_type:"FOUNDER"}],
                stock=[item(),item(ITEM2)]}={}) {
    this.members=members;
    this.stock=stock;
    this.calls=[];
    this.fail=false;
  }
  prepare(sql) {
    assert.ok(sql===OWNER_SQL || sql===INVENTORY_SQL);
    assert.match(sql,/^\s*SELECT/i);
    assert.doesNotMatch(sql,/\b(UPDATE|INSERT|DELETE|DROP|ALTER)\b/i);
    assert.match(OWNER_SQL,/g.state='PARITY_VERIFIED'/);
    assert.match(OWNER_SQL,/count\(\*\).*ops_shadow_table_receipts/s);
    assert.match(OWNER_SQL,/m.legacy_user_id=\?/);
    assert.match(OWNER_SQL,/m.active=1 AND o.active=1/);
    assert.match(INVENTORY_SQL,/generation_id=\? AND owner_id=\? AND id>\?/);
    assert.match(INVENTORY_SQL,/ORDER BY id LIMIT \?/);
    return {
      bind: (...params)=>({
        all: async()=>{
          this.calls.push({sql,params});
          if (this.fail) throw Error("sensitive stack, secret, account id");
          if (sql===OWNER_SQL) return {success:true,results:this.members};
          const [generation,owner,cursor,limit]=params;
          assert.equal(generation,GEN);
          return {success:true,results:this.stock.filter(x=>
            x.owner_id===owner && x.id>cursor).slice(0,limit)};
        },
      }),
    };
  }
}
function env(db=new D1Fake()) {
  return {DR_INTERNAL_HMAC_SECRET:KEY,DR_OPS_GENERATION_ID:GEN,OPS_DB:db};
}
function signed(body=payload(),{time=originalTime(),url=ROOT+PATH,method="POST",
    key=KEY,raw=null,signature=null,contentType="application/json"}={}) {
  const bytes=raw??JSON.stringify(body);
  const canonical="POST\n"+PATH+"\n"+String(time)+"\n"+bytes;
  const calculated="sha256="+createHmac("sha256",Buffer.from(key,"hex"))
    .update(canonical,"utf8").digest("hex");
  return new Request(url,{
    method,headers: {
      "Content-Type":contentType,
      "X-DR-Timestamp":String(time),
      "X-DR-Signature":signature??calculated,
    },
    body:method==="POST"?bytes:undefined,
  });
}
async function call(req,config) {
  const result=await worker.fetch(req,config);
  return {status:result.status,body:await result.json(),headers:result.headers};
}

test("server-signed actor retrieves only own D1 stock under a parity-verified generation",async()=>{
  const d1=new D1Fake();
  const r=await call(signed(),env(d1));
  assert.equal(r.status,200);
  assert.equal(r.body.status,"VERIFIED_READ_ONLY");
  assert.equal(r.body.owner_id,OWNER1);
  assert.equal(r.body.inventory.length,2);
  assert.deepEqual(r.body.inventory.map(x=>x.id),[ITEM1,ITEM2]);
  assert.equal(r.body.owner_type,"FOUNDER");
  assert.equal(r.body.founder_hq_allowed,false);
  assert.equal(r.body.business_allowed,false);
  assert.equal(r.body.next_cursor,ITEM2);
  assert.equal(r.headers.get("Cache-Control"),"no-store, private");
  assert.equal(r.headers.get("Access-Control-Allow-Origin"),null);
  assert.deepEqual(d1.calls[0].params,[GEN,USER1]);
  assert.deepEqual(d1.calls[1].params,[GEN,OWNER1,"",2]);
});

test("consignor can never request founder stock by supplying an owner ID",async()=>{
  const d1=new D1Fake({
    members:[{owner_id:OWNER2,owner_type:"CONSIGNOR"}],
    stock:[item(ITEM1,OWNER1),item(ITEM2,OWNER2)],
  });
  const r=await call(signed(payload(USER2)),env(d1));
  assert.equal(r.status,200);
  assert.deepEqual(r.body.inventory.map(x=>x.id),[ITEM2]);
  assert.equal(r.body.owner_id,OWNER2);
  assert.equal(r.body.business_allowed,false);
  assert.deepEqual(d1.calls[0].params,[GEN,USER2]);
  assert.deepEqual(d1.calls[1].params,[GEN,OWNER2,"",2]);

  const malicious={...payload(USER2),owner_id:OWNER1};
  const rejected=await call(signed(malicious),env(d1));
  assert.equal(rejected.status,400);
  assert.equal(d1.calls.length,2);
});

test("revoked, missing and ambiguous owner membership always fail closed",async()=>{
  for(const [members,status] of [
    [[],403],
    [[{owner_id:OWNER1,owner_type:"FOUNDER"},{owner_id:OWNER2,owner_type:"FOUNDER"}],409],
    [[{owner_id:"bad",owner_type:"FOUNDER"}],503],
  ]) {
    const d1=new D1Fake({members});
    const r=await call(signed(),env(d1));
    assert.equal(r.status,status);
    assert.equal(d1.calls.length,1);
    assert.equal(JSON.stringify(r.body).includes(OWNER1),false);
  }
});

test("unsigned, expired, future-dated and tampered requests never reach database",async()=>{
  const d1=new D1Fake();
  const now=originalTime();
  const variants=[
    signed(payload(),{time:now-130}),
    signed(payload(),{time:now+130}),
    signed(payload(),{signature:"sha256="+"0".repeat(64)}),
    signed(payload(),{key:"f1".repeat(32)}),
    signed(payload(),{raw:JSON.stringify({...payload(),limit:4}),
                      signature:"sha256="+"0".repeat(64)}),
    new Request(ROOT+PATH,{method:"POST",headers:{"Content-Type":"application/json"},
                           body:JSON.stringify(payload())}),
  ];
  for (const req of variants) assert.equal((await call(req,env(d1))).status,401);
  assert.equal(d1.calls.length,0);
});

test("unapproved snapshot, missing D1 binding or secret fail before any D1 read",async()=>{
  const d1=new D1Fake();
  for (const bad of [
    {...env(d1),DR_OPS_GENERATION_ID:"src-invalid"},
    {...env(d1),DR_INTERNAL_HMAC_SECRET:"testing-secret"},
    {...env(d1),OPS_DB:null},
  ]) {
    const r=await call(signed(),bad);
    assert.ok([401,503].includes(r.status));
  }
  assert.equal(d1.calls.length,0);
});

test("invalid body shape, query injection and other routes are not accepted",async()=>{
  const d1=new D1Fake();
  const wrong=[
    signed({...payload(),role:"PLATFORM_ADMIN"}),
    signed({...payload(),legacy_user_id:"' OR 1=1 --"}),
    signed({...payload(),limit:1000}),
    signed({...payload(),cursor:"not-a-uuid"}),
    signed(payload(),{raw:"{not valid json"}),
  ];
  for(const req of wrong) {
    const r=await call(req,env(d1));
    assert.equal(r.status,400);
  }
  assert.equal((await call(signed(payload(),{url:ROOT+PATH+"?debug=true"}),env(d1))).status,404);
  assert.equal((await call(signed(payload(),{method:"GET"}),env(d1))).status,404);
  assert.equal((await call(signed(payload(),{contentType:"text/plain"}),env(d1))).status,415);
  assert.equal(d1.calls.length,0);
});

test("strict cursor ordering and row-owner integrity block corrupt D1 responses",async()=>{
  const db=new D1Fake({stock:[item(ITEM2),item(ITEM1)]});
  const r=await call(signed(),env(db));
  assert.equal(r.status,503);
  assert.equal(r.body.error,"Invalid private inventory");

  const mixed=new D1Fake({members:[{owner_id:OWNER1,owner_type:"FOUNDER"}]});
  mixed.stock=[item(ITEM1,OWNER2)];
  // An unexpected returned row is denied even if the DB adapter malfunctions.
  mixed.prepare=function(sql) {
    return {bind:(...params)=>({all:async()=>(
      sql===OWNER_SQL
        ? {results:[{owner_id:OWNER1,owner_type:"FOUNDER"}]}
        : {results:[item(ITEM1,OWNER2)]}
    )})};
  };
  assert.equal((await call(signed(),env(mixed))).status,503);
});

test("private D1 errors never expose original SQL, tokens or owner identifiers",async()=>{
  const d1=new D1Fake();
  d1.fail=true;
  const r=await call(signed(),env(d1));
  assert.equal(r.status,503);
  assert.equal(r.body.error,"Private D1 read unavailable");
  const payload=JSON.stringify(r.body);
  for(const hidden of ["sensitive stack","secret",OWNER1,USER1,KEY]) {
    assert.ok(!payload.includes(hidden));
  }
});

test("the module has no SQL write operation or public read bypass",async()=>{
  assert.doesNotMatch(OWNER_SQL,/\b(INSERT|UPDATE|DELETE|ALTER|DROP|REPLACE|PRAGMA)\b/i);
  assert.doesNotMatch(INVENTORY_SQL,/\b(INSERT|UPDATE|DELETE|ALTER|DROP|REPLACE|PRAGMA)\b/i);
  const d1=new D1Fake();
  const response=await call(signed(payload(USER1,1,ITEM1)),env(d1));
  assert.equal(response.status,200);
  assert.deepEqual(response.body.inventory.map(x=>x.id),[ITEM2]);
  assert.deepEqual(d1.calls[1].params,[GEN,OWNER1,ITEM1,1]);
});
