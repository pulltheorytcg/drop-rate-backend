"""Public catalogue price references, separate from physical inventory pricing.

TCGdex checklist responses omit pricing. Fetch card details only for displayed
English/Japanese references and require explicit, finish-specific marketplace IDs. These
quotes never confirm a printing, value a slab, or change a Store Price.
"""
from __future__ import annotations

import asyncio
import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import quote

import httpx

from .db import user_connection
from .fx import EcbHistoricalFxProvider


SOURCE = "TCGDEX_CARDMARKET"
SUPPORT_SOURCE = "TCGDEX_TCGPLAYER"
REVISION = 2
LOCALES = {"English": "en", "Japanese": "ja"}
MAX_AGE = timedelta(days=7)
FINISHES = {"normal": ("normal", "Normal"), "holo": ("holofoil", "Holofoil"),
            "reverse": ("reverse-holofoil", "Reverse Holofoil")}
_requests = asyncio.Semaphore(6)

READ_SQL = """
select 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id)) as key,
       r.provider,r.system_code,r.language,r.provider_id,r.set_id,r.name,r.card_number,
       s.name as set_name,c.quotes,c.checked_at,c.expires_at,c.refresh_revision
from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_market_prices c using(provider,system_code,language,provider_id)
where r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language in ('English','Japanese')
  and (s.release_date is null or s.release_date<=current_date)
  and 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id))=any($1::text[])
"""
WRITE_SQL = """
insert into tcg.reference_market_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at,refresh_revision)
values($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,2)
on conflict(provider,system_code,language,provider_id) do update
set quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
    market_value_high_minor=excluded.market_value_high_minor,
    pricing_updated_at=excluded.pricing_updated_at,checked_at=excluded.checked_at,expires_at=excluded.expires_at,
    refresh_revision=excluded.refresh_revision
where tcg.reference_market_prices.checked_at<=excluded.checked_at
"""


def _text(value) -> str:
    return unicodedata.normalize("NFKC", html.unescape(str(value or ""))).strip().casefold()


def _number(value) -> str:
    value = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    return str(int(value)) if value.isdigit() else value


def _time(value) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Provider timestamp needs a timezone")
    return stamp


def _minor(value) -> int:
    if isinstance(value, bool):
        raise ValueError("Invalid price")
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0 or amount > 10_000_000:
        raise ValueError("Invalid price")
    result = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if result <= 0:
        raise ValueError("Invalid price")
    return result


