"""Public catalogue price references, separate from physical inventory pricing.

TCGdex checklist responses omit pricing. Daily work covers every English/Japanese
reference; a displayed card may also request a bounded refresh. Require explicit,
finish-specific marketplace IDs. These
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
VARIANT_SOURCE = "TCGDEX_CARDMARKET_VARIANT"
CATALOGUE_SOURCE = "CARDMARKET_CATALOGUE"
SUPPORT_SOURCE = "TCGDEX_TCGPLAYER"
REVISION = 3
LOCALES = {"English": "en", "Japanese": "ja"}
MAX_AGE = timedelta(days=7)
FINISHES = {"normal": ("normal", "Normal"), "holo": ("holofoil", "Holofoil"),
            "reverse": ("reverse-holofoil", "Reverse Holofoil")}
_requests = asyncio.Semaphore(6)

READ_SQL = """
select 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id)) as key,
       r.provider,r.system_code,r.language,r.provider_id,r.set_id,r.name,r.card_number,
       s.name as set_name,c.quotes,c.checked_at,c.expires_at,c.refresh_revision,
       b.quotes as catalogue_quotes
from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_market_prices c using(provider,system_code,language,provider_id)
left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
where r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language in ('English','Japanese')
  and (s.release_date is null or s.release_date<=current_date)
  and 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id))=any($1::text[])
"""
WRITE_SQL = """
insert into tcg.reference_market_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at,refresh_revision)
values($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,3)
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


def variant_details(variant):
    """Keep named treatments as their own references, never a base-card quote."""
    subtype = variant.get('subtype') or ''
    stamps = variant.get('stamp') or []
    first = variant.get('firstEdition', False)
    if (not isinstance(subtype,str) or len(subtype)>100 or not isinstance(stamps,list)
            or len(stamps)>8 or any(not isinstance(s,str) or not s or len(s)>100 for s in stamps)
            or type(first) is not bool):
        return None
    labels = [subtype] if subtype else []
    labels.extend(sorted(set(stamps)))
    if first and '1st-edition' not in labels:
        labels.append('1st-edition')
    return ' · '.join(labels)


def distinct_quotes(rows):
    # Some provider variants incorrectly share a marketplace ID across editions.
    # The ID+price-field must identify only one treatment. Normal/reverse fields
    # of the same product remain distinct. Never choose the first priced edition.
    identities = {}
    conflicts = set()
    for key,row in rows.items():
        product = (row['product_id'],row['source_field'],row.get('market_finish'))
        if product in identities and identities[product] != key:
            conflicts.update((identities[product],key))
        identities[product] = key
    return [row for key,row in rows.items() if key not in conflicts]


