"""Drop Rate's internal, evidence-backed catalogue valuation pass.

Runs within the existing catalogue worker; never creates a new service.
The model is strictly for ordinary standard C/UC cards: variants and
special rarities require exact product/artwork marketplace evidence instead.
A calculation can be rules-verified without pretending to be a completed sale.
The derived catalogue value is not a physical copy's condition-adjusted value.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from .access_control import require_platform_admin
from .db import user_connection
from .pokewallet_one_piece_market import WRITE_SQL
from .pricing_rules import store_price_floor
from .reference_baseline_model import PeerGuide, Printing, ordinary_peer_baseline
from .fusion_official_rarity import VERIFIED_BASE_SQL as FUSION_VERIFIED_BASE_SQL

JOB = "DROP_RATE_DAILY_MODEL"
SOURCE = "DROP_RATE_COMPUTED_MARKET_V1"
REVISION = 2
ALGORITHM_VERSION = 1  # The existing P25 formula is unchanged; revision rolls out new source eligibility.
MAX_BATCH = 1000

# Exact, published physical references only. We explicitly exclude Naruto and
# every printing with a positive independent market/guide price, even if stale.
# On later days a previously calculated Drop Rate value may be recalculated.
CANDIDATE_SQL = f"""
select r.provider,r.system_code,r.language,r.provider_id,r.set_id,r.name,
       r.card_number,r.rarity,r.image_url,s.name as set_name,
       b.quotes->0->>'source' as prior_source,
       concat_ws(chr(31),r.provider,r.system_code,r.language,r.set_id,r.provider_id) as cursor
from tcg.reference_cards r
join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
where (s.release_date is null or s.release_date<=current_date)
  and r.image_url is not null and length(btrim(r.image_url))>0
  and coalesce(p.market_value_minor,0)<=0
  and (coalesce(b.market_value_minor,0)<=0
       or b.quotes->0->>'source'='DROP_RATE_COMPUTED_MARKET_V1')
  and (
   (r.provider='Bandai Official' and r.system_code='DRAGON_BALL_SUPER_MASTERS'
    and r.language='English' and r.rarity in ('Common[C]','Uncommon[UC]')
    and r.card_number ~ '^BT[0-9]+-[0-9]{{2,3}}$'
    and r.provider_id !~* '_(PR[0-9]*|p[0-9]+)([.]|$)')
   or
   (r.system_code='ONE_PIECE_CARD_GAME' and r.language in ('English','Japanese')
    and r.rarity in ('C','UC','Common','Uncommon')
    and r.provider_id=r.card_number and r.card_number ~ '^(OP|EB|PRB|ST)[0-9]{{2}}-[0-9]{{3}}$')
   or {FUSION_VERIFIED_BASE_SQL}
  )
  and concat_ws(chr(31),r.provider,r.system_code,r.language,r.set_id,r.provider_id)>$1
order by r.provider,r.system_code,r.language,r.set_id,r.provider_id
limit $2
"""

# Peers are sourced from pre-existing externally derived guides, NEVER from
# another Drop Rate model estimate. Future models cannot self-reinforce.
PEER_SQL = f"""
with wanted as (
 select distinct provider,system_code,language,set_id,rarity
 from jsonb_to_recordset($1::jsonb)
 as x(provider text,system_code text,language text,set_id text,rarity text)
)
select r.provider,r.system_code,r.language,r.set_id,r.provider_id,r.card_number,
       r.rarity, p.market_value_minor as detail_minor,
       p.pricing_updated_at as detail_at, p.quotes->0->>'source' as detail_source,
       b.market_value_minor as catalogue_minor,
       b.pricing_updated_at as catalogue_at,b.quotes->0->>'source' as catalogue_source
from tcg.reference_cards r join wanted w
 using(provider,system_code,language,set_id,rarity)
