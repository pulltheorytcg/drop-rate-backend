"""Free-tier Japanese Pokémon Cardmarket *catalogue* guides.

PokéWallet's free `/sets` endpoint identifies Japanese releases, and its
paginated free `/search` endpoint exposes per-printing Cardmarket aggregates.
Set-detail card listings explicitly contain empty price arrays. Neither these mixed-language guides
nor an exact catalogue identifier prices a particular seller's physical card.

Require a unique JP release code on both checklists, an identical complete
collector fraction, a unique *printing* across the whole paginated set, and
an explicit Cardmarket single URL. Never select a cheaper/sole priced parallel.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .db import user_connection
from .pokewallet_one_piece_market import WRITE_SQL
from .reference_market import _minor

log = logging.getLogger(__name__)
SOURCE = "POKEWALLET_POKEMON_CARDMARKET_CATALOGUE"
SYSTEM = "POKEMON_TCG"
PROVIDER = "TCGdex"
BASE_URL = "https://api.pokewallet.io"
PAGE_SIZE = 100
MAX_REQUESTS_PER_HOUR = 7
COLLECTOR = re.compile(r"0*([1-9]\d{0,3})/0*([1-9]\d{0,3})\Z")
SET_CODE = re.compile(r"[a-zA-Z][a-zA-Z0-9]{0,17}\Z")
# Cardmarket-only releases use negative IDs in the documented /sets contract.
# Keep the literal source ID; a sign is not a release or language alias.
NUMERIC_SET_ID = re.compile(r"-?[1-9][0-9]{0,9}\Z")
# Provider examples include a `pk_` TCGPlayer digest longer than 80 hex
# characters; Cardmarket-only identifiers are unprefixed 64-hex hashes.
# This is format validation, never a substitute for a full print match.
SOURCE_ID = re.compile(r"(?:pk_[a-fA-F0-9]{32,128}|[a-fA-F0-9]{64})\Z")

READ_SQL = """select r.provider,r.system_code,r.language,r.provider_id,r.name,r.set_id,
 r.card_number,r.rarity,s.name as set_name,
 (coalesce(p.market_value_minor,0)>0 and
  p.pricing_updated_at>=now()-interval '7 days') as has_detail_value,
 coalesce(b.market_value_minor,0) as existing_catalogue_value,
 b.quotes->0->>'source' as existing_source,
 b.pricing_updated_at as existing_pricing_updated_at
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 where r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='Japanese'
 and (s.release_date is null or s.release_date<=current_date)"""


class ProviderResponseError(ValueError):
    """Unknown release, incomplete pagination or free-tier exhaustion."""


def collector_fraction(value: object) -> tuple[int, int] | None:
    match = COLLECTOR.fullmatch(str(value or "").strip())
    return (int(match[1]), int(match[2])) if match else None


def reference_code(ref: dict) -> str | None:
    if any(ref.get(k) != v for k, v in (
            ("provider", PROVIDER), ("system_code", SYSTEM), ("language", "Japanese"))):
        return None
    code = str(ref.get("set_id") or "")
    number = collector_fraction(ref.get("card_number"))
    provider_id = str(ref.get("provider_id") or "")
    if not SET_CODE.fullmatch(code) or not number:
        return None
    # TCGdex's local suffix must corroborate the printed numerator. Other
    # local IDs are not a proof of this provider's collector-number mapping.
    suffix = provider_id[len(code)+1:] if provider_id.casefold().startswith(code.casefold()+"-") else ""
    if not suffix.isdigit() or int(suffix) != number[0]:
        return None
    return code.casefold()


def reference_groups(refs: list[dict], now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    all_numbers = defaultdict(list)
    for ref in refs:
        code = reference_code(ref)
        if code:
            all_numbers[(code, collector_fraction(ref["card_number"]))].append(ref)
    # A canonical collision is just as dangerous as a source collision.
    wanted = {}
    for key, rows in all_numbers.items():
        if len(rows) != 1:
            continue
        ref = rows[0]
        if ref.get("has_detail_value"):
            continue
        if int(ref.get("existing_catalogue_value") or 0) > 0:
            # An independent adapter retains ownership of its positive guide.
            # Our own source must be revisited before its seven-day display
            # window expires; merely having a cached value is not freshness.
            updated = ref.get("existing_pricing_updated_at")
            if (ref.get("existing_source") != SOURCE or
                    not isinstance(updated, datetime) or updated.tzinfo is None or
                    updated >= now - timedelta(days=1)):
                continue
        wanted[key] = ref
    return wanted


def unique_japanese_sets(data: dict) -> dict[str, dict]:
    if data.get("success") is not True or not isinstance(data.get("data"), list):
        raise ProviderResponseError("SETS_SCHEMA")
    groups = defaultdict(list)
    for row in data["data"]:
        if not isinstance(row, dict) or row.get("language") != "jap":
            continue
        code, number = str(row.get("set_code") or ""), str(row.get("set_id") or "")
        if SET_CODE.fullmatch(code) and NUMERIC_SET_ID.fullmatch(number):
            groups[code.casefold()].append(row)
    return {code: rows[0] for code, rows in groups.items() if len(rows) == 1}


def complete_search_page(payload: dict, code: str, page: int):
    pagination = payload.get("pagination")
    cards = payload.get("results")
    if (not isinstance(pagination, dict) or not isinstance(cards, list)
            or str(payload.get("query") or "").casefold() != code):
        raise ProviderResponseError("SEARCH_SCHEMA")
    total, pages = pagination.get("total"), pagination.get("total_pages")
    if (type(total) is not int or type(pages) is not int
            or type(pagination.get("page")) is not int
            or pagination["page"] != page or not 0 <= total <= 100_000
            or pages != ceil(total / PAGE_SIZE)
            or (isinstance(payload.get("metadata"), dict)
                and payload["metadata"].get("truncated") is True)
            or len(cards) != min(PAGE_SIZE, max(0, total - (page-1)*PAGE_SIZE))
            or any(not isinstance(item, dict) for item in cards)):
        raise ProviderResponseError("INCOMPLETE_SEARCH")
    return total, pages, cards


def matching_printings(wanted: dict, code: str, set_id: str, cards: list[dict], diagnostics=None):
    """No uniqueness decision may depend on prices or row order."""
    by_number = defaultdict(list)
    shape = Counter()
    for item in cards:
        if not isinstance(item, dict):
            continue
        shape["rows"] += 1
        if not SOURCE_ID.fullmatch(str(item.get("id") or "")):
            continue
        shape["valid_ids"] += 1
        info = item.get("card_info")
        if not isinstance(info, dict):
            continue
        shape["card_info"] += 1
        if info.get("product_type") != "card":
            continue
        shape["card_type"] += 1
        if str(info.get("set_id") or "") != set_id:
            continue
        shape["set_id"] += 1
        if str(info.get("set_code") or "").casefold() not in {code, set_id}:
            continue
        shape["set_code"] += 1
        if str(info.get("card_number") or "").strip().isdigit():
            shape["numeric_only_number"] += 1
        fraction = collector_fraction(info.get("card_number"))
        if fraction:
            shape["full_collector_fraction"] += 1
            by_number[fraction].append(item)
    results = []
    ambiguous = 0
    for (ref_code, number), ref in wanted.items():
        if ref_code != code:
            continue
        candidates = by_number.get(number, [])
        if len(candidates) > 1:
            ambiguous += 1
        if len(candidates) == 1:
            results.append((ref, candidates[0]))
    if diagnostics is not None:
        diagnostics.update(source_number_count=len(by_number),
            duplicate_printing_numbers=ambiguous, unique_matched=len(results),
            source_shape=dict(shape))
    return results


def guide_quote(ref: dict, item: dict, set_id: str, fx, observed: datetime, diagnostics=None):
    """Return the existing trend guide, with bounded shape-only diagnostics.

    Rejection information contains fixed labels/counts and positive-field
    flags, never raw provider records, URLs, amounts, or exception messages.
    Other source fields are observed for diagnosis only, not accepted prices.
    """
    shape = {"price_rows": 0, "normal_rows": 0, "holo_rows": 0,
             "unsupported_variant_rows": 0, "invalid_price_rows": 0,
             "positive_trend_rows": 0, "positive_avg30_rows": 0}

    def reject(reason):
        if diagnostics is not None:
            diagnostics.update(reason=reason, source_shape=shape)
        return None

    market = item.get("cardmarket")
    if not isinstance(market, dict):
        return reject("CARDMARKET_ABSENT")
    if not isinstance(market.get("prices"), list):
        return reject("PRICE_ARRAY_INVALID")
    shape["price_rows"] = len(market["prices"])
    if not market["prices"]:
        return reject("PRICE_ARRAY_EMPTY")
    url = urlsplit(str(market.get("product_url") or ""))
    if (url.scheme != "https" or url.hostname not in {"cardmarket.com", "www.cardmarket.com"}
            or not url.path.casefold().startswith(("/en/pokemon/products/singles/",
                                                  "/it/pokemon/products/singles/",
                                                  "/de/pokemon/products/singles/",
                                                  "/fr/pokemon/products/singles/",
                                                  "/es/pokemon/products/singles/"))
            or url.query or url.fragment):
        return reject("SINGLE_PRODUCT_URL_INVALID")
    quotes = defaultdict(list)
    for row in market["prices"]:
        if not isinstance(row, dict):
            shape["invalid_price_rows"] += 1
            continue
        variant = row.get("variant_type")
        if not isinstance(variant, str) or variant not in {"normal", "holo"}:
            shape["unsupported_variant_rows"] += 1
            continue
        shape[variant + "_rows"] += 1
        try:
            _minor(row.get("avg30"))
            shape["positive_avg30_rows"] += 1
        except (ValueError, TypeError, ArithmeticError):
            pass
        try:
            raw = _minor(row.get("trend"))
        except (ValueError, TypeError, ArithmeticError):
            shape["invalid_price_rows"] += 1
            continue
        shape["positive_trend_rows"] += 1
        quotes[row["variant_type"]].append((raw, row))
    if not quotes:
        return reject("POSITIVE_SUPPORTED_TREND_ABSENT")
    if any(len(rows) != 1 for rows in quotes.values()):
        return reject("DUPLICATE_FINISH_QUOTES")
    # Normal, if explicitly present, is the catalogue baseline. When the
    # sole available guide is Holo, its finish is disclosed in provenance.
    variant = "normal" if "normal" in quotes else "holo"
    original, source_row = quotes[variant][0]
    amount = int((Decimal(original) * fx.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount <= 0:
        return reject("NONPOSITIVE_CONVERSION")
    if diagnostics is not None:
        diagnostics.update(reason="ACCEPTED", source_shape=shape)
    # The provider refreshes prices daily but updated_at records the last price
    # change, not the last check. Preserve it literally, separately from this
    # successful source observation; failed requests never create that observation.
    # https://pokewallet.io/blog/tcg-price-api-12-card-games-one-key
    return {"source": SOURCE, "aggregator": "POKEWALLET", "market": "CARDMARKET",
        "source_card_id": item["id"], "source_set_id": set_id,
        "source_product_url": market["product_url"], "source_field": "trend",
        "finish": variant, "original_currency": "EUR", "original_minor": original,
        "price_gbp_minor": amount, "observed_at": observed.isoformat(),
        "provider_updated_at": source_row.get("updated_at"),
        "valuation_role": "MIXED_NON_ENGLISH_REFERENCE", "reference_language": "Japanese",
        "condition_specific": False, "sold_comparable": False,
        "physical_language_confirmed": False, "physical_valuation_eligible": False,
        "match_basis": "EXACT_JAPANESE_SET_AND_UNIQUE_COMPLETE_COLLECTOR_FRACTION",
        "reference_printing_id": ref["provider_id"],
        "reference_identity": {key: ref[key] for key in ("name", "set_id", "card_number", "set_name")},
        "fx_rate_to_gbp": str(fx.rate), "fx_source": fx.source,
        "fx_effective_at": fx.effective_at.isoformat(),
        "fx_retrieved_at": fx.retrieved_at.isoformat()}


class FreePokewalletPokemonClient:
    def __init__(self, api_key: str, *, request_limit: int, client):
        if not api_key or not api_key.startswith("pk_live_"):
            raise ProviderResponseError("API_KEY_NOT_LIVE")
        self.api_key, self.limit, self.http = api_key, request_limit, client
        self.requests = 0

    async def get(self, path: str, params=None):
        if self.requests >= self.limit:
            raise ProviderResponseError("REQUEST_BUDGET_EXHAUSTED")
        if path not in {"/sets", "/search"}:
            raise ProviderResponseError("PAID_OR_UNKNOWN_ENDPOINT")
        self.requests += 1
        response = await self.http.get(BASE_URL+path, params=params,
            headers={"X-API-Key": self.api_key, "Accept": "application/json"})
        if response.status_code == 429:
            raise ProviderResponseError("RATE_LIMITED")
        if response.status_code >= 400:
            raise ProviderResponseError("UPSTREAM_HTTP_"+str(response.status_code))
        for name in ("X-RateLimit-Remaining-Hour", "X-RateLimit-Remaining-Day"):
            remaining = response.headers.get(name)
            if remaining is not None and remaining.isdigit() and int(remaining) < 5:
                raise ProviderResponseError("PROVIDER_BUDGET_LOW")
        if len(response.content) > 4_000_000:
            raise ProviderResponseError("RESPONSE_TOO_LARGE")
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderResponseError("INVALID_JSON") from exc
        if not isinstance(body, dict):
            raise ProviderResponseError("INVALID_SCHEMA")
        return body


async def refresh_pokewallet_pokemon(pool, actor, fx, api_key: str, *,
                                    dry_run=True, request_limit=MAX_REQUESTS_PER_HOUR,
                                    previous_cursor=None, http_client=None):
    """Bounded, round-robin Japanese checklist import. Dry run by default."""
    now = datetime.now(timezone.utc)
    budget = min(max(1, request_limit), MAX_REQUESTS_PER_HOUR)
    result = {"source": SOURCE, "dry_run": dry_run, "requests": 0,
        "checked_references": 0, "eligible_references": 0,
        "target_sets": 0, "matched_printings": 0, "eligible_quotes": 0,
        "writes_attempted": 0, "set_pages": 0, "source_sets": 0,
        "input_cursor": previous_cursor, "cursor": previous_cursor,
        "sampled_sets": [], "skipped_invalid_sets": 0, "provider_failures": 0,
        "quote_rejections": {}, "quote_rejection_samples": []}
    owns_client = http_client is None
    if owns_client:
        http_client = httpx.AsyncClient(timeout=18, follow_redirects=False)
    client = FreePokewalletPokemonClient(api_key, request_limit=budget, client=http_client)
    try:
        async with user_connection(pool, actor, str(uuid4())) as connection:
            refs = [dict(row) for row in await connection.fetch(READ_SQL)]
        result["checked_references"] = len(refs)
        wanted = reference_groups(refs, now)
        result["eligible_references"] = len(wanted)
        if not wanted:
            return result
        listings = await client.get("/sets")
        available = unique_japanese_sets(listings)
        result["source_sets"] = len(available)
        counts = Counter(code for code, _ in wanted)
        targets = [(code, str(row["set_id"])) for code, row in available.items() if code in counts]
        targets.sort(key=lambda pair: (-counts[pair[0]], pair[0], pair[1]))
        result["target_sets"] = len(targets)
        if previous_cursor:
            index = next((i + 1 for i, pair in enumerate(targets) if pair[1] == previous_cursor), 0)
            targets = targets[index:] + targets[:index]
        conversion = None
        for code, set_id in targets:
            if client.requests >= budget:
                break
            cards = []
            total = 0
            try:
                first = await client.get("/search", {"q": code, "page": 1, "limit": PAGE_SIZE})
                total, pages, batch = complete_search_page(first, code, 1)
                if pages > budget-client.requests+1:
                    result["deferred_large_sets"] = result.get("deferred_large_sets", 0)+1
                    result["cursor"] = set_id
                    continue
                cards.extend(batch)
                result["set_pages"] += 1
                for page in range(2, pages+1):
                    more = await client.get("/search", {"q": code, "page": page, "limit": PAGE_SIZE})
                    expected, expected_pages, batch = complete_search_page(more, code, page)
                    if expected != total or expected_pages != pages:
                        raise ProviderResponseError("PAGE_IDENTITY_CHANGED")
                    cards.extend(batch)
                    result["set_pages"] += 1
                if len(cards) != total or len({str(p.get("id")) for p in cards if isinstance(p, dict)}) != total:
                    raise ProviderResponseError("INCOMPLETE_SEARCH")
                # A set-code query must cover *all* printings in that exact
                # provider set. Otherwise a variant on another page or an
                # incomplete search could be misread as a unique printing.
                exact_cards = [p for p in cards if isinstance(p.get("card_info"),dict)
                               and p["card_info"].get("product_type") == "card"
                               and str(p["card_info"].get("set_id") or "") == set_id]
                expected_cards = available[code].get("card_count")
                if (type(expected_cards) is not int or expected_cards < 0
                        or len(exact_cards) != expected_cards):
                    raise ProviderResponseError("SET_SEARCH_INCOMPLETE")
            except ProviderResponseError as exc:
                if str(exc) not in {"SEARCH_SCHEMA", "INCOMPLETE_SEARCH",
                                    "PAGE_IDENTITY_CHANGED", "SET_SEARCH_INCOMPLETE"}:
                    raise
                result["skipped_invalid_sets"] += 1
                result["cursor"] = set_id
                continue
            diagnostics = {"code": code, "set_id": set_id, "cards": len(exact_cards),
                           "search_results": len(cards)}
            matches = matching_printings(wanted, code, set_id, exact_cards, diagnostics)
            result["matched_printings"] += len(matches)
            if len(result["sampled_sets"]) < 8:
                result["sampled_sets"].append(diagnostics)
            if matches and conversion is None:
                conversion = await fx.quote(base_currency="EUR", quote_currency="GBP", at=now)
            values = []
            for ref, item in matches:
                quote_diagnostics = {}
                quote = guide_quote(ref, item, set_id, conversion, now, quote_diagnostics)
                if quote is None:
                    reason = quote_diagnostics["reason"]
                    result["quote_rejections"][reason] = result["quote_rejections"].get(reason, 0) + 1
                    if len(result["quote_rejection_samples"]) < 5:
                        result["quote_rejection_samples"].append({
                            "reference_id": ref["provider_id"], "set_code": code,
                            **quote_diagnostics})
                    continue
                result["eligible_quotes"] += 1
                values.append((ref["provider"], ref["system_code"], ref["language"],
                    ref["provider_id"], json.dumps([quote]), quote["price_gbp_minor"],
                    quote["price_gbp_minor"], now, now, now+timedelta(days=1),
                    ref["name"], ref["set_id"], ref["card_number"], ref["set_name"],
                    ref.get("rarity"), SOURCE))
            if values and not dry_run:
                for index in range(0, len(values), 100):
                    async with user_connection(pool, actor, str(uuid4())) as connection:
                        await connection.executemany(WRITE_SQL, values[index:index+100])
                result["writes_attempted"] += len(values)
            result["cursor"] = set_id
    except (httpx.HTTPError, ProviderResponseError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        result["provider_failures"] += 1
        result["reason"] = str(exc) if isinstance(exc, ProviderResponseError) else type(exc).__name__
    finally:
        result["requests"] = client.requests
        if owns_client:
            await http_client.aclose()
    log.warning("Pokewallet Pokemon JP free guide dry_run=%s requests=%s quotes=%s writes=%s reason=%s",
                dry_run, result["requests"], result["eligible_quotes"],
                result["writes_attempted"], result.get("reason", "none"))
    return result
