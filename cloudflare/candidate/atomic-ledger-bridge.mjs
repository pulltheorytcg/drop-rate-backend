/**
 * INACTIVE, STAGING-ONLY private Drop Rate D1 financial transaction transport.
 *
 * NOT deployed. DO NOT attach production D1 or Shopify directly. When a
 * separately approved staging-only Worker is provisioned, its sole purpose
 * is to verify backend-issued HMAC envelopes and execute FIXED, PARAMETERIZED
 * SQL statements with D1Database.batch() in ONE atomic transaction.
 *
 * FastAPI must independently authenticate Shopify/eBay source events and
 * derive the verified physical inventory owner; this Worker does NOT infer
 * ownership, validate payment settlement or authorize browser requests.
 */
const PATH = "/internal/d1/candidate/post";
const MAX_BODY_BYTES = 65536;
const MAX_SALE_LINES = 100;
const MAX_SIGNATURE_SKEW_SECONDS = 120;
const encoder = new TextEncoder();

export const ALLOWED_SQL = Object.freeze({
  saleOrder:
    "INSERT INTO candidate_orders (id,source,source_reference,currency,status,placed_at) " +
    "VALUES(?,?,?,'GBP','RECONCILIATION_REQUIRED',?)",
  saleInbox:
    "INSERT INTO candidate_webhook_inbox " +
    "(webhook_id,source,shop_domain,payload_sha256,order_id,received_at) " +
    "VALUES(?,?,?,?,?,?)",
  saleLine:
    "INSERT INTO candidate_order_items " +
    "(id,order_id,inventory_id,owner_id,expected_inventory_version," +
    "sale_price_minor,discount_minor,net_sale_minor,cost_basis_minor," +
    "commission_bps_snapshot,commission_minor,sold_at) " +
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
  saleOutbox:
    "INSERT INTO candidate_outbox " +
    "(id,order_id,event_type,payload_sha256,status,created_at) " +
    "VALUES(?,?,'ORDER_POSTED',?,'PENDING',?)",
  cardRefund:
    "INSERT INTO candidate_card_refunds " +
    "(id,source,source_reference,order_id,order_item_id,inventory_id," +
    "owner_id,card_amount_minor,currency,return_to_inspection,payload_sha256," +
    "occurred_at) VALUES(?,?,?,?,?,?,?,?,'GBP',?,?,?)",
  shippingAllocation:
    "INSERT INTO candidate_shipping_allocations " +
    "(id,source,source_reference,order_id,order_item_id,owner_id," +
    "amount_minor,currency,payload_sha256,occurred_at) " +
    "VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
  shippingRefund:
    "INSERT INTO candidate_shipping_refunds " +
    "(id,source,source_reference,order_id,order_item_id,owner_id," +
    "amount_minor,currency,payload_sha256,occurred_at) " +
    "VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
  paymentFee:
    "INSERT INTO candidate_payment_fees " +
    "(id,source,source_reference,order_id,order_item_id,owner_id," +
    "amount_minor,currency,payload_sha256,occurred_at) " +
    "VALUES(?,?,?,?,?,?,?,'GBP',?,?)",
});

const SINGLE = Object.freeze({
  POST_CARD_REFUND: ALLOWED_SQL.cardRefund,
  POST_SHIPPING_ALLOCATION: ALLOWED_SQL.shippingAllocation,
  POST_SHIPPING_REFUND: ALLOWED_SQL.shippingRefund,
  POST_PAYMENT_FEE: ALLOWED_SQL.paymentFee,
});

function errorResponse(code, label) {
  return Response.json({ status: label }, { status: code, headers: {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
  } });
}

function isSafeParam(param) {
  if (param === null) return true;
  if (typeof param === "number") return Number.isSafeInteger(param) &&
    Math.abs(param) <= 1000000000000000;
  if (typeof param === "string") return param.length <= 1024 &&
    !/[\u0000-\u001f\u007f]/.test(param);
  return false;
}

function validateStatement(statement, expected) {
  if (!statement || typeof statement !== "object" || Array.isArray(statement) ||
      Object.keys(statement).sort().join(",") !== "params,sql" ||
      statement.sql !== expected || !Array.isArray(statement.params) ||
      statement.params.length > 100 ||
      statement.params.length !== (expected.match(/\?/g) || []).length ||
      !statement.params.every(isSafeParam)) {
    throw new Error("Invalid fixed financial statement contract");
  }
}