async def tcgdex_quotes(payload: dict, reference: dict, fx, *, now: datetime, language="English") -> list[dict]:
    # The request locale is part of identity, not inferred from translated names.
    if (reference.get("provider") != "TCGdex" or reference.get("system_code") != "POKEMON_TCG"
            or language not in LOCALES or reference.get("language") != language):
        return []
    card_set = payload.get("set") or {}
    if (payload.get("id") != reference["provider_id"] or card_set.get("id") != reference["set_id"]
            or _text(payload.get("name")) != _text(reference["name"])
            or _text(card_set.get("name")) != _text(reference["set_name"])
            or _number(payload.get("localId")) != _number(reference["card_number"].split("/")[0])):
        return []
    variants = payload.get("variants_detailed")
    if not isinstance(variants, list) or len(variants) > 40:
        return []
    result = {}
    conflicts = set()
    for variant in variants:
        if not isinstance(variant, dict) or variant.get("size") != "standard" or variant.get("type") not in FINISHES:
            continue
        # Named/stamped/first-edition treatments must never inherit a base quote.
        if variant.get("subtype") or variant.get("stamp") or variant.get("firstEdition"):
            continue
        finish_key, finish_label = FINISHES[variant["type"]]
        try:
            marketplace_id = (variant.get("thirdParty") or {}).get("cardmarket")
            variant_id = variant.get("variantId")
            market = (variant.get("pricing") or {}).get("cardmarket") or {}
            finishes = payload.get("variants") or {}
            # Cardmarket's base field is the base SKU (which can itself be
            # holo); its -holo field prices the alternative foil treatment.
            # Require declared finish availability before choosing either.
            if finishes.get(variant["type"]) is not True:
                continue
            field = "trend"
            if variant["type"] == "reverse":
                if finishes.get("normal") is True and finishes.get("holo") is True:
                    continue  # Two foil treatments share the aggregate.
                field = "trend-holo"
            elif variant["type"] == "holo":
                if finishes.get("normal") is True:
                    if finishes.get("reverse") is not False:
                        continue
                    field = "trend-holo"
                elif finishes.get("normal") is not False:
                    continue
            if (not variant_id or not str(marketplace_id).isdigit() or int(marketplace_id) <= 0
                    or str(market.get("idProduct")) != str(marketplace_id) or market.get("unit") != "EUR"):
                continue
            observed = _time(market.get("updated"))
            if not now - MAX_AGE <= observed <= now + timedelta(hours=1):
                continue
            original = _minor(market.get(field))
            conversion = await fx.quote(base_currency="EUR", quote_currency="GBP", at=observed)
            gbp = int((Decimal(original) * conversion.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if gbp <= 0:
                continue
            row = {"finish": finish_label, "variant_id": str(variant_id), "product_id": str(marketplace_id),
                   "source": SOURCE, "original_currency": "EUR", "source_field": field, "original_minor": original,
                   "price_gbp_minor": gbp, "observed_at": observed.isoformat(),
                   "fx_rate_to_gbp": str(conversion.rate), "fx_source": conversion.source,
                   "fx_effective_at": conversion.effective_at.isoformat(),
                   "fx_retrieved_at": conversion.retrieved_at.isoformat()}
        except (ValueError, TypeError, InvalidOperation, AttributeError):
            continue
        # A broad printing with two different treatments of the same finish is
        # ambiguous. Do not select whichever happened to arrive last.
        if finish_key in result and result[finish_key] != row:
            conflicts.add(finish_key)
        result[finish_key] = row
    # TCGplayer supplies US context only. Never turn its USD market price into
    # a UK valuation, and never inherit a root-level or different-finish quote.
    support = {}
    support_conflicts = set()
    for variant in variants:
        if (not isinstance(variant, dict) or variant.get("size") != "standard"
                or variant.get("type") not in FINISHES or variant.get("subtype")
                or variant.get("stamp") or variant.get("firstEdition")):
            continue
        finish_key, finish_label = FINISHES[variant["type"]]
        try:
            if (payload.get("variants") or {}).get(variant["type"]) is not True:
                continue
            variant_id = variant.get("variantId")
            product_id = (variant.get("thirdParty") or {}).get("tcgplayer")
            market = (variant.get("pricing") or {}).get("tcgplayer") or {}
            price = market.get(finish_key) or {}
            if (not variant_id or not str(product_id).isdigit() or int(product_id) <= 0
                    or str(price.get("productId")) != str(product_id) or market.get("unit") != "USD"):
                continue
            observed = _time(market.get("updated"))
            if not now - MAX_AGE <= observed <= now + timedelta(hours=1):
                continue
            row = {"finish": finish_label, "variant_id": str(variant_id), "product_id": str(product_id),
                   "source": SUPPORT_SOURCE, "original_currency": "USD", "source_field": "marketPrice",
                   "original_minor": _minor(price.get("marketPrice")), "observed_at": observed.isoformat(),
                   "valuation_role": "US_CONTEXT_ONLY", "reference_language": language}
        except (ValueError, TypeError, InvalidOperation, AttributeError):
            continue
        if finish_key in support and support[finish_key] != row:
            support_conflicts.add(finish_key)
        support[finish_key] = row
    return ([dict(row, reference_language=language, valuation_role="UK_REFERENCE")
             for key, row in result.items() if key not in conflicts]
            + [row for key, row in support.items() if key not in support_conflicts])


def price_view(key: str, quotes: list[dict], *, now: datetime) -> dict:
    current = []
    for row in quotes:
        try:
            if row.get("source") in {SOURCE, SUPPORT_SOURCE} and now - MAX_AGE <= _time(row["observed_at"]) <= now + timedelta(hours=1):
                current.append(row)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    values = [row["price_gbp_minor"] for row in current if row["source"] == SOURCE]
    return {"key": key, "market_value_minor": min(values) if values else None,
            "market_value_high_minor": max(values) if values else None,
            "basis_condition": "Raw · Cardmarket" if values else None,
            "pricing_updated_at": min((_time(row["observed_at"]) for row in current
                                       if not values or row["source"] == SOURCE), default=None),
            "market_value_source": SOURCE if values else (SUPPORT_SOURCE if current else None),
            "market_quotes": current, "market_refresh_needed": False}


async def fetch_quotes(client, reference, fx, *, now):
    # Never fetch a caller-supplied URL. Exact IDs come from the master catalogue.
    locale = LOCALES[reference["language"]]
    url = "https://api.tcgdex.net/v2/" + locale + "/cards/" + quote(reference["provider_id"], safe="")
    async with _requests:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            body = bytearray()
            async for part in response.aiter_bytes():
                body.extend(part)
                if len(body) > 1_000_000:
                    raise ValueError("Provider response too large")
    import json
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Invalid provider response")
    return await tcgdex_quotes(payload, reference, fx, now=now, language=reference["language"])


async def refresh_reference_prices(pool, user_id, request_id, keys: list[str], *, fx_provider=None, force=False) -> list[dict]:
    async with user_connection(pool, user_id, request_id) as connection:
        references = [dict(row) for row in await connection.fetch(READ_SQL, keys)]
    now = datetime.now(timezone.utc)
    fx = fx_provider or EcbHistoricalFxProvider(timeout_seconds=6)
    async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
        async def refresh(reference):
            previous = reference.get("quotes") or []
            if not force and reference.get("refresh_revision", REVISION) == REVISION and reference.get("expires_at") and reference["expires_at"] > now:
                return reference, price_view(reference["key"], previous, now=now), None
            try:
                quotes = await asyncio.wait_for(fetch_quotes(client, reference, fx, now=now), timeout=15)
                expires = now + timedelta(hours=24 if quotes else 6)
                failed = False
            except (httpx.HTTPError, ValueError, RuntimeError, TypeError, AttributeError, asyncio.TimeoutError):
                # A provider outage doesn't erase a recent known quote. Retry
                # after five minutes, and always keep the source's original date.
                quotes = previous
                expires = now + timedelta(minutes=5)
                failed = True
            view = price_view(reference["key"], quotes, now=now)
            view['provider_refresh_failed'] = failed
            return reference, view, expires
        results = await asyncio.gather(*(refresh(reference) for reference in references))
    async with user_connection(pool, user_id, request_id) as connection:
        for reference, view, expires in results:
            if expires is not None:
                await connection.execute(WRITE_SQL, reference["provider"], reference["system_code"], reference["language"],
                    reference["provider_id"], view["market_quotes"], view["market_value_minor"], view["market_value_high_minor"],
                    view["pricing_updated_at"], now, expires)
    return [view for _, view, _ in results]
