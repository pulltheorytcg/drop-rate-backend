"""Exact-provider repair for three newest missing-image Pokémon sets.

All source images are *reference-only*, not Shopify/physical-item photographs.
Read-only by default; only an administrator with an explicit one-off operator
gate may fill previously blank, identity-exact reference image_url fields.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
import re
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .access_control import require_platform_admin
from .db import user_connection
from .pokemon_artwork_repair import _probe_url
from .reference_feeds import ReferenceFeeds, ReferenceFeedError, tcgdex_card_number

SOURCE = "TCGdex"
SYSTEM = "POKEMON_TCG"
LANGUAGE = "English"
SETS = ("me06", "30th-c", "B2a")
MAX_ROWS = 350
MAX_SET_CARDS = 500
MAX_SECONDS = 240
SOURCE_ROOT = "https://api.tcgdex.net/v2/en"
ASSET_HOST = "assets.tcgdex.net"
PROOF = "TCGDEX_EXACT_NEW_SET_IMAGE_V1"

READ_SQL = """
select r.provider,r.system_code,r.language,r.provider_id,r.set_id,r.name,
       r.card_number,r.source_url,r.image_url,r.evidence
from tcg.reference_cards r join tcg.reference_sets s
  using(provider,system_code,language,set_id)
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
  and r.language='English' and r.set_id=any($1::text[])
  and nullif(btrim(r.image_url),'') is null
  and s.release_date<=current_date
order by array_position($1::text[],r.set_id),r.provider_id
limit $2
"""
WRITE_SQL = """
with c as (
 select * from jsonb_to_recordset($1::jsonb) as x (
  provider_id text,set_id text,name text,card_number text,
  source_url text,local_id text,image_url text,artwork_proof jsonb)
)
update tcg.reference_cards r
set image_url=c.image_url,
    evidence=r.evidence || jsonb_build_object('image_reference',c.artwork_proof)
from c,tcg.reference_sets s
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and r.language='English' and r.set_id=c.set_id and r.provider_id=c.provider_id
 and r.name=c.name and r.card_number=c.card_number and r.source_url=c.source_url
 and r.evidence->>'provider_local_id'=c.local_id
 and nullif(btrim(r.image_url),'') is null
 and s.provider=r.provider and s.system_code=r.system_code
 and s.language=r.language and s.set_id=r.set_id
 and s.release_date<=current_date