export function validateOperationEnvelope(envelope) {
  if (!envelope || typeof envelope !== "object" || Array.isArray(envelope) ||
      Object.keys(envelope).sort().join(",") !== "operation,statements,version" ||
      envelope.version !== 1 || typeof envelope.operation !== "string" ||
      !Array.isArray(envelope.statements)) {
    throw new Error("Invalid protected financial envelope");
  }
  const list = envelope.statements;
  if (envelope.operation === "POST_PAID_SALE") {
    if (list.length < 4 || list.length > MAX_SALE_LINES + 3) {
      throw new Error("Invalid physical sale batch length");
    }
    validateStatement(list[0], ALLOWED_SQL.saleOrder);
    validateStatement(list[1], ALLOWED_SQL.saleInbox);
    for (let index = 2; index < list.length - 1; index++) {
      validateStatement(list[index], ALLOWED_SQL.saleLine);
    }
    validateStatement(list[list.length - 1], ALLOWED_SQL.saleOutbox);
  } else if (Object.hasOwn(SINGLE, envelope.operation)) {
    if (list.length !== 1) throw new Error("Financial event must be atomic");
    validateStatement(list[0], SINGLE[envelope.operation]);
  } else {
    throw new Error("Unapproved D1 financial operation");
  }
  return list;
}

function bytesToHex(data) {
  return Array.from(new Uint8Array(data), byte =>
    byte.toString(16).padStart(2, "0")).join("");
}

function decodeHex(text) {
  if (typeof text !== "string" || !/^[a-f0-9]{64}$/.test(text)) {
    throw new Error("Invalid fixed HMAC length");
  }
  return Uint8Array.from(text.match(/../g), pair => parseInt(pair, 16));
}

async function readBoundedBody(request) {
  const advertised = request.headers.get("Content-Length");
  if (advertised && Number(advertised) > MAX_BODY_BYTES) {
    throw new Error("Oversized signed body");
  }
  if (!request.body) throw new Error("Missing signed body");
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new Error("Oversized signed body");
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const part of chunks) {
    body.set(part, offset);
    offset += part.byteLength;
  }
  return body;
}

export async function verifySignedRequest(request, secret, expectedHost, nowSeconds) {
  const url = new URL(request.url);
  if (request.method !== "POST" || url.pathname !== PATH ||
      url.search || url.hash || url.host !== expectedHost ||
      request.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !==
        "application/json" ||
      request.headers.get("X-DR-Protocol") !== "1" ||
      typeof secret !== "string" || secret.length < 40) {
    throw new Error("Untrusted internal service request");
  }
  const timestamp = request.headers.get("X-DR-Timestamp");
  if (!timestamp || !/^[0-9]{10,12}$/.test(timestamp) ||
      !Number.isSafeInteger(Number(timestamp)) ||
      Math.abs(nowSeconds - Number(timestamp)) > MAX_SIGNATURE_SKEW_SECONDS) {
    throw new Error("Expired or future service signature");
  }
  const body = await readBoundedBody(request);
  const digest = bytesToHex(await crypto.subtle.digest("SHA-256", body));
  const advertisedHash = request.headers.get("X-DR-Body-Sha256");
  if (advertisedHash !== digest) {
    throw new Error("Signed body digest mismatch");
  }
  const message = ["POST", url.host, PATH, timestamp, digest].join("\n");
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" },
    false, ["verify"]);
  let signature;
  try {
    signature = decodeHex(request.headers.get("X-DR-Signature"));
  } catch {
    throw new Error("Invalid signature encoding");
  }
  if (!await crypto.subtle.verify(
      "HMAC", key, signature, encoder.encode(message))) {
    throw new Error("Invalid internal service signature");
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
}

const worker = {
  async fetch(request, env) {
    // Enforce the kill switch and staging-only deployment at the edge.
    // A production deployment cannot become writable by changing a
    // lone flag or attaching a production database binding.
    if (env?.DR_ENVIRONMENT !== "staging" ||
        env?.DR_CANDIDATE_WRITES_ENABLED !== "staging-only" ||
        env?.DR_CANDIDATE_SCHEMA_VERSION !== "v3" ||
        !env?.DB || typeof env.DB.batch !== "function" ||
        typeof env.DB.prepare !== "function" ||
        typeof env.DR_EXPECTED_STAGING_HOST !== "string" ||
        typeof env.DR_INTERNAL_HMAC_SECRET !== "string") {
      return errorResponse(404, "NOT_FOUND");
    }
    let envelope;
    try {
      envelope = await verifySignedRequest(
        request, env.DR_INTERNAL_HMAC_SECRET,
        env.DR_EXPECTED_STAGING_HOST,
        Math.floor(Date.now() / 1000),
      );
    } catch {
      // No source/token/URL/header/body details in a response or log.
      return errorResponse(401, "UNAUTHORIZED");
    }
    let statements;
    try {
      statements = validateOperationEnvelope(envelope);
    } catch {
      return errorResponse(400, "UNAPPROVED_OPERATION");
    }
    try {
      const prepared = statements.map(item => env.DB.prepare(item.sql).bind(...item.params));
      // Cloudflare D1 batch() rolls back the ENTIRE transaction if any
      // statement/trigger fails. Never loop through separate .run() calls.
      await env.DB.batch(prepared);
      return errorResponse(200, "STAGING_POSTED");
    } catch {
      return errorResponse(409, "STAGING_TRANSACTION_REJECTED");
    }
  },
};

export default worker;
