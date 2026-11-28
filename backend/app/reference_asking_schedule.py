"""Hourly UK eBay asking-price collection, stock first.

Owner rule (28 Nov 2026): the first price for a card is the average of what
UK sellers are asking on eBay, checked against Cardmarket. Until now nothing
collected those asking prices on a schedule, so the rule had no data.

This module only chooses which cards to ask about and when. Every Browse
call, quota reservation, identity check, median and outlier rule stays in
``reference_asking_backfill`` and ``reference_asking_estimator``. It writes
asking evidence for catalogue references only: never inventory rows, Store
Prices, Shopify, ownership or sold observations.

Priority each hour:
  1. cards the business holds as approved stock;
  2. the catalogue cards with the highest Cardmarket guide value.
A card is skipped while it has a current asking price, and for three days
after it was last asked about, so one card that eBay cannot price does not
spend the allowance again every hour.

The selection is four small reads combined in Python. One statement joining
stock, both price tables and every catalogue card took 11 to 62 seconds in
production; each read below is an index lookup or a bounded top-N.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .ebay_official_client import EbayOfficialClient
from .reference_applicability import DIGITAL_REFERENCE_SQL
from .reference_asking_backfill import (
    BackfillStop, MAX_DAILY, MAX_TARGET_REFERENCES, backfill_reference_asking,
)
from .reference_asking_estimator import _aspects, estimate_reference_asking_price

log = logging.getLogger(__name__)

KEYS = ("provider", "system_code", "language", "provider_id")
SYSTEMS = ["POKEMON_TCG", "ONE_PIECE_CARD_GAME", "DRAGON_BALL_SUPER_MASTERS",
           "DRAGON_BALL_SUPER_FUSION_WORLD"]
LANGUAGES = ["English", "Japanese"]
TARGETS_PER_RUN = MAX_TARGET_REFERENCES
# One search plus at most six item details per card.
MAX_QUERIES_PER_RUN = TARGETS_PER_RUN * 7
ATTEMPT_MEMORY = timedelta(days=3)
RUN_TIMEOUT_SECONDS = 600
RUN_EVERY_MINUTES = 15
DAILY_HEADROOM = 10
# How many of the highest guide values are considered beyond stock each hour,
# and how many candidates are checked against the catalogue per run.
CATALOGUE_POOL = 2000
VALIDATE_LIMIT = 200

STATE_SQL = """select
 max(started_at) filter (where actor_user_id=$1
   and jsonb_typeof(report#>'{scope,reference_keys}')='array') as last_started,
 coalesce(sum(requests) filter (
   where budget_day=(clock_timestamp() at time zone 'UTC')::date),0)::integer as used_today
 from tcg.reference_asking_runs
 where started_at>=clock_timestamp()-interval '2 days'"""

# Reference cards for approved stock. ``held`` carries plain columns so both
# joins are equality joins on indexed or hashable values.
STOCK_SQL = """with held as materialized (
 select distinct i.language,lower(p.name) as name,lower(p.set_name) as set_name,
  upper(replace(p.card_number,' ','')) as card_number,
  case p.game when 'Pokemon' then 'POKEMON_TCG' when 'One Piece' then 'ONE_PIECE_CARD_GAME'
   when 'Dragon Ball Super' then 'DRAGON_BALL_SUPER_MASTERS'
   when 'Dragon Ball Super Fusion World' then 'DRAGON_BALL_SUPER_FUSION_WORLD' end as system_code
 from tcg.inventory_items i
 join tcg.catalogue_products p on p.id=i.catalogue_id and p.product_type='CARD'
 where i.status='APPROVED'
)
select r.provider,r.system_code,r.language,r.provider_id
 from held h
 join tcg.reference_cards r on r.system_code=h.system_code and r.language=h.language
  and lower(r.name)=h.name and r.provider='TCGdex'
 join tcg.reference_sets s on (s.provider,s.system_code,s.language,s.set_id)=
  (r.provider,r.system_code,r.language,r.set_id)
 where h.system_code='POKEMON_TCG' and lower(s.name)=h.set_name
union
select r.provider,r.system_code,r.language,r.provider_id
 from held h
 join tcg.reference_cards r on r.system_code=h.system_code and r.language=h.language
  and r.card_number=h.card_number
 where h.system_code<>'POKEMON_TCG'
  and (r.provider='Bandai Official'
       or (r.provider='Punk Records' and r.system_code='ONE_PIECE_CARD_GAME'))"""

TOP_GUIDE_SQL = """(select provider,system_code,language,provider_id,market_value_minor as guide_minor
  from tcg.reference_market_prices
  where market_value_minor>0 and system_code=any($1::text[]) and language=any($2::text[])
  order by market_value_minor desc limit $3)
union all
(select provider,system_code,language,provider_id,market_value_minor as guide_minor
  from tcg.reference_catalogue_prices
  where market_value_minor>0 and system_code=any($1::text[]) and language=any($2::text[])
  order by market_value_minor desc limit $3)"""

# Cards with a current asking price, and cards the collector already moved
# past since $1. The row comparison is the collector's own cursor order.
BUSY_SQL = """select provider,system_code,language,provider_id
 from tcg.reference_asking_prices where expires_at>now()
union
select k->>0,k->>1,k->>2,k->>3
 from tcg.reference_asking_runs run,
  jsonb_array_elements(run.report#>'{scope,reference_keys}') k
 where run.started_at>=$1
  and jsonb_typeof(run.report#>'{scope,reference_keys}')='array'
  and (run.status='COMPLETE' or (jsonb_typeof(run.report->'cursor')='array'
    and (k->>0,k->>1,k->>2,k->>3)<=(run.report->'cursor'->>0,run.report->'cursor'->>1,
      run.report->'cursor'->>2,run.report->'cursor'->>3)))"""

VALID_SQL = f"""with wanted as materialized (
 select * from jsonb_to_recordset($1::jsonb) as x(
   provider text,system_code text,language text,provider_id text)
)
select r.provider,r.system_code,r.language,r.provider_id,
 greatest(coalesce(m.market_value_minor,0),coalesce(b.market_value_minor,0)) as guide_minor
 from wanted w
 join tcg.reference_cards r using(provider,system_code,language,provider_id)
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices m using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 where r.language=any($2::text[]) and (s.release_date is null or s.release_date<=current_date)
  and not ({DIGITAL_REFERENCE_SQL})"""


def schedule_enabled(settings):
    """Collection needs the UK eBay application and the shop postcode."""
    return bool(getattr(settings, "ebay_asking_schedule_enabled", True)
                and getattr(settings, "ebay_client_id", None)
                and getattr(settings, "ebay_client_secret", None)
                and getattr(settings, "ebay_marketplace_id", None) == "EBAY_GB"
                and getattr(settings, "ebay_origin_postcode", None)
                and getattr(settings, "catalogue_maintenance_actor_user_id", None))


def schedule_due(last_started, now, used_today):
    """One bounded run per quarter hour while today's allowance has room.

    A run spends about 40 to 175 Browse calls on 25 cards. Hourly runs left
    half of the 2,000-call day unused and took a day to pass over stock.
    """
    if used_today >= MAX_DAILY - DAILY_HEADROOM:
        return False
    now = now.astimezone(timezone.utc)
    slot = now.replace(minute=now.minute - now.minute % RUN_EVERY_MINUTES, second=0, microsecond=0)
    return last_started is None or last_started < slot


def _key(row):
    return tuple(row[name] for name in KEYS)


def candidate_keys(stock_rows, guide_rows, busy_rows, *, limit=VALIDATE_LIMIT):
    """Stock first, then the highest guide values; busy cards are left out.

    Returns ``(keys, held)``: an ordered, de-duplicated list and the set of
    keys that are stock. A stock card is never crowded out by the catalogue.
    """
    busy = {_key(row) for row in busy_rows}
    held = {_key(row) for row in stock_rows} - busy
    ordered = sorted(held)
    seen = set(ordered)
    for row in sorted(guide_rows, key=lambda row: (-row["guide_minor"], _key(row))):
        key = _key(row)
        if key in busy or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered[:max(limit, len(held))], held


def target_keys(valid_rows, held):
    """Exact reference keys for the collector, bounded by its own limits."""
    ranked = sorted(valid_rows, key=lambda row: (_key(row) not in held, -row["guide_minor"], _key(row)))
    keys = [list(_key(row)) for row in ranked][:TARGETS_PER_RUN]
    while keys and len(json.dumps(keys, ensure_ascii=False).encode()) > 4000:
        keys.pop()
    return keys


def run_summary(report, targets, held):
    stats = report.get("stats") or {}
    return {"status": report.get("status"), "stop_reason": report.get("stop_reason"),
            "run_id": report.get("run_id"), "targets": targets, "stock_targets": held,
            "requests": report.get("session_requests"),
            "searched": stats.get("collected"), "priced": stats.get("matched"),
            "written": stats.get("written"), "rejections": report.get("rejections")}


LOGGED_ASPECTS = ("set", "language", "card number", "finish", "card condition", "features", "rarity")


def log_listing_outcomes(reference, details, estimate, observed):
    """One log line per listing read, and one per card: what was decided.

    This is how the matching rules are tuned from real listings. It logs the
    public title, price and a few item specifics; never the seller.
    """
    card = "/".join(str(reference.get(name)) for name in ("system_code", "language", "provider_id"))
    for row in details:
        single = estimate_reference_asking_price(reference, [row], observed_at=observed, now=observed)
        aspects = _aspects(row)
        price = row.get("price") if isinstance(row.get("price"), dict) else {}
        log.warning("EBAY_ASKING_LISTING %s", json.dumps({
            "card": card, "decision": next(iter(single["rejection_counts"]), "ACCEPTED"),
            "title": str(row.get("title", ""))[:110], "price": price.get("value"),
            "specifics": {name: aspects[name][:60] for name in LOGGED_ASPECTS if name in aspects},
        }, ensure_ascii=False, sort_keys=True))
    log.warning("EBAY_ASKING_CARD %s", json.dumps({
        "card": card, "name": reference.get("name"), "number": reference.get("card_number"),
        "set": reference.get("set_name"), "status": estimate.get("status"),
        "listings_read": len(details), "sellers": estimate.get("seller_count"),
        "estimate_minor": estimate.get("estimate_minor"),
    }, ensure_ascii=False, sort_keys=True))


async def choose_targets(connection, now):
    stock = await connection.fetch(STOCK_SQL)
    guide = await connection.fetch(TOP_GUIDE_SQL, SYSTEMS, LANGUAGES, CATALOGUE_POOL)
    busy = await connection.fetch(BUSY_SQL, now - ATTEMPT_MEMORY)
    candidates, held = candidate_keys(stock, guide, busy)
    if not candidates:
        return [], 0
    wanted = [dict(zip(KEYS, key)) for key in candidates]
    valid = await connection.fetch(VALID_SQL, json.dumps(wanted), LANGUAGES)
    targets = target_keys(valid, held)
    return targets, sum(1 for key in targets if tuple(key) in held)


async def scheduled_asking_pass(pool, actor, settings, *, now=None, client=None,
                                collect=backfill_reference_asking):
    """Ask eBay about the next priority cards. Returns a summary or None."""
    if not schedule_enabled(settings):
        return None
    now = now or datetime.now(timezone.utc)
    async with user_connection(pool, actor, "asking-schedule-" + str(uuid4())) as connection:
        await require_platform_admin(connection)
        state = await connection.fetchrow(STATE_SQL, actor)
        if not schedule_due(state["last_started"], now, state["used_today"]):
            return None
        targets, held = await choose_targets(connection, now)
    if not targets:
        return None
    if client is None:
        client = EbayOfficialClient(
            client_id=settings.ebay_client_id, client_secret=settings.ebay_client_secret,
            marketplace_id="EBAY_GB", timeout_seconds=20,
            buyer_country="GB", buyer_postal_code=settings.ebay_origin_postcode)
    try:
        report = await asyncio.wait_for(collect(
            pool, actor, client, run=True, apply=True, max_queries=MAX_QUERIES_PER_RUN,
            include_priced=True, reference_keys=targets,
            postcode=settings.ebay_origin_postcode, observe=log_listing_outcomes),
            timeout=RUN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.error("EBAY_ASKING_SCHEDULE_TIMEOUT targets=%s", len(targets))
        return {"status": "TIMEOUT", "targets": len(targets), "stock_targets": held}
    except (BackfillStop, ValueError) as exc:
        log.error("EBAY_ASKING_SCHEDULE_STOPPED %s", getattr(exc, "code", type(exc).__name__))
        return {"status": "STOPPED", "stop_reason": getattr(exc, "code", type(exc).__name__),
                "targets": len(targets), "stock_targets": held}
    summary = run_summary(report, len(targets), held)
    log.warning("EBAY_ASKING_SCHEDULE %s", json.dumps(summary, sort_keys=True, default=str))
    return summary
