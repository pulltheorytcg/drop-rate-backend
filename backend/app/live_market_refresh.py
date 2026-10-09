"""Bounded, auditable eBay UK inventory valuation through the existing v4 engine.

One lookup per physical pricing identity, not per copy. The existing immutable
ingestion journal is also the durable retry clock; no new service or outbox type.
Selling prices and publication are never mutated by this worker.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .ebay_sold_pricing import TrawlApiError, TrawlEbaySoldClient, _matches_comp, _persist_comp, _sold_at, select_five_newest_comps
from .ebay_sealed_pricing import _sealed_query, _select_five_sold
from .ebay_uk_parse_adapter import _normalise_text, _contains_term
from .market_ingestion import _record_run
from .pricing import _policy_from_row
from .pricing_engine import ComparableTarget, MarketObservation, PricingPolicy, calculate_price

log = logging.getLogger(__name__)
JOB = "LIVE_EBAY_MARKET_V1"
LOCK = 847220091
ACTIVE = {"DRAFT", "INSPECTION", "APPROVED"}
IDENTITY_FIELDS = ("catalogue_id", "product_type", "game", "name", "set_name", "card_number", "variant",
                   "rarity", "condition", "grading_company", "grade", "language", "seal_status",
                   "identity_confirmed", "set_code", "profile_identity_status", "sealed_identity_status", "sealed_product_type")
TARGET_SQL = """
select i.id,i.owner_id,i.inventory_code,i.catalogue_id,i.version,i.status,i.identity_confirmed,
 i.condition,i.grading_company,i.grade,i.language,i.seal_status,i.store_price_minor,
 i.market_value_minor,i.latest_pricing_snapshot_id,i.pricing_updated_at,
 p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
 pr.set_code,pr.identity_status as profile_identity_status,sd.identity_status as sealed_identity_status,
 (select a.value_code from tcg.catalogue_taxonomy_assignments a
  where a.catalogue_id=p.id and a.scope_kind='SEALED' and a.dimension_code='SEALED_TYPE'
    and a.verification_status='VERIFIED' order by a.created_at desc limit 1) as sealed_product_type
