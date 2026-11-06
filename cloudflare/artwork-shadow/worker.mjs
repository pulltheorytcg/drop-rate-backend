// Drop Rate Cloudflare artwork SHADOW only. No public image routes or publication.
const MAX_BYTES = 10_000_000;
const DIGEST = /^[0-9a-f]{64}$/;
const KEY = /^x:[0-9a-f]{64}$/;
const TOKEN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/;

function reject(status, reason) {
  return new Response(JSON.stringify({accepted:false,reason}), {
    status, headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}
  });
}
function response(body,status=200) {
  return new Response(JSON.stringify(body),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function toHex(bytes) {
  return [...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,"0")).join("");
}
async function sha256(data) {
  return toHex(await crypto.subtle.digest("SHA-256",data));
}
async function verifyHmac(secret, timestamp, body, signature) {
  if (typeof secret!=="string"||secret.length<32
    ||typeof timestamp!=="string"||!/^[0-9]{10,11}$/.test(timestamp)
    ||typeof signature!=="string"||!/^sha256=[0-9a-f]{64}$/.test(signature)) return false;
  const seconds=Number(timestamp);
  if (!Number.isSafeInteger(seconds)||Math.abs(Date.now()/1000-seconds)>300) return false;
  const encoder=new TextEncoder();
  const key=await crypto.subtle.importKey("raw",encoder.encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const expected=toHex(await crypto.subtle.sign("HMAC",key,encoder.encode(timestamp+"."+body)));
  const supplied=signature.slice(7);
  let mismatch=0;
  for(let i=0;i<64;i++)mismatch|=expected.charCodeAt(i)^supplied.charCodeAt(i);
  return mismatch===0;
}
function checked(body) {
  if (!body||typeof body!=="object"||Array.isArray(body)
    ||body.schema_version!==1||body.action!=="STAGE_VERIFIED_ARTWORK"
    ||Object.keys(body).sort().join(",")!==
    ["action","card_number","content_sha256","finish","language","object_key","provider","provider_id","rarity","reference_key","rights_review_id","schema_version","set_id","size_bytes","source_manifest_sha256","system_code"].sort().join(",")) return null;
  if (![body.content_sha256,body.source_manifest_sha256].every(x=>typeof x==="string"&&DIGEST.test(x))
    ||typeof body.reference_key!=="string"||!KEY.test(body.reference_key)
    ||typeof body.object_key!=="string"
    ||body.object_key!=="drop-rate/private-media/"+body.content_sha256+".webp"
    ||!Number.isInteger(body.size_bytes)||body.size_bytes<12||body.size_bytes>MAX_BYTES) return null;
  for(const field of ["provider","provider_id","system_code","language","set_id","card_number","rights_review_id"]){
    const value=body[field];
    if(typeof value!=="string"||!value||value.length>256||!TOKEN.test(value))return null;
  }
  if (!/^[A-Z][A-Z0-9_]{1,63}$/.test(body.system_code)
    ||!["English","Japanese","Korean","French","German","Spanish","Italian","Chinese"].includes(body.language)
    ||typeof body.finish!=="string"||body.finish.length>128
    ||typeof body.rarity!=="string"||body.rarity.length>128
    ||!body.set_id||!body.card_number) return null;
  return body;
}

export async function handle(request,env) {
  if(new URL(request.url).pathname!=="/v1/internal/artwork/shadow")return reject(404,"NOT_FOUND");
  if(request.method!=="POST")return reject(405,"METHOD_NOT_ALLOWED");
  const length=Number(request.headers.get("content-length")||"0");
  if(length>4096)return reject(413,"BODY_TOO_LARGE");
  let raw;
  try {
    raw=await request.text();
    if(raw.length===0||raw.length>4096)return reject(413,"BODY_TOO_LARGE");
  }catch{return reject(400,"INVALID_BODY");}
  const validSignature=await verifyHmac(env.ARTWORK_COMMAND_SECRET,
    request.headers.get("x-drop-rate-timestamp"),
    raw,request.headers.get("x-drop-rate-signature"));
  if(!validSignature)return reject(401,"UNAUTHORISED");
  let data;
  try {data=checked(JSON.parse(raw));}catch{return reject(422,"INVALID_ARTWORK_RECEIPT");}
  if(!data)return reject(422,"INVALID_ARTWORK_RECEIPT");
  // Exact stable key in R2-first catalogue is sha256(JSON of this tuple).
  const expected="x:"+await sha256(new TextEncoder().encode(JSON.stringify([
    data.provider,data.system_code,data.language,data.provider_id
  ])));
  if(expected!==data.reference_key)return reject(409,"REFERENCE_IDENTITY_MISMATCH");
  if(!env.ARTWORK_R2||!env.ARTWORK_D1)return reject(503,"PRIVATE_BINDINGS_MISSING");
  let obj;
  try {obj=await env.ARTWORK_R2.get(data.object_key);}catch{return reject(503,"R2_UNAVAILABLE");}
  if(!obj)return reject(409,"R2_ARTWORK_MISSING");
  if(obj.size!==data.size_bytes||obj.httpMetadata?.contentType!=="image/webp")
    return reject(409,"R2_ARTWORK_METADATA_MISMATCH");
  let bytes;
  try {bytes=new Uint8Array(await obj.arrayBuffer());}catch{return reject(503,"R2_READ_FAILED");}
  if(bytes.length!==data.size_bytes||bytes.length<12||bytes[0]!==82||bytes[1]!==73
    ||bytes[2]!==70||bytes[3]!==70||bytes[8]!==87||bytes[9]!==69
    ||bytes[10]!==66||bytes[11]!==80||await sha256(bytes)!==data.content_sha256)
    return reject(409,"R2_ARTWORK_SHA_OR_FORMAT_MISMATCH");
  // This database is an isolated artwork SHADOW. No live pointers or Shopify
  // publication are exposed. The signed backend must separately verify the
  // printing and rights policy before any future full release workflow.
  try {
    const existing=await env.ARTWORK_D1.prepare(
      "select content_sha256,size_bytes,object_key from artwork_shadow_candidates where reference_key=? and source_manifest_sha256=?"
    ).bind(data.reference_key,data.source_manifest_sha256).first();
    if(existing){
      if(existing.content_sha256!==data.content_sha256||existing.size_bytes!==data.size_bytes||existing.object_key!==data.object_key)
        return reject(409,"SHADOW_IMAGE_CONFLICT");
      return response({accepted:true,state:"SHADOW_ONLY",unchanged:true,reference_key:data.reference_key,content_sha256:data.content_sha256});
    }
    const result=await env.ARTWORK_D1.prepare(
      "insert or ignore into artwork_shadow_candidates (reference_key,provider,system_code,language,provider_id,set_id,card_number,rarity,finish,source_manifest_sha256,object_key,content_sha256,size_bytes,rights_review_id,state) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    ).bind(data.reference_key,data.provider,data.system_code,data.language,data.provider_id,
      data.set_id,data.card_number,data.rarity,data.finish,data.source_manifest_sha256,
      data.object_key,data.content_sha256,data.size_bytes,data.rights_review_id,"STAGED_PRIVATE").run();
    if(result?.meta?.changes===1)return response({accepted:true,state:"SHADOW_ONLY",unchanged:false,reference_key:data.reference_key,content_sha256:data.content_sha256});
    // Concurrent insert must be proven identical; never overwrite a print.
    const competing=await env.ARTWORK_D1.prepare(
      "select content_sha256,size_bytes,object_key from artwork_shadow_candidates where reference_key=? and source_manifest_sha256=?"
    ).bind(data.reference_key,data.source_manifest_sha256).first();
    if(competing?.content_sha256===data.content_sha256&&competing.size_bytes===data.size_bytes
      &&competing.object_key===data.object_key)
      return response({accepted:true,state:"SHADOW_ONLY",unchanged:true,reference_key:data.reference_key,content_sha256:data.content_sha256});
    return reject(409,"SHADOW_WRITE_CONFLICT");
  }catch{
    return reject(503,"D1_SHADOW_UNAVAILABLE");
  }
}
export default {fetch:handle};
