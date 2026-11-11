"""Exact regional sale aggregates for catalogue presentation only."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

from .db import user_connection
from .fx import EcbHistoricalFxProvider
from .reference_market import MAX_AGE, READ_SQL, WRITE_SQL, _cache_is_current, _time, fetch_quotes, price_view


# Short-lived entries coalesce concurrent lookups. Positive observations also
# enter the existing catalogue cache for future requests and worker restarts.
_cache = OrderedDict()
_locks = [asyncio.Lock() for _ in range(4)]


def eligible_quotes(rows, now):
    result = []
    for row in rows:
        sale = row.get("regional_sale") or {}
        if (sale.get("physical_valuation_eligible") is not False
                or type(sale.get("price_gbp_minor")) is not int or sale["price_gbp_minor"] <= 0
                or not row.get("variant_id") or not row.get("product_id")):
            continue
        pair = (row.get("source"), sale.get("region"), sale.get("source_field"))
        if pair not in {("TCGDEX_CARDMARKET", "EU", "avg7"), ("TCGDEX_CARDMARKET", "EU", "avg7-holo"),
                        ("TCGDEX_CARDMARKET_VARIANT", "EU", "avg7"), ("TCGDEX_CARDMARKET_VARIANT", "EU", "avg7-holo"),
                        ("TCGDEX_TCGPLAYER", "US", "marketPrice")}:
            continue
        try:
            observed = _time(row["observed_at"])
        except (ValueError, TypeError, KeyError):
            continue
        if now - MAX_AGE <= observed <= now:
            result.append(row)
    return result


def _identity(row):
    return tuple(row.get(k) for k in ("key", "set_id", "set_name", "name", "card_number", "language"))


def attach_cached_regional_prices(rows):
    """Return cached observations on catalogue pages without provider calls."""
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.get("provider") == "TCGdex" and row.get("source_kind") == "REFERENCE":
            cached = _cache.get(_identity(row))
            if cached and cached[0] > now:
                row["regional_quotes"] = eligible_quotes(cached[1], now)
    return rows


async def regional_prices_for_reference(pool, user_id, request_id, key):
    now = datetime.now(timezone.utc)
    async with user_connection(pool, user_id, request_id) as connection:
        records = await connection.fetch(READ_SQL, [key])
    if not records:
        raise HTTPException(404, "Unknown regional price reference")
    reference = dict(records[0])
    if _cache_is_current(reference.get("expires_at"), now):
        rows = eligible_quotes(reference.get("quotes") or [], now)
        if rows:
            return {"quotes": rows}
    identity = _identity(reference)
    async with _locks[int(key[-2:], 16) % len(_locks)]:
        now = datetime.now(timezone.utc)
        cached = _cache.get(identity)
        if cached and cached[0] > now:
            return {"quotes": eligible_quotes(cached[1], now)}
        try:
            async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
                quotes = await asyncio.wait_for(fetch_quotes(client, reference, EcbHistoricalFxProvider(timeout_seconds=6),
                                                             now=now), timeout=16)
        except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
            raise HTTPException(503, "Regional price feed temporarily unavailable") from None
        rows = eligible_quotes(quotes, now)
        if rows:
            view = price_view(key, quotes, now=now)
            async with user_connection(pool, user_id, request_id) as connection:
                await connection.execute(WRITE_SQL, reference["provider"], reference["system_code"],
                                         reference["language"], reference["provider_id"], quotes,
                                         view["market_value_minor"], view["market_value_high_minor"],
                                         view["pricing_updated_at"], now, now + timedelta(days=1))
        _cache[identity] = (now + timedelta(minutes=30 if rows else 5), rows)
        _cache.move_to_end(identity)
        if len(_cache) > 512:
            _cache.popitem(last=False)
        return {"quotes": rows}
