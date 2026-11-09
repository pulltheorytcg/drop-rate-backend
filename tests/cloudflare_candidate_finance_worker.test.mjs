/* Offline synthetic tests: NO Cloudflare network, source owner, or payment. */
import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker,{PATH,plan,ORDER_SQL,INBOX_SQL,LINE_SQL,OUTBOX_SQL,
  REFUND_SQL,EVIDENCE_SQL} from "../cloudflare/operational-candidate-finance/worker.mjs";

const SECRET="a1".repeat(32);
const UUIDS={
  order:"11111111-1111-4111-8111-111111111111",
  item:"22222222-2222-4222-8222-222222222222",
  other:"33333333-3333-4333-8333-333333333333",
  stock:"44444444-4444-4444-8444-444444444444",
  stock2:"55555555-5555-4555-8555-555555555555",
  owner:"66666666-6666-4666-8666-666666666666",
  owner2:"77777777-7777-4777-8777-777777777777",
  refund:"88888888-8888-4888-8888-888888888888",
};
const NOW=()=>new Date().toISOString().replace("Z","000Z");
const URL="https://candidate-finance.example.workers.dev"+PATH;

function sale() {
  return {kind:"SALE",event:{
    order_id:UUIDS.order,source:"SHOPIFY",source_reference:"order-100",
    webhook_id:"hook-100",shop_domain:"shop.example.com",
    payload_sha256:"b2".repeat(32),placed_at:NOW(),
    lines:[
      {id:UUIDS.item,inventory_id:UUIDS.stock,owner_id:UUIDS.owner,
       expected_inventory_version:1,sale_price_minor:200,
       discount_minor:1,cost_basis_minor:50,commission_bps_snapshot:0,
       commission_minor:0},
      {id:UUIDS.other,inventory_id:UUIDS.stock2,owner_id:UUIDS.owner2,
       expected_inventory_version:6,sale_price_minor:300,
       discount_minor:0,cost_basis_minor:null,commission_bps_snapshot:1000,
       commission_minor:30},
    ],
  }};
}
function refund() {
  return {kind:"CARD_REFUND",event:{
    id:UUIDS.refund,source:"SHOPIFY",source_reference:"refund-100",
    order_id:UUIDS.order,order_item_id:UUIDS.item,
    inventory_id:UUIDS.stock,owner_id:UUIDS.owner,card_amount_minor:199,
    return_to_inspection:true,payload_sha256:"b2".repeat(32),occurred_at:NOW(),
  }};
}
function money(kind) {
  return {kind,event:{
    id:UUIDS.refund,source:"SHOPIFY",source_reference:"ref-100",
    order_id:UUIDS.order,order_item_id:UUIDS.item,owner_id:UUIDS.owner,
    amount_minor:123,payload_sha256:"c3".repeat(32),occurred_at:NOW(),
  }};
}
function fakeDb({fail=false,truncate=false}={}) {
  const calls=[];
  return {
    calls,
    prepare(sql) {
      assert.ok([ORDER_SQL,INBOX_SQL,LINE_SQL,OUTBOX_SQL,REFUND_SQL,
        ...Object.values(EVIDENCE_SQL)].includes(sql));
      return {bind(...values){return {sql,values};}};
    },
    async batch(statements) {
      calls.push(statements);
      if (fail) throw new Error("secret: private customer money SQL");
      return (truncate?statements.slice(0,-1):statements)
        .map(()=>({success:true}));
    },
  };
}
function signed(payload,{secret=SECRET,delay=0,method="POST",
                 path=PATH,type="application/json",extraHeaders={},
                 untrustedBody=null}={}) {
  const body=JSON.stringify(payload);
  const timestamp=String(Math.floor(Date.now()/1000)+delay);
  const data="POST\n"+PATH+"\n"+timestamp+"\n"+body;
  const hash=createHmac("sha256",Buffer.from(secret,"hex"))
    .update(data).digest("hex");
  const headers={
    "Content-Type":type,
    "X-DR-Timestamp":timestamp,
    "X-DR-Signature":"sha256="+hash,
    ...extraHeaders,
  };
  return new Request("https://candidate-finance.example.workers.dev"+path,{
    method,headers,body:method==="POST"?(untrustedBody??body):undefined,
  });
}
function env(db=fakeDb(),stage="true") {
  return {DR_CANDIDATE_STAGE_ENABLED:stage,DR_CANDIDATE_DB:db,
    DR_FINANCE_HMAC_SECRET:SECRET};
}
async function reply(req,settings) {
  const response=await worker.fetch(req,settings);
  return {status:response.status,data:await response.json(),headers:response.headers};
}