returning r.set_id,r.provider_id
"""


def safe_image_base(value, set_id: str, local: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        u = urlsplit(value)
        segments = u.path.strip("/").split("/")
        return (u.scheme == "https" and u.hostname == ASSET_HOST
                and u.port in (None, 443) and not u.username and not u.password
                and not u.query and not u.fragment and len(segments) == 4
                and segments[0] == "en" and segments[2] == set_id
                and segments[3] == local
                and all(re.fullmatch(r"[A-Za-z0-9._+-]{1,60}", x) for x in segments))
    except ValueError:
        return False


async def source_sets(feed, *, sets=SETS) -> dict:
    """Exactly three fixed official set URLs; never a supplied provider URL."""
    result = {}
    for sid in sets:
        if sid not in SETS:
            raise ValueError("Unsupported artwork source set")
        data = await feed.get(f"{SOURCE_ROOT}/sets/{sid}")
        if not isinstance(data, dict) or data.get("id") != sid:
            raise ReferenceFeedError("Unexpected official TCGdex set identity")
        cards = data.get("cards")
        if not isinstance(cards, list) or len(cards) > MAX_SET_CARDS:
            raise ReferenceFeedError("Invalid bounded set card list")
        official = (data.get("cardCount") or {}).get("official")
        if type(official) is not int or not 1 <= official <= 1000:
            raise ReferenceFeedError("Missing official collector denominator")
        images = {}
        for row in cards:
            if not isinstance(row, dict):
                raise ReferenceFeedError("Malformed card record")
            pid, local, name = row.get("id"), row.get("localId"), row.get("name")
            if (not isinstance(local, str) or not local
                    or not isinstance(pid, str) or pid != f"{sid}-{local}"
                    or not isinstance(name, str) or not name.strip()
                    or not re.fullmatch(r"[A-Za-z0-9-]{1,36}", local)
                    or pid in images):
                raise ReferenceFeedError("Conflicting source card identity")
            images[pid] = row
        result[sid] = {"data": data, "cards": images, "official": official}
    return result


def exact_candidate(ref: dict, snapshot: dict) -> dict | None:
    sid, pid = ref.get("set_id"), ref.get("provider_id")
    if (ref.get("provider") != SOURCE or ref.get("system_code") != SYSTEM
            or ref.get("language") != LANGUAGE or sid not in SETS
            or ref.get("image_url")):
        return None
    snap = snapshot.get(sid)
    if not snap:
        return None
    card = snap["cards"].get(pid)
    if not card:
        return None
    local = card.get("localId")
    evidence = ref.get("evidence") or {}
    if not isinstance(evidence, dict):
        return None
    expected_number = tcgdex_card_number("en", sid, pid, local, snap["official"])
    source_url = f"{SOURCE_ROOT}/cards/{pid}"
    base = card.get("image")
    if (ref.get("name") != card.get("name")
            or ref.get("source_url") != source_url
            or ref.get("card_number") != expected_number
            or evidence.get("provider_local_id") != local
            or not safe_image_base(base, sid, local)):
        return None
    return {"set_id": sid, "provider_id": pid, "local_id": local,
            "name": card["name"], "card_number": expected_number,
            "source_url": source_url, "image_base": base}


async def verify_image(client, candidate: dict):
    base = candidate["image_base"]
    for suffix, mime, fmt in (
            ("high.webp","image/webp","WEBP"),
            ("low.webp","image/webp","WEBP"),
            ("high.png","image/png","PNG")):
        result, error = await _probe_url(client, f"{base}/{suffix}", mime, fmt)
        if result:
            return result, None
        if error != "HTTP_404":
            return None, error
    return None, "HTTP_404"


async def run(pool=None, actor=None, *, apply=False, max_rows=MAX_ROWS, max_seconds=MAX_SECONDS,
              sample_only=False, progress=None):
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_ROWS:
        raise ValueError("Invalid one-shot card bound")
    if type(max_seconds) is not int or not 10 <= max_seconds <= MAX_SECONDS:
        raise ValueError("Invalid time budget")
    if apply and (pool is None or actor is None or sample_only
                  or os.getenv("DROP_RATE_POKEMON_NEW_ARTWORK_APPLY_CONFIRMED") != "YES"):
        raise PermissionError("One-shot image repair approval absent")
    if not sample_only and (pool is None or actor is None):
        raise ValueError("Database mode requires an authorized actor")
    if not sample_only:
        async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as conn:
            await require_platform_admin(conn)
            rows = [dict(x) for x in await conn.fetch(READ_SQL, list(SETS), max_rows)]
    else:
        rows = []
    feed = ReferenceFeeds()
    try:
        snapshot = await source_sets(feed)
    finally:
        await feed.close()
    counts = {sid: {
        "cards":len(item["cards"]),
        "declared_image_bases":sum(bool(x.get("image")) for x in item["cards"].values())}
        for sid,item in snapshot.items()}
    report = {"sets":counts,"source":"TCGdex official public API",
              "apply":apply,"requested":len(rows),"eligible":0,"verified":0,
              "updated":0,"rejected":{},"writes":False}
    if sample_only:
        return report
    candidates = [c for row in rows if (c:=exact_candidate(row,snapshot))]
    report["eligible"] = len(candidates)
    verified, failures = [], Counter()
    cutoff = asyncio.get_running_loop().time() + max_seconds
    async with httpx.AsyncClient(follow_redirects=False,limits=httpx.Limits(max_connections=4)) as client:
        for i in range(0,len(candidates),4):
            remaining = cutoff - asyncio.get_running_loop().time()
            if remaining < 1:
                failures["TIME_BUDGET"] += len(candidates)-i
                break
            try:
                async with asyncio.timeout(remaining):
                    found = await asyncio.gather(
                        *(verify_image(client,c) for c in candidates[i:i+4]))
            except TimeoutError:
                failures["TIME_BUDGET"] += len(candidates)-i
                break
            for item,(image,error) in zip(candidates[i:i+4],found):
                if error:
                    failures[error]+=1
                    continue
                verified.append({**{k:item[k] for k in ("set_id","provider_id","name",
                                        "card_number","source_url")},
                                 "local_id":item["local_id"],"image_url":image["image_url"],
                                 "artwork_proof":{
                                     "verification":PROOF,"scope":"REFERENCE_ONLY_NOT_APPROVED_MEDIA",
                                     "image_url":image["image_url"],"source_url":item["source_url"],
                                     "provider_set_url":f"{SOURCE_ROOT}/sets/{item['set_id']}",
                                     "verified_at":datetime.now(timezone.utc).isoformat(),
                                     "content_sha256":image["content_sha256"],
                                     "size_bytes":image["size_bytes"],
                                     "width":image["width"],"height":image["height"]}})
            if progress and (i+len(found))%40==0:
                progress({"examined":i+len(found),"verified":len(verified)})
            await asyncio.sleep(0.12)
    digests=Counter(row["artwork_proof"]["content_sha256"] for row in verified)
    safe=[row for row in verified if digests[row["artwork_proof"]["content_sha256"]]==1]
    failures["SHARED_IMAGE_BYTES"]+=len(verified)-len(safe)
    report.update(verified=len(safe),rejected=dict(failures))
    if apply and safe:
        async with user_connection(pool,actor,str(uuid4())) as conn:
            await require_platform_admin(conn)
            changed=await conn.fetch(WRITE_SQL,json.dumps(safe,ensure_ascii=False))
            report["updated"]=len(changed)
            report["writes"]=bool(changed)
            report["status"]="VERIFIED_PARTIAL" if len(changed)!=len(safe) else "VERIFIED_APPLIED"
    else:
        report["status"]="SOURCE_ONLY" if sample_only else "READ_ONLY_VERIFIED"
    return report
