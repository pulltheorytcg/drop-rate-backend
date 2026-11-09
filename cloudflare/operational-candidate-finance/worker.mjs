/*
 * INACTIVE isolated D1 FINANCE CANDIDATE transaction worker.
 *
 * NO Wrangler deployment file, public route, Shopify/webhook listener or
 * production D1 binding is created by this module. Enable ONLY in a separate
 * staging environment after backend webhook/owner verification and source
 * freezing rules are independently reviewed. Supabase remains authoritative.
 *
 * Exact HMAC-signed FastAPI event -> fixed statement planner -> one db.batch.
 * No arbitrary SQL, owner lookup, price calculation, payment or payout action.
 * Database candidate triggers own sale/ledger/stock transaction invariants.
 */
const PATH = "/internal/v1/candidate-financial-event";
const MAX_BODY = 65536;
const MAX_SKEW_SECONDS = 90;
const MAX_LINES = 100;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
const EXTERNAL = /^[a-zA-Z0-9][a-zA-Z0-9:._/-]{0,254}$/;
const DOMAIN = /^[a-z0-9](?:[a-z0-9.-]{0,252}[a-z0-9])$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const ENCODER = new TextEncoder();
const MAX_PENNIES = 1_000_000_000_000;

function safeJson(status, body) {
  return new Response(JSON.stringify(body), {
    status, headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, private",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
function exactObject(value, expected) {
  return value !== null && !Array.isArray(value) && typeof value === "object" &&
    Object.keys(value).sort().join(",") === [...expected].sort().join(",");
}
function requireValid(ok) {
  if (!ok) throw new Error("Invalid candidate event envelope");
}
function ref(value) { requireValid(typeof value==="string" && EXTERNAL.test(value)); return value; }
function uuid(value) { requireValid(typeof value==="string" && UUID.test(value)); return value; }
function sha(value) { requireValid(typeof value==="string" && SHA.test(value)); return value; }
function pennies(value, positive=false) {
  requireValid(Number.isSafeInteger(value) && value >= (positive ? 1 : 0) && value<=MAX_PENNIES);
  return value;
}
function at(value) {
  requireValid(typeof value==="string" && UTC.test(value) && !Number.isNaN(Date.parse(value)));
  const normalized = new Date(value).toISOString();
  requireValid(normalized.slice(0, 19)===value.slice(0, 19));
  return value;
}
function source(value) { requireValid(value==="SHOPIFY" || value==="EBAY"); return value; }
function sourceFields(event) {
  return [
    uuid(event.id),source(event.source),ref(event.source_reference),
    uuid(event.order_id),uuid(event.order_item_id),uuid(event.owner_id),
    pennies(event.amount_minor,true),sha(event.payload_sha256),at(event.occurred_at),
  ];
}

const ORDER_SQL = "INSERT INTO candidate_orders (id,source,source_reference,currency,status,placed_at) VALUES(?,?,?,'GBP','RECONCILIATION_REQUIRED',?)";
const INBOX_SQL = "INSERT INTO candidate_webhook_inbox (webhook_id,source,shop_domain,payload_sha256,order_id,received_at) VALUES(?,?,?,?,?,?)";
const LINE_SQL = "INSERT INTO candidate_order_items (id,order_id,inventory_id,owner_id,expected_inventory_version,sale_price_minor,discount_minor,net_sale_minor,cost_basis_minor,commission_bps_snapshot,commission_minor,sold_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)";
const OUTBOX_SQL = "INSERT INTO candidate_outbox (id,order_id,event_type,payload_sha256,status,created_at) VALUES(?,?,'ORDER_POSTED',?,'PENDING',?)";
const REFUND_SQL = "INSERT INTO candidate_card_refunds (id,source,source_reference,order_id,order_item_id,inventory_id,owner_id,card_amount_minor,currency,return_to_inspection,payload_sha256,occurred_at) VALUES(?,?,?,?,?,?,?,?,'GBP',?,?,?)";
const EVIDENCE_SQL = {
  SHIPPING_ALLOCATION: "INSERT INTO candidate_shipping_allocations (id,source,source_reference,order_id,order_item_id,owner_id,amount_minor,currency,payload_sha256,occurred_at) VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
  SHIPPING_REFUND: "INSERT INTO candidate_shipping_refunds (id,source,source_reference,order_id,order_item_id,owner_id,amount_minor,currency,payload_sha256,occurred_at) VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
  PAYMENT_FEE: "INSERT INTO candidate_payment_fees (id,source,source_reference,order_id,order_item_id,owner_id,amount_minor,currency,payload_sha256,occurred_at) VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
};

function plan(payload) {
  requireValid(exactObject(payload,["kind","event"]));
  const {kind,event} = payload;
  requireValid(event!==null && typeof event==="object" && !Array.isArray(event));
  if (kind === "SALE") {
    requireValid(exactObject(event,[
      "order_id","source","source_reference","webhook_id","shop_domain",
      "payload_sha256","placed_at","lines",
    ]));
    const orderId=uuid(event.order_id), src=source(event.source);
    const srcRef=ref(event.source_reference), hook=ref(event.webhook_id);
    requireValid(typeof event.shop_domain==="string" &&
      event.shop_domain === event.shop_domain.toLowerCase() &&
      DOMAIN.test(event.shop_domain));
    const digest=sha(event.payload_sha256), when=at(event.placed_at);
    requireValid(Array.isArray(event.lines) && event.lines.length>=1 &&
      event.lines.length<=MAX_LINES);
    const statements=[
      [ORDER_SQL,[orderId,src,srcRef,when]],
      [INBOX_SQL,[hook,src,event.shop_domain,digest,orderId,when]],
    ];
    const inventoryIds=new Set(), itemIds=new Set();
    for (const line of event.lines) {
      requireValid(exactObject(line,[
        "id","inventory_id","owner_id","expected_inventory_version",
        "sale_price_minor","discount_minor","cost_basis_minor",
        "commission_bps_snapshot","commission_minor",
      ]));
      const itemId=uuid(line.id), itemStock=uuid(line.inventory_id);
      requireValid(!inventoryIds.has(itemStock) && !itemIds.has(itemId));
      inventoryIds.add(itemStock);itemIds.add(itemId);
      const owner=uuid(line.owner_id);
      const version=line.expected_inventory_version;
      requireValid(Number.isSafeInteger(version) && version>=1);
      const price=pennies(line.sale_price_minor,true);
      const discount=pennies(line.discount_minor);
      requireValid(discount < price);
      const cost=line.cost_basis_minor===null?null:pennies(line.cost_basis_minor);
      const bps=line.commission_bps_snapshot, fee=pennies(line.commission_minor);
      requireValid(Number.isSafeInteger(bps) && bps>=0 && bps<=10000);
      // The schema constraint and trigger revalidate the source-supplied
      // commission, cost, active owner, stock status and version in D1 itself.
      statements.push([LINE_SQL,[itemId,orderId,itemStock,owner,version,price,
        discount,price-discount,cost,bps,fee,when]]);
    }
    statements.push([OUTBOX_SQL,["order:"+orderId,orderId,digest,when]]);
    return statements;
  }
  if (kind === "CARD_REFUND") {
    requireValid(exactObject(event,[
      "id","source","source_reference","order_id","order_item_id",
      "inventory_id","owner_id","card_amount_minor","return_to_inspection",
      "payload_sha256","occurred_at",
    ]));
    requireValid(typeof event.return_to_inspection==="boolean");
    return [[REFUND_SQL,[
      uuid(event.id),source(event.source),ref(event.source_reference),
      uuid(event.order_id),uuid(event.order_item_id),uuid(event.inventory_id),
      uuid(event.owner_id),pennies(event.card_amount_minor,true),
      event.return_to_inspection?1:0,sha(event.payload_sha256),at(event.occurred_at),
    ]]];
  }
  if (Object.prototype.hasOwnProperty.call(EVIDENCE_SQL,kind)) {
    requireValid(exactObject(event,[
      "id","source","source_reference","order_id","order_item_id",
      "owner_id","amount_minor","payload_sha256","occurred_at",
    ]));
    return [[EVIDENCE_SQL[kind],sourceFields(event)]];
  }
  throw new Error("Unsupported candidate event");
}

async function authenticated(request, secret, body) {
  if (typeof secret!=="string" || !SHA.test(secret)) return false;
  const timestamp=request.headers.get("X-DR-Timestamp");
  const signature=request.headers.get("X-DR-Signature");
  if (!timestamp || !/^\d{10,12}$/.test(timestamp) ||
      !signature || !/^sha256=[0-9a-f]{64}$/.test(signature)) return false;
  const now=Math.floor(Date.now()/1000), sent=Number(timestamp);
  if (!Number.isSafeInteger(sent) || Math.abs(now-sent)>MAX_SKEW_SECONDS) return false;
  const key=await crypto.subtle.importKey(
    "raw",Uint8Array.from(secret.match(/.{2}/g).map(s=>parseInt(s,16))),
    {name:"HMAC",hash:"SHA-256"},false,["verify"]);
  const data=ENCODER.encode("POST\n"+PATH+"\n"+timestamp+"\n"+body);
  const sig=Uint8Array.from(signature.slice(7).match(/.{2}/g).map(s=>parseInt(s,16)));
  return crypto.subtle.verify("HMAC",key,sig,data);
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if (url.pathname!==PATH || url.search || request.method!=="POST") {
      return safeJson(404,{error:"Not found"});
    }
    if (request.headers.get("Content-Type")!=="application/json") {
      return safeJson(415,{error:"Unsupported content type"});
    }
    const length=request.headers.get("Content-Length");
    if (length && (!/^\d+$/.test(length) || Number(length)>MAX_BODY)) {
      return safeJson(413,{error:"Payload exceeds internal bound"});
    }
    let raw;
    try {raw=await request.text();} catch {return safeJson(400,{error:"Invalid body"});}
    if (ENCODER.encode(raw).length>MAX_BODY) {
      return safeJson(413,{error:"Payload exceeds internal bound"});
    }
    // The worker must be deployed with an ISOLATED candidate D1 binding.
    // Missing stage enablement is always a hard 503, never a fallback to prod.
    if (env?.DR_CANDIDATE_STAGE_ENABLED!=="true" ||
        !env?.DR_CANDIDATE_DB || typeof env.DR_CANDIDATE_DB.batch!=="function" ||
        typeof env.DR_CANDIDATE_DB.prepare!=="function") {
      return safeJson(503,{error:"Candidate staging disabled"});
    }
    try {
      if (!await authenticated(request,env.DR_FINANCE_HMAC_SECRET,raw)) {
        return safeJson(401,{error:"Unauthorized"});
      }
      let data;
      try {data=JSON.parse(raw);} catch {return safeJson(400,{error:"Invalid JSON"});}
      const statements=plan(data);
      // No input-supplied SQL is ever prepared or executed.
      const prepared=statements.map(([sql,values])=>
        env.DR_CANDIDATE_DB.prepare(sql).bind(...values));
      const results=await env.DR_CANDIDATE_DB.batch(prepared);
      requireValid(Array.isArray(results) && results.length===statements.length &&
        results.every(result=>result && result.success!==false));
      return safeJson(200,{status:"CANDIDATE_ATOMIC_EVENT_COMMITTED",
        authority:"STAGING_ONLY",kind:data.kind,automatic_payout:false});
    } catch {
      // Never leak SQL, customer/card identifiers, monetary amounts, secrets,
      // D1 provider error details or transaction contents to the caller/logs.
      return safeJson(409,{error:"Candidate event rejected; reconcile privately"});
    }
  },
};

export {PATH,plan,ORDER_SQL,INBOX_SQL,LINE_SQL,OUTBOX_SQL,REFUND_SQL,EVIDENCE_SQL};