left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
where
 (r.system_code='DRAGON_BALL_SUPER_MASTERS'
  and r.card_number ~ '^BT[0-9]+-[0-9]{{2,3}}$'
  and r.provider_id !~* '_(PR[0-9]*|p[0-9]+)([.]|$)')
 or
 (r.system_code='ONE_PIECE_CARD_GAME' and r.provider_id=r.card_number
  and r.card_number ~ '^(OP|EB|PRB|ST)[0-9]{{2}}-[0-9]{{3}}$')
 or {FUSION_VERIFIED_BASE_SQL}
"""


def uk_daily_pricing_slot(now: datetime) -> datetime:
    """Last local 04:00 in Europe/London converted to UTC, including DST."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Timezone-aware now is required")
    local = now.astimezone(ZoneInfo("Europe/London"))
    slot = local.replace(hour=4, minute=0, second=0, microsecond=0)
    if local < slot:
        slot -= timedelta(days=1)
    return slot.astimezone(timezone.utc)


def daily_model_due(previous, now: datetime, *, revision: int) -> bool:
    local = now.astimezone(ZoneInfo("Europe/London"))
    if local.hour < 4:
        return False
    if previous is None:
        return True
    report = previous.get("report") or {}
    if report.get("importer_revision") != revision:
        return True
    if previous["started_at"] < uk_daily_pricing_slot(now):
        return True
    return previous["status"] != "COMPLETE" and (
        now - previous["started_at"] >= timedelta(hours=1))


def _rarity(value: str) -> str | None:
    return {
        "Common[C]": "C", "Uncommon[UC]": "UC",
        "C": "C", "UC": "UC", "Common": "C", "Uncommon": "UC",
    }.get(value)


def _printing(ref: dict) -> Printing:
    rarity = _rarity(ref["rarity"])
    if rarity is None:
        raise ValueError("Not an eligible standard C/UC card")
    return Printing(ref["provider"], ref["system_code"], ref["set_id"],
                    ref["provider_id"], ref["language"], "STANDARD", rarity)


def _peer(record: dict, now: datetime) -> PeerGuide | None:
    for amount, at, source in (
        (record["detail_minor"],record["detail_at"],record["detail_source"]),
        (record["catalogue_minor"],record["catalogue_at"],record["catalogue_source"]),
    ):
        if (type(amount) is int and amount>0 and isinstance(at,datetime)
                and at.tzinfo is not None and now-timedelta(days=7)<=at<=now
                and isinstance(source,str) and bool(source.strip())
                and not source.startswith("DROP_RATE_")):
            try:
                return PeerGuide(_printing(record),amount,at,source)
            except ValueError:
                return None
    return None


def _cohort_key(ref: dict):
    return (ref["provider"],ref["system_code"],ref["language"],
            ref["set_id"],_rarity(ref["rarity"]))


def _quote(ref: dict, value, now: datetime, sample: list[PeerGuide]) -> dict:
    reference_identity = {key:ref[key] for key in ("name","set_id","card_number","set_name")}
    return {
        "source": SOURCE, "market": "DROP_RATE",
        "observation_type": "DERIVED_NOT_SOLD",
        "valuation_role": "DROP_RATE_CALCULATED_MARKET_VALUE",
        "verification_basis": "RULES_VERIFIED_PEER_MODEL",
        "algorithm_version": ALGORITHM_VERSION,
        "method": value.method, "confidence": value.confidence,
        "price_gbp_minor": value.estimate_minor,
        "low_gbp_minor": value.low_minor,
        "high_gbp_minor": value.high_minor,
        "independent_reference_count": value.evidence_count,
        "sample_reference_ids": [
            {"source":p.source,"provider_id":p.printing.provider_id}
            for p in sample[:12]],
        "reference_printing_id": ref["provider_id"],
        "reference_rarity": ref["rarity"],
        "reference_identity": reference_identity,
        "physical_valuation_eligible": False,
        "sold_comparable": False,
        "condition_specific": False,
        "store_price_floor_minor": 100,
        "recommended_store_price_minor": store_price_floor(value.estimate_minor),
        "observed_at": now.isoformat(),
        "expires_after_days": 2,
    }