from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
join tcg.owners o on o.id=i.owner_id and o.active
left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
left join tcg.sealed_product_details sd on sd.catalogue_id=p.id
"""


def identity_key(target):
    return hashlib.sha256(json.dumps([str(target.get(k) or "") for k in IDENTITY_FIELDS]).encode()).hexdigest()


def card_name(target):
    # Annotations still participate in the print checks below, not the search name.
    name = re.split(r"\s*[([]|\s+-\s+|\s*//", target["name"], maxsplit=1)[0].strip()
    return name or target["name"]


def query_for(target):
    if target["product_type"] != "CARD":
        return _sealed_query(target)
    parts = [_normalise_text(card_name(target)), target["card_number"]]
    if target["language"].casefold() == "japanese":
        parts.append("Japanese")
    if target["grading_company"]:
        parts.extend([target["grading_company"], target["grade"]])
    return " ".join(parts)


def eligibility(target):
    if not target["identity_confirmed"]:
        return "IDENTITY_UNCONFIRMED"
    if target["language"] not in {"English", "Japanese"}:
        return "LANGUAGE_REVIEW_REQUIRED"
    if target["product_type"] == "CARD":
        if not target["card_number"] or not target["variant"]:
            return "EXACT_PRINT_REQUIRED"
        if not target["condition"] and not (target["grading_company"] and target["grade"]):
            return "PHYSICAL_CONDITION_REQUIRED"
        return None
    if (target["game"] == "One Piece" and target["seal_status"] == "SEALED"
            and target["profile_identity_status"] == target["sealed_identity_status"] == "VERIFIED"
            and target["sealed_product_type"] == "BOOSTER_PACK" and target["set_code"]):
        return None
    return "EXACT_SEALED_PRODUCT_MATCH_REQUIRED"


def exact_card_match(row, target):
    title = str(row.get("title") or "")
    text = _normalise_text(title)
    if re.search(r"\b(?:proxy|custom|replica|reprint|digital|jumbo|oversized|choose|choice|pick|lot|bundle|playset)\b", text):
        return False
    for m in re.finditer(r"\b(?:x\s*(\d+)|(\d+)\s*x|(\d+)\s+cards)\b", text):
        if any(int(v) != 1 for v in m.groups() if v):
            return False
    # Collector number must be one contiguous identifier, never scattered tokens.
    number = str(target["card_number"]).strip()
    if "/" in number and re.fullmatch(r"\d+/\d+", number):
        a, b = (int(x) for x in number.split("/"))
        pattern = rf"(?<!\d)0*{a}\s*/\s*0*{b}(?!\d)"
    else:
        pattern = r"(?<![A-Za-z0-9])" + r"[-\s]?".join(re.escape(p) for p in number.split("-")) + r"(?![A-Za-z0-9])"
    matched = re.search(pattern, title, re.I)
    if not matched:
        return False
    copy = dict(target, name=card_name(target), card_number=matched.group())
    # Keep language conflicts out even when the expected language is also present.
    if target["language"] == "Japanese" and _contains_term(text, "English"):
        return False
    company, grade = target["grading_company"], target["grade"]
    if company and not re.search(rf"\b{re.escape(company)}\s*(?:gem\s*mint\s*|mint\s*)?{re.escape(grade)}(?![\d.])", title, re.I):
        return False
    name = _normalise_text(target["name"])
    special_groups = (("parallel", "alt art", "alternate art", "aa"), ("manga",), ("sp",),
                      ("treasure",), ("film red",), ("25th",), ("3rd anniversary",), ("stamped",), ("winner",))
    for markers in special_groups:
        wanted = any(_contains_term(name, x) for x in markers)
        present = any(_contains_term(text, x) for x in markers)
        if wanted != present:
            return False
    for annotation in re.findall(r"[([]([^\])]+)[\])]", target["name"]):
        clean = _normalise_text(annotation)
        if re.fullmatch(r"[\d\s/]+", clean) or clean in {"parallel", "alt art", "alternate art", "sp", "manga"}:
            continue
        if not _contains_term(text, clean):
            return False
    if target["game"] == "Pokemon" and not _contains_term(text, target["set_name"]):
        return False
    return _matches_comp(row, copy)


def select_comps(payload, target, now):
    if payload.get("site") != "EBAY_GB" or payload.get("currency") != "GBP":
        raise ValueError("UK GBP sold response required")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Sold results required")
    original_titles = {str(r.get("item_id")):r.get("title") for r in rows if isinstance(r,dict)}
    def valid_money(row):
        try:
            amount=Decimal(str(row.get("sale_price")))
            return not isinstance(row.get("sale_price"),bool) and amount.is_finite() and amount>0
        except InvalidOperation:
            return False
    clean = dict(payload, results=[r for r in rows if isinstance(r, dict) and r.get("currency") in {None, "£", "GBP"} and valid_money(r)
                and (sold := _sold_at(r.get("date_sold"))) is not None and now-timedelta(days=90)<=sold<=now])
    if target["product_type"] == "CARD":
        clean["results"] = [r for r in clean["results"] if exact_card_match(r, target)]
        # Additional canonical-name checks have already been made above.
        check_target = dict(target, name=card_name(target))
        # Number formatting can differ by leading zero; normalise only the exact matched number.
        normalised = []
        for row in clean["results"]:
            r = dict(row)
            if re.fullmatch(r"\d+/\d+", target["card_number"]):
                a,b = (int(x) for x in target["card_number"].split("/"))
                r["title"] = re.sub(rf"(?<!\d)0*{a}\s*/\s*0*{b}(?!\d)", target["card_number"], r["title"])
            normalised.append(r)
        clean["results"] = normalised
        comps = [asdict(x) for x in select_five_newest_comps(clean, target=check_target)]
    else:
        comps = _select_five_sold(clean, target)
    return [dict(x,title=original_titles.get(x["item_id"],x["title"])) for x in comps]


def value_comps(comps, target, policy=None, now=None):
    if len(comps) != 5:
        raise ValueError("Five exact recent sales required")
    physical = {k:target.get(k) for k in ("condition", "grading_company", "grade", "language", "seal_status")}
    observations = [MarketObservation(source="EBAY", observation_type="SOLD", observed_at=c["sold_at"],
                    price_gbp_minor=c["price_minor"], source_country="GB", **physical) for c in comps]
    return calculate_price(observations, target=ComparableTarget(**physical), policy=policy or PricingPolicy(),
                           current_store_price_minor=target.get("store_price_minor"), as_of=now)


async def save_snapshot(connection, item, comps, query, now):
    policy_row = await connection.fetchrow("select * from tcg.pricing_policies where owner_id=$1", item["owner_id"])
    result = value_comps(comps, item, _policy_from_row(policy_row) if policy_row else None, now)
    evidence = {"method": JOB, "marketplace": "EBAY_GB", "query":query, "sale_price_excludes_shipping":True,
                "comps":[dict(c, sold_at=c["sold_at"].isoformat()) for c in comps],
                "sources":[dict(asdict(s), newest_observation_at=s.newest_observation_at.isoformat()) for s in result.source_estimates]}
    snapshot = await connection.fetchval("""insert into tcg.pricing_snapshots
      (inventory_id,catalogue_id,owner_id,market_value_minor,recommended_retail_minor,quick_sale_minor,
       target_acquisition_minor,confidence,source_count,observation_count,sold_observation_count,
       volatility_pct,newest_observation_at,algorithm_version,evidence,auto_publish_eligible,block_reasons)
      values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,false,$16::jsonb) returning id""",
      item["id"],item["catalogue_id"],item["owner_id"],result.market_value_minor,result.recommended_retail_minor,
      result.quick_sale_minor,result.target_acquisition_minor,result.confidence,result.source_count,
      result.observation_count,result.sold_observation_count,result.volatility_pct,result.newest_observation_at,
      result.algorithm_version,json.dumps(evidence),json.dumps(list(result.block_reasons)))
    return snapshot,result


async def save_value(connection, item, comps, query, now):
    snapshot,result = await save_snapshot(connection,item,comps,query,now)
    updated = await connection.fetchval("""update tcg.inventory_items set market_value_minor=$1,
      recommended_retail_minor=$2,latest_pricing_snapshot_id=$3,pricing_updated_at=now(),updated_at=now(),version=version+1
      where id=$4 and owner_id=$5 and version=$6 and status in ('DRAFT','INSPECTION','APPROVED') returning id""",
      result.market_value_minor,result.recommended_retail_minor,snapshot,item["id"],item["owner_id"],item["version"])
    if updated is None:
        raise ValueError("Inventory changed during valuation")


async def refresh_group(pool, actor, owner_id, items, client):
    started = datetime.now(timezone.utc)
    target = items[0]
    key = identity_key(target)
    reason = eligibility(target)
    comps, usage, query = [], {}, None
    if reason is None:
        query = query_for(target)
        payload = await client.sold(query=query, max_pages=2 if target["product_type"] != "CARD" else 1)
        usage = payload.get("_usage", {})
        try:
            comps = select_comps(payload, target, started)
        except (ValueError,TypeError,InvalidOperation) as exc:
            raise TrawlApiError("Sold provider data failed validation") from exc
        if len(comps) < 5:
            reason = "INSUFFICIENT_EXACT_SALES"
    updated, inserted, skipped = 0, 0, 0
    async with user_connection(pool, actor, str(uuid4())) as connection:
        await require_platform_admin(connection)
        current_rows = await connection.fetch(TARGET_SQL + " where i.id=any($1::uuid[]) order by i.id for update of i", [i["id"] for i in items])
        expected = {i["id"]:i for i in items}
        valid = [dict(r) for r in current_rows if r["status"] in ACTIVE and r["version"]==expected[r["id"]]["version"]
                 and r["owner_id"]==expected[r["id"]]["owner_id"] and identity_key(r)==key]
        skipped = len(items)-len(valid)
        if len(comps)==5 and valid:
            # Persist using the same immutable observation schema as manual pricing.
            from .ebay_sold_pricing import SoldComparable
            for comp in comps:
                persisted = SoldComparable(**{k:comp.get(k) for k in SoldComparable.__dataclass_fields__})
                inserted += int(await _persist_comp(connection, target, persisted, query=query))
            for item in valid:
                await save_value(connection, item, comps, query, started)
                updated += 1
        await _record_run(connection, owner_id=owner_id, source="EBAY", trigger_type="SCHEDULED",
            status="SUCCEEDED" if updated else "BLOCKED", mapping_count=1, fetched_count=len(comps),
            inserted_count=inserted, duplicate_count=len(comps)-inserted if updated else 0,
            failed_mapping_count=0, errors=[], started_at=started,
            metadata={"job":JOB,"identity_key":key,"reason":reason,"inventory_ids":[str(i["id"]) for i in items],
                      "updated":updated,"skipped_changed":skipped,"comparable_count":len(comps),"usage":usage,
                      "next_check_at":(started+timedelta(hours=24 if updated else 72)).isoformat()})
    log.warning("Live eBay market group: key=%s updated=%s pending=%s changed=%s",key[:12],updated,reason,skipped)
    return {"updated":updated,"pending":len(items)-updated,"usage":usage}


async def refresh_pass(pool, settings):
    actor = UUID(settings.ebay_market_refresh_actor_user_id)
    # A session advisory lock prevents duplicate provider use across app replicas.
    # There is no open transaction during HTTP; the lock connection is released in finally.
    async with pool.acquire() as lock_connection:
        if not await lock_connection.fetchval("select pg_try_advisory_lock($1)", LOCK):
            return {"status":"ALREADY_RUNNING"}
        try:
            async with user_connection(pool, actor, str(uuid4())) as connection:
                access = await require_platform_admin(connection)
                # Retain every historical snapshot and store price. Imported benchmarks
                # cannot remain the active 'live' market value under the eBay-only policy.
                await connection.execute("""update tcg.inventory_items i set market_value_minor=null,
                  recommended_retail_minor=null,pricing_updated_at=null,updated_at=now(),version=version+1
                  where i.status in ('DRAFT','INSPECTION','APPROVED') and i.market_value_minor is not null
                    and exists(select 1 from tcg.pricing_snapshots s where s.id=i.latest_pricing_snapshot_id)
                    and not exists(select 1 from tcg.pricing_snapshots s where s.id=i.latest_pricing_snapshot_id
                      and s.algorithm_version='drop-rate-market-v4'
                      and (s.evidence->>'method'='LIVE_EBAY_MARKET_V1' or s.sold_observation_count>=5)
                      and s.evidence->'sources' @> '[{"source":"EBAY"}]'::jsonb)""")
                rows = await connection.fetch(TARGET_SQL + " where i.status in ('DRAFT','INSPECTION','APPROVED') order by i.store_price_minor desc nulls last,i.id limit 2000")
                checks = await connection.fetch("""select distinct on (metadata->>'identity_key') metadata,completed_at
                  from tcg.market_ingestion_runs where source='EBAY' and metadata->>'job'=$1
                  order by metadata->>'identity_key',completed_at desc limit 3000""", JOB)
            last = {r["metadata"].get("identity_key"):r["metadata"] for r in checks}
            now = datetime.now(timezone.utc)
            pause = last.get("PROVIDER", {}).get("next_check_at")
            if pause and datetime.fromisoformat(pause)>now:
                return {"status":"PROVIDER_PAUSED","until":pause}
            groups = defaultdict(list)
            for row in rows:
                groups[identity_key(row)].append(dict(row))
            total = {"status":"COMPLETE","groups":0,"updated":0,"pending":0}
            client = TrawlEbaySoldClient(api_key=settings.trawl_api_key)
            for key, items in groups.items():
                previous = last.get(key, {})
                if previous.get("next_check_at") and datetime.fromisoformat(previous["next_check_at"])>now:
                    continue
                if total["groups"]>=settings.ebay_market_refresh_max_groups:
                    total["status"]="BATCH_LIMIT"
                    break
                try:
                    result = await refresh_group(pool, actor, access["owner_id"], items, client)
                except TrawlApiError as exc:
                    # Global stop on quota/auth/provider errors, not 500 repeat failures.
                    delay = 24 if exc.status_code==429 else 1
                    async with user_connection(pool,actor,str(uuid4())) as connection:
                        await require_platform_admin(connection)
                        await _record_run(connection,owner_id=access["owner_id"],source="EBAY",trigger_type="SCHEDULED",
                            status="FAILED",mapping_count=1,fetched_count=0,inserted_count=0,duplicate_count=0,
                            failed_mapping_count=1,errors=[{"code":"PROVIDER_UNAVAILABLE","status":exc.status_code}],started_at=now,
                            metadata={"job":JOB,"identity_key":"PROVIDER","next_check_at":(datetime.now(timezone.utc)+timedelta(hours=delay)).isoformat()})
                    total["status"]="PROVIDER_PAUSED"
                    log.warning("Live eBay market paused: provider_status=%s groups=%s",exc.status_code,total["groups"])
                    break
                total["groups"]+=1
                total["updated"]+=result["updated"]
                total["pending"]+=result["pending"]
                # Below even the provider's free-tier rate. No retries on empty results.
                await asyncio.sleep(0.6)
            log.warning("Live eBay market pass: %s",total)
            return total
        finally:
            await lock_connection.execute("select pg_advisory_unlock($1)", LOCK)


async def run_live_market_refresh(pool, settings):
    while True:
        try:
            await refresh_pass(pool,settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No raw provider responses, queries, credentials or connection strings in logs.
            log.error("Live eBay market refresh failed: type=%s; retry in one hour",type(exc).__name__)
        await asyncio.sleep(3600)