def ambiguous_ids(variants, marketplace):
    identities = {}
    for variant in variants:
        if not isinstance(variant,dict) or variant.get('size')!='standard' or variant.get('type') not in FINISHES:
            continue
        product_id = (variant.get('thirdParty') or {}).get(marketplace)
        if product_id is None:
            continue
        key = (str(product_id),FINISHES[variant['type']][0])
        identity = (str(variant.get('variantId')),variant_details(variant))
        identities.setdefault(key,set()).add(identity)
    # Include unpriced variants: availability of a quote cannot prove identity.
    return {key for key,values in identities.items() if len(values)>1}


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
    ambiguous_cardmarket = ambiguous_ids(variants,'cardmarket')
    ambiguous_tcgplayer = ambiguous_ids(variants,'tcgplayer')
    for variant in variants:
        if not isinstance(variant, dict) or variant.get("size") != "standard" or variant.get("type") not in FINISHES:
            continue
        treatment = variant_details(variant)
        if treatment is None:
            continue
        finish_key, finish_label = FINISHES[variant["type"]]
        key = (finish_key,treatment)
        try:
            marketplace_id = (variant.get("thirdParty") or {}).get("cardmarket")
            if (str(marketplace_id),finish_key) in ambiguous_cardmarket:
                continue
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
                   "source": VARIANT_SOURCE if treatment else SOURCE,
                   "variant_label": ' · '.join(filter(None,(finish_label,treatment))),
                   "physical_valuation_eligible": not bool(treatment),
                   "original_currency": "EUR", "source_field": field, "original_minor": original,
                   "price_gbp_minor": gbp, "observed_at": observed.isoformat(),
                   "fx_rate_to_gbp": str(conversion.rate), "fx_source": conversion.source,
                   "fx_effective_at": conversion.effective_at.isoformat(),
                   "fx_retrieved_at": conversion.retrieved_at.isoformat()}
        except (ValueError, TypeError, InvalidOperation, AttributeError):
            continue
        # A broad printing with two different treatments of the same finish is
        # ambiguous. Do not select whichever happened to arrive last.
        if key in result and result[key] != row:
            conflicts.add(key)
        result[key] = row
    # TCGplayer supplies US context only. Never turn its USD market price into
    # a UK valuation, and never inherit a root-level or different-finish quote.
    support = {}
    support_conflicts = set()
    for variant in variants:
        if (not isinstance(variant, dict) or variant.get("size") != "standard"
                or variant.get("type") not in FINISHES):
            continue
        treatment = variant_details(variant)
        if treatment is None:
            continue
        finish_key, finish_label = FINISHES[variant["type"]]
        key = (finish_key,treatment)
        try:
            if (payload.get("variants") or {}).get(variant["type"]) is not True:
                continue
            variant_id = variant.get("variantId")
            product_id = (variant.get("thirdParty") or {}).get("tcgplayer")
            if (str(product_id),finish_key) in ambiguous_tcgplayer:
                continue
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
                   "market_finish": finish_key,
                   "variant_label": ' · '.join(filter(None,(finish_label,treatment))),
                   "original_minor": _minor(price.get("marketPrice")), "observed_at": observed.isoformat(),
                   "valuation_role": "US_CONTEXT_ONLY", "reference_language": language}
        except (ValueError, TypeError, InvalidOperation, AttributeError):
            continue
        if key in support and support[key] != row:
            support_conflicts.add(key)
        support[key] = row
    quotes = ([dict(row, reference_language=language,
                   valuation_role="VARIANT_REFERENCE" if row['source']==VARIANT_SOURCE else "UK_REFERENCE")
               for row in distinct_quotes({key:row for key,row in result.items() if key not in conflicts})]
              + distinct_quotes({key:row for key,row in support.items() if key not in support_conflicts}))
    return quotes if len(quotes)<=40 else []


def price_view(key: str, quotes: list[dict], *, now: datetime) -> dict:
    current = []
    for row in quotes:
        try:
            if row.get("source") in {SOURCE, VARIANT_SOURCE, CATALOGUE_SOURCE, SUPPORT_SOURCE} and now - MAX_AGE <= _time(row["observed_at"]) <= now + timedelta(hours=1):
                current.append(row)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    priced = [row for row in current if row['source'] in {SOURCE,VARIANT_SOURCE}]
    if not priced:
        priced = [row for row in current if row['source']==CATALOGUE_SOURCE]
    values = [row['price_gbp_minor'] for row in priced]
    source = (SOURCE if any(row['source']==SOURCE for row in priced) else priced[0]['source']) if priced else None
    return {"key": key, "market_value_minor": min(values) if values else None,
            "market_value_high_minor": max(values) if values else None,
            "basis_condition": ("Raw · Cardmarket mixed-language guide" if source==CATALOGUE_SOURCE else "Raw · Cardmarket") if values else None,
            "pricing_updated_at": min((_time(row["observed_at"]) for row in (priced or current)), default=None),
            "market_value_source": source or (SUPPORT_SOURCE if current else None),
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
    output = []
    for reference,view,_ in results:
        identity = {key:reference[key] for key in ('name','set_id','card_number','set_name')}
        fallback = [q for q in reference.get('catalogue_quotes') or []
                    if q.get('source')==CATALOGUE_SOURCE and q.get('reference_identity')==identity]
        if view['market_value_minor'] is None and fallback:
            combined = price_view(reference['key'],fallback+view['market_quotes'],now=now)
            view.update(combined)
        output.append(view)
    return output