test("accepted mixed-owner sale uses ONE fixed-source D1 batch; ledger is trigger-owned", async()=>{
  const db=fakeDb();const msg=sale(), r=await reply(signed(msg),env(db));
  assert.equal(r.status,200);
  assert.equal(r.data.status,"CANDIDATE_ATOMIC_EVENT_COMMITTED");
  assert.equal(r.data.authority,"STAGING_ONLY");
  assert.equal(r.data.automatic_payout,false);
  assert.equal(db.calls.length,1);
  const q=db.calls[0];
  assert.equal(q.length,5);
  assert.deepEqual(q.map(x=>x.sql),[ORDER_SQL,INBOX_SQL,LINE_SQL,LINE_SQL,OUTBOX_SQL]);
  assert.equal(q[2].values[3],UUIDS.owner);
  assert.equal(q[3].values[3],UUIDS.owner2);
  assert.equal(q[3].values[10],30);
  assert.ok(q.every(x=>!x.sql.includes("DROP TABLE")));
  assert.equal(r.headers.get("Cache-Control"),"no-store, private");
  assert.equal(r.headers.get("Access-Control-Allow-Origin"),null);
});

test("staging requires explicit separate D1 binding and enablement",async()=>{
  for (const st of ["false",null,"TRUE",""]){
    const db=fakeDb(), r=await reply(signed(sale()),env(db,st));
    assert.equal(r.status,503);assert.equal(db.calls.length,0);
  }
  const r=await reply(signed(sale()),{DR_CANDIDATE_STAGE_ENABLED:"true",
    DR_FINANCE_HMAC_SECRET:SECRET});
  assert.equal(r.status,503);
});

test("wrong signing key, changed body, missing HMAC, expired timestamp reject before D1",async()=>{
  const db=fakeDb(), e=env(db);
  const bad=[
    signed(sale(),{secret:"f0".repeat(32)}),
    signed(sale(),{untrustedBody:JSON.stringify(refund())}),
    signed(sale(),{delay:-1000}),
    signed(sale(),{delay:1000}),
    signed(sale(),{extraHeaders:{"X-DR-Signature":"sha256="+"0".repeat(64)}}),
  ];
  for(const request of bad){
    assert.equal((await reply(request,e)).status,401);
  }
  assert.equal(db.calls.length,0);
});

test("requests cannot select paths, methods, content type or query params",async()=>{
  const db=fakeDb(),e=env(db);
  const variants=[
    [signed(sale(),{path:"/internal/v1/other"}),404],
    [signed(sale(),{path:PATH+"?foo=bar"}),404],
    [signed(sale(),{method:"GET"}),404],
    [signed(sale(),{type:"text/plain"}),415],
    [signed(sale(),{extraHeaders:{"Content-Length":"999999"}}),413],
  ];
  for(const [req,expected] of variants)
    assert.equal((await reply(req,e)).status,expected);
  assert.equal(db.calls.length,0);
});

test("untrusted SQL, extra owner claims, unapproved event types cannot reach D1",async()=>{
  const db=fakeDb(),e=env(db);
  const attempts=[
    {...sale(), sql:"DELETE FROM candidate_owners"},
    {kind:"SQL",event:{sql:"SELECT * FROM candidate_owners"}},
    {kind:"SALE",event:{...sale().event,role:"PLATFORM_ADMIN"}},
    {kind:"FUND_TRANSFER",event:money("PAYMENT_FEE").event},
    {kind:"SALE",event:{...sale().event,lines:[{...sale().event.lines[0],sql:"DROP TABLE"}]}},
  ];
  for(const p of attempts)
    assert.equal((await reply(signed(p),e)).status,409);
  assert.equal(db.calls.length,0);
});

