/*
 * INACTIVE private Cloudflare D1 operational owner-inventory READ pilot.
 * NO wrangler deployment binding, domain route, public API or write method.
 * Only a signed FastAPI server may provide a previously verified legacy user
 * UUID. A browser-supplied owner_id, role, founder slot or token is rejected.
 *
 * HMAC: hex SHA256 signature over POST + path + UTC epoch seconds + raw body.
 * This is an internal transport trust boundary, NOT a customer login provider.
 * The source generation and D1 binding are server configuration only.
 */
const PATH = "/internal/v1/owner-inventory";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const GENERATION = /^src-[0-9a-f]{32}$/;
const HMAC_HEX = /^[0-9a-f]{64}$/;
const MAX_BODY_BYTES = 2048;
const MAX_SKEW_SECONDS = 120;
const MAX_PAGE = 50;
const encoder = new TextEncoder();

const OWNER_SQL = `
SELECT m.owner_id, o.owner_type
FROM ops_shadow_memberships AS m
JOIN ops_shadow_owners AS o
  ON o.generation_id=m.generation_id AND o.id=m.owner_id
JOIN ops_shadow_identity_map AS im
  ON im.generation_id=m.generation_id AND im.legacy_user_id=m.legacy_user_id
JOIN ops_shadow_generations AS g
  ON g.generation_id=m.generation_id
WHERE m.generation_id=?
  AND m.legacy_user_id=?
  AND m.active=1 AND o.active=1
  AND m.role IN ('OWNER','PLATFORM_ADMIN')
  AND g.state='PARITY_VERIFIED'
  AND (SELECT count(*) FROM ops_shadow_table_receipts r
       WHERE r.generation_id=g.generation_id)=9
LIMIT 2
`;

const INVENTORY_SQL = `
SELECT id,inventory_code,catalogue_id,owner_id,condition,grade,
       language,status,version,acquisition_cost_minor,
       market_value_minor,store_price_minor,currency
FROM ops_shadow_inventory
WHERE generation_id=? AND owner_id=? AND id>?
ORDER BY id LIMIT ?
`;

function respond(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, private",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function hexToBytes(hex) {
  if (typeof hex !== "string" || !HMAC_HEX.test(hex)) return null;
  const bytes = new Uint8Array(32);
  for (let i=0; i<32; i++) bytes[i]=Number.parseInt(hex.slice(2*i,2*i+2),16);
  return bytes;
}

async function verifiedInternalRequest(request, secretHex, rawBody, nowSeconds) {
  const secret = hexToBytes(secretHex);
  const stamp = request.headers.get("X-DR-Timestamp");
  const signature = request.headers.get("X-DR-Signature");
  if (!secret || !stamp || !/^[0-9]{10,12}$/.test(stamp)
      || !signature || !/^sha256=[0-9a-f]{64}$/.test(signature)) return false;
  const epoch = Number(stamp);
  if (!Number.isSafeInteger(epoch)
      || Math.abs(epoch-nowSeconds)>MAX_SKEW_SECONDS) return false;
  const supplied = hexToBytes(signature.slice(7));
  const key = await crypto.subtle.importKey(
    "raw",secret,{name:"HMAC",hash:"SHA-256"},false,["verify"]);
  const message = encoder.encode(
    "POST\n"+PATH+"\n"+stamp+"\n"+rawBody);
  return crypto.subtle.verify("HMAC",key,supplied,message);
}

function parsePayload(raw) {
  let body;
  try { body = JSON.parse(raw); } catch { return null; }
  if (body === null || Array.isArray(body) || typeof body !== "object") return null;
  const keys = Object.keys(body).sort();
  if (keys.join(",")!=="cursor,legacy_user_id,limit") return null;
  if (!UUID.test(body.legacy_user_id)
      || !(body.cursor===null || UUID.test(body.cursor))
      || !Number.isInteger(body.limit) || body.limit<1 || body.limit>MAX_PAGE) {
    return null;
  }
  return body;
}

function validRows(response, max) {
  if (!response || !Array.isArray(response.results)
      || response.success===false || response.results.length>max) {
    throw new Error("Private D1 readback rejected");
  }
  return response.results;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname!==PATH || url.search || request.method!=="POST") {
      return respond(404,{error:"Not found"});
    }
    if (request.headers.get("Content-Type")!=="application/json") {
      return respond(415,{error:"Unsupported content type"});
    }
    const declared = request.headers.get("Content-Length");
    if (declared && (!/^[0-9]+$/.test(declared) ||
                     Number(declared)>MAX_BODY_BYTES)) {
      return respond(413,{error:"Request too large"});
    }
    let raw;
    try { raw = await request.text(); } catch {
      return respond(400,{error:"Malformed request"});
    }
    if (encoder.encode(raw).length>MAX_BODY_BYTES) {
      return respond(413,{error:"Request too large"});
    }
    try {
      const authorized=await verifiedInternalRequest(
        request,env?.DR_INTERNAL_HMAC_SECRET,raw,
        Math.floor(Date.now()/1000));
      if (!authorized) return respond(401,{error:"Unauthorized"});
      const generation=env?.DR_OPS_GENERATION_ID;
      if (!GENERATION.test(generation) ||
          !env?.OPS_DB || typeof env.OPS_DB.prepare!=="function") {
        return respond(503,{error:"Source not verified"});
      }
      const body=parsePayload(raw);
      if (!body) return respond(400,{error:"Invalid owner-inventory request"});

      // Always derive exactly one owner from ACTIVE, private D1 memberships.
      // Never accept owner_id from client JSON even if the HMAC is valid.
      const access=validRows(await env.OPS_DB.prepare(OWNER_SQL)
        .bind(generation,body.legacy_user_id).all(),2);
      if (access.length===0) return respond(403,{error:"No active owner"});
      if (access.length!==1) return respond(409,{error:"Ambiguous owner membership"});
      const owner=access[0];
      if (!UUID.test(owner?.owner_id) ||
          !["FOUNDER","CONSIGNOR"].includes(owner?.owner_type)) {
        return respond(503,{error:"Invalid private owner"});
      }

      const items=validRows(await env.OPS_DB.prepare(INVENTORY_SQL)
        .bind(generation,owner.owner_id,body.cursor??"",body.limit).all(),
        body.limit);
      let last=body.cursor??"";
      for (const item of items) {
        if (!UUID.test(item?.id) || item.id<=last ||
            item.owner_id!==owner.owner_id || item.currency!=="GBP" ||
            !Number.isInteger(item.version) || item.version<1) {
          return respond(503,{error:"Invalid private inventory"});
        }
        last=item.id;
      }
      return respond(200,{
        status:"VERIFIED_READ_ONLY",
        owner_id:owner.owner_id,
        owner_type:owner.owner_type,
        founder_hq_allowed:false,
        business_allowed:false,
        inventory:items,
        next_cursor:items.length===body.limit?last:null,
      });
    } catch {
      // No SQL, private identifiers, table contents or credentials to logs.
      return respond(503,{error:"Private D1 read unavailable"});
    }
  },
};

export { PATH, OWNER_SQL, INVENTORY_SQL };