def _write_args(ref: dict, estimate, now: datetime, sample: list[PeerGuide]):
    q = _quote(ref,estimate,now,sample)
    return (
        ref["provider"],ref["system_code"],ref["language"],ref["provider_id"],
        json.dumps([q],sort_keys=True),estimate.estimate_minor,estimate.high_minor,
        now,now,now+timedelta(days=2),ref["name"],ref["set_id"],
        ref["card_number"],ref["set_name"],ref["rarity"],SOURCE,
        ref["image_url"],None,
    )


async def run_daily_reference_model(pool, actor, *, dry_run=True,
                                    limit=1000, previous_cursor=None,
                                    now=None) -> dict:
    """Evaluate one fixed-size reference batch without any external API calls.

    Applied values go only to the existing audited reference guide table.
    Exactly-matched physical inventory is NOT modified by this function.
    Owner-opted-in physical repricing must be independently verified.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError("Expected a batch between 1 and 1,000")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware now is required")
    report = {
        "source":SOURCE,"model_version":REVISION,
        "dry_run":dry_run,"input_cursor":previous_cursor,
        "cursor":previous_cursor,"examined":0,"eligible":0,
        "model_rejected":0,"writes_attempted":0,"writes_applied":0,
        "inventory_writes":0,"shopify_writes":0,
        "retail_minimum_minor":100,"scope":"CARD_CATALOGUE_ONLY",
        "excluded_systems":["NARUTO_KAYOU","NARUTO_BANDAI_LEGACY"],
    }
    async with user_connection(pool,actor,str(uuid4())) as c:
        await require_platform_admin(c)
        rows = await c.fetch(CANDIDATE_SQL,previous_cursor or "",limit)
        if not rows and previous_cursor:
            report["wrapped"] = True
            rows = await c.fetch(CANDIDATE_SQL,"",limit)
        refs = [dict(row) for row in rows]
        report["examined"] = len(refs)
        if not refs:
            return report
        report["cursor"] = refs[-1]["cursor"]
        cohorts = [
            dict(zip(("provider","system_code","language","set_id","rarity"),key))
            for key in {tuple(r[k] for k in ("provider","system_code","language","set_id","rarity"))
                        for r in refs}
        ]
        peers = await c.fetch(PEER_SQL,json.dumps(cohorts))
    by_cohort=defaultdict(list)
    for row in peers:
        candidate=_peer(dict(row),now)
        if candidate:
            by_cohort[_cohort_key(dict(row))].append(candidate)
    writes=[]
    for ref in refs:
        group=by_cohort.get(_cohort_key(ref),[])
        result=ordinary_peer_baseline(_printing(ref),group,now=now)
        if result is None:
            report["model_rejected"] += 1
            continue
        sample=sorted(group,key=lambda p:p.price_gbp_minor)
        writes.append(_write_args(ref,result,now,sample))
    report["eligible"]=len(writes)
    report["sample_values_minor"]=[r[5] for r in writes[:10]]
    if dry_run or not writes:
        return report
    async with user_connection(pool,actor,str(uuid4())) as c:
        await require_platform_admin(c)
        for offset in range(0,len(writes),100):
            chunk=writes[offset:offset+100]
            report["writes_attempted"]+=len(chunk)
            await c.executemany(WRITE_SQL,chunk)
        identifiers=[(r[0],r[1],r[2],r[3]) for r in writes]
        check=await c.fetch(
            """select provider,system_code,language,provider_id from
               tcg.reference_catalogue_prices
               where (provider,system_code,language,provider_id) in
               (select provider,system_code,language,provider_id
                from jsonb_to_recordset($1::jsonb) as x(
                 provider text,system_code text,language text,provider_id text))
                 and quotes->0->>'source'=$2 and pricing_updated_at=$3""",
            json.dumps([dict(zip(
                ("provider","system_code","language","provider_id"),x))
                for x in identifiers]),SOURCE,now)
        report["writes_applied"]=len(check)
    return report