test("reject corrupt sale snapshots, duplicate stock and missing/foreign owners",async()=>{
  const db=fakeDb(),e=env(db);
  const base=sale();
  const attempts=[
    {kind:"SALE",event:{...base.event,lines:[...base.event.lines,base.event.lines[0]]}},
    {kind:"SALE",event:{...base.event,lines:[{...base.event.lines[0],owner_id:"bad"}]}},
    {kind:"SALE",event:{...base.event,lines:[{...base.event.lines[0],expected_inventory_version:0}]}},
    {kind:"SALE",event:{...base.event,lines:[{...base.event.lines[0],sale_price_minor:-1}]}},
    {kind:"SALE",event:{...base.event,lines:[{...base.event.lines[0],discount_minor:200}]}},
    {kind:"SALE",event:{...base.event,lines:[{...base.event.lines[0],commission_minor:1.5}]}},
    {kind:"SALE",event:{...base.event,lines:[]}},
  ];
  for(const p of attempts)
    assert.equal((await reply(signed(p),e)).status,409);
  assert.equal(db.calls.length,0);
});

test("only fixed refund event SQL, not a second independent ledger write",async()=>{
  const db=fakeDb(),r=await reply(signed(refund()),env(db));
  assert.equal(r.status,200);assert.equal(db.calls.length,1);
  assert.equal(db.calls[0].length,1);
  assert.equal(db.calls[0][0].sql,REFUND_SQL);
  assert.equal(db.calls[0][0].values[8],1);
});

test("shipping, shipping refund and fee use exact preapproved SQL without guesses",async()=>{
  for(const kind of ["SHIPPING_ALLOCATION","SHIPPING_REFUND","PAYMENT_FEE"]){
    const db=fakeDb();const res=await reply(signed(money(kind)),env(db));
    assert.equal(res.status,200);
    assert.equal(db.calls.length,1);
    assert.equal(db.calls[0].length,1);
    assert.equal(db.calls[0][0].sql,EVIDENCE_SQL[kind]);
    assert.equal(db.calls[0][0].values[6],123);
  }
});

test("invalid refunded pennies, wrong boolean or tainted source SHA fail closed",async()=>{
  const db=fakeDb(),e=env(db);
  const vals=[
    {...refund(),event:{...refund().event,return_to_inspection:1}},
    {...refund(),event:{...refund().event,card_amount_minor:0}},
    {...refund(),event:{...refund().event,payload_sha256:"x"}},
    {...money("PAYMENT_FEE"),event:{...money("PAYMENT_FEE").event,amount_minor:-10}},
    {...money("PAYMENT_FEE"),event:{...money("PAYMENT_FEE").event,owner_id:UUIDS.stock,role:"admin"}},
  ];
  for(const p of vals)
    assert.equal((await reply(signed(p),e)).status,409);
  assert.equal(db.calls.length,0);
});

test("D1 rejection, UNIQUE replay and incomplete batch response do not claim commit",async()=>{
  for(const opts of [{fail:true},{truncate:true}]){
    const db=fakeDb(opts), result=await reply(signed(sale()),env(db));
    assert.equal(result.status,409);
    assert.deepEqual(result.data,{error:"Candidate event rejected; reconcile privately"});
    assert.equal(db.calls.length,1);
    assert.equal(JSON.stringify(result.data).includes("secret"),false);
  }
});

test("plan emits bounded fixed parameterized SQL, not event-supplied strings",()=>{
  const statements=plan(sale());
  assert.equal(statements.length,5);
  assert.equal(statements[2][0],LINE_SQL);
  assert.equal(statements[2][1].length,12);
  assert.equal(statements[4][1].length,4);
  assert.ok(statements.every(([sql,params])=>
    (sql.match(/\?/g)||[]).length===params.length && params.length<=100));
});
