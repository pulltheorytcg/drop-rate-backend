"""Conservative free-tier PokéWallet/One Piece catalogue guides.

PokéWallet's *free* ``/op/sets`` routes contain per-printing Cardmarket
guides. Its paid ``/op/prices`` route is deliberately never called. These
are indicative EUR marketplace guides, not UK sold comparables or a licence
to reprice physical inventory. The separate catalogue-guide table is used.

Only a release-unique, number-unique **base** printing can be matched. An
alternate art/parallel requires its own independent printing evidence; the
first, cheapest or sole *priced* item is never used as a tie-breaker.
"""
from __future__ import annotations

import html
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .db import user_connection
from .one_piece_market import normalized, release_identity
from .reference_market import _minor

log = logging.getLogger(__name__)
SOURCE = "POKEWALLET_CARDMARKET_CATALOGUE"
SYSTEM = "ONE_PIECE_CARD_GAME"
BASE_URL = "https://api.pokewallet.io"
MAX_FREE_REQUESTS_PER_RUN = 60  # 100/hour, 1,000/day across all PokéWallet games
PAGE_SIZE = 200
BASE_NUMBER = re.compile(r"(?:OP|EB|PRB|ST)\d{2}-\d{3}")
SET_MARKER = re.compile(r"\[((?:OP|EB|PRB|ST)-?\d{2})(?:-?EB\d{2})?\]$")
JP_MARKER = re.compile(r"【((?:OP|EB|PRB|ST)-?\d{2})】$")
JP_SET_PREFIXES = ("ブースターパック ", "エクストラブースター ",
                   "プレミアムブースター ", "スタートデッキ ", "アルティメットデッキ ")
RARITIES = {
    "c": "common", "uc": "uncommon", "r": "rare", "sr": "superrare",
    "sec": "secretrare", "l": "leader", "sp": "special",
}

READ_SQL = """select r.provider,r.system_code,r.language,r.provider_id,r.name,r.set_id,
 r.card_number,r.rarity,s.name as set_name,
 coalesce(p.market_value_minor,0)>0 as has_detail_value,
 coalesce(b.market_value_minor,0) as existing_catalogue_value,
 b.quotes->0->>'source' as existing_source,
 b.pricing_updated_at as existing_pricing_updated_at
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 where r.system_code='ONE_PIECE_CARD_GAME' and r.language in ('English','Japanese')
 and r.provider in ('Bandai Official','Punk Records')
 and (s.release_date is null or s.release_date<=current_date)"""

# A stored positive guide from another provider cannot be replaced, even if
# stale. Our own older guide can be refreshed. Reference identity, including
# the literal publisher's Japanese name, must still match at write time.
WRITE_SQL = """insert into tcg.reference_catalogue_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,
 market_value_high_minor,pricing_updated_at,checked_at,expires_at)
 select $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4
 and r.name=$11 and r.set_id=$12 and r.card_number=$13 and s.name=$14
 and r.rarity is not distinct from $15
 on conflict(provider,system_code,language,provider_id) do update set
 quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
 market_value_high_minor=excluded.market_value_high_minor,
 pricing_updated_at=excluded.pricing_updated_at,
 checked_at=excluded.checked_at,expires_at=excluded.expires_at
 where (coalesce(tcg.reference_catalogue_prices.market_value_minor,0)<=0
   or (tcg.reference_catalogue_prices.quotes->0->>'source'=$16
       and tcg.reference_catalogue_prices.checked_at<excluded.checked_at))"""


class ProviderResponseError(ValueError):
    """A source response is invalid or over quota; existing prices survive."""


def code_from_reference(ref: dict) -> str | None:
    if (ref.get("system_code") != SYSTEM or
            ref.get("provider") not in {"Punk Records", "Bandai Official"} or
            ref.get("language") not in {"English", "Japanese"}):
        return None
    number = str(ref.get("card_number") or "")
    if (ref.get("provider_id") != number or not BASE_NUMBER.fullmatch(number)):
        return None  # no extrapolation to parallel art suffixes
    name = str(ref.get("set_name") or "")
    if ref["language"] == "Japanese":
        if ref["provider"] != "Punk Records" or not name.startswith(JP_SET_PREFIXES):
            return None
        marker = JP_MARKER.search(name)
    else:
        # The full Bandai/Punk release identity must be recognised; the
        # bracketed OP/ST code alone is not proof for an arbitrary promo.
        if (not re.match(r"^(?:BOOSTER PACK|EXTRA BOOSTER|PREMIUM BOOSTER|STARTER DECK|ULTRA DECK)\b",name,re.I)
                or release_identity(name) is None):
            return None
        marker = SET_MARKER.search(name)
    if marker is None:
        return None
    code = marker[1].replace("-", "").upper()
    return code if number.startswith(code + "-") else None


def rarity(value: object) -> str:
    label = normalized(str(value or ""))
    return RARITIES.get(label, label)


def quote_eligible(ref: dict, now: datetime) -> bool:
    if ref.get("has_detail_value"):
        return False
    existing = int(ref.get("existing_catalogue_value") or 0)
    if existing <= 0:
        return True
    if ref.get("existing_source") != SOURCE:
        return False
    updated = ref.get("existing_pricing_updated_at")
    return isinstance(updated, datetime) and updated < now - timedelta(days=1)


def collect_reference_groups(refs: list[dict], now: datetime):
    """Return every base reference, including priced rows for collision checks."""
    by_number = defaultdict(list)
    wanted = defaultdict(list)
    for ref in refs:
        code = code_from_reference(ref)
        if code:
            key = (ref["language"], code, ref["card_number"])
            by_number[key].append(ref)
            if quote_eligible(ref, now):
                wanted[key].append(ref)
    # Multiple reference sets with one release code, or conflicting reference
    # rarities, must never create an apparent unique market product.
    valid = {}
    for key, rows in by_number.items():
        if (len({(r["provider"],r["provider_id"],r["set_id"]) for r in rows}) != len(rows)
                or len({rarity(r.get("rarity")) for r in rows}) != 1
                or (key[0] == "English" and
                    (len({normalized(html.unescape(r["name"])) for r in rows}) != 1
                     or len({normalized(r["set_name"]) for r in rows}) != 1))):
            continue
        if key in wanted and rarity(rows[0].get("rarity")):
            valid[key] = wanted[key]
    return valid


def unique_source_sets(payloads: dict[str, dict]) -> dict[tuple[str, str], dict]:
    groups = defaultdict(list)
    for lang, body in payloads.items():
        if body.get("success") is not True or not isinstance(body.get("data"), list):
            raise ProviderResponseError("SETS_SCHEMA")
        for record in body["data"]:
            if not isinstance(record, dict) or record.get("language") not in ({"en"} if lang=="English" else {"jp"}):
                continue
            code = str(record.get("set_code") or "").replace("-", "").upper()
            group_id = str(record.get("group_id") or "")
            if re.fullmatch(r"(?:OP|EB|PRB|ST)\d{2}",code) and re.fullmatch(r"-?\d+",group_id):
                groups[(lang,code)].append(record)
    return {key:rows[0] for key,rows in groups.items() if len(rows)==1}


def unique_market_products(body: dict, lang: str, group_id: str, code: str):
    """Reject incomplete sets; variants may be on a later page."""
    meta = body.get("set")
    if (body.get("success") is not True or not isinstance(meta, dict)
            or str(meta.get("group_id")) != group_id
            or str(meta.get("set_code") or "").replace("-", "").upper() != code
            or meta.get("language") != ("jp" if lang=="Japanese" else "en")):
        raise ProviderResponseError("SET_IDENTITY_SCHEMA")
    total = body.get("total")
    page = body.get("page")
    items = body.get("data")
    if (type(total) is not int or total < 0 or total > 10000
            or type(page) is not int or page < 1 or not isinstance(items,list)):
        raise ProviderResponseError("SET_PAGINATION_SCHEMA")
    return total,items


def matches_for_complete_set(refs_by_number: dict, lang: str, code: str, products: list[dict]):
    by_number = defaultdict(list)
    for item in products:
        if not isinstance(item,dict):
            continue
        number = str(item.get("card_number") or "")
        if number.startswith(code + "-") and BASE_NUMBER.fullmatch(number):
            by_number[number].append(item)
    matches=[]
    for (ref_lang, ref_code, number), refs in refs_by_number.items():
        if (ref_lang, ref_code) != (lang,code):
            continue
        candidates = by_number.get(number,())
        if len(candidates) != 1:  # one quoted art never resolves a parallel collision
            continue
        product=candidates[0]
        if (not str(product.get("id") or "").startswith("op_")
                or rarity(product.get("rarity")) != rarity(refs[0].get("rarity"))
                or str(product.get("sub_type_name") or "Normal").casefold() not in
                   {"normal", "foil", "holofoil"}):
            continue
        if lang == "English" and normalized(html.unescape(product.get("name") or "")) != normalized(html.unescape(refs[0]["name"])):
            continue
        matches.extend((ref,product) for ref in refs)
    return matches


def catalogue_guide(ref: dict, product: dict, group_id: str, fx, observed: datetime):
    market=product.get("cardmarket")
    if not isinstance(market,dict) or not isinstance(market.get("prices"),dict):
        return None
    uri=str(market.get("product_url") or "")
    parsed=urlsplit(uri)
    if (parsed.scheme!="https" or parsed.hostname not in {"www.cardmarket.com","cardmarket.com"}
            or "/onepiece/" not in parsed.path.casefold()):
        return None
    try:
        original=_minor(market["prices"].get("trend"))
        gbp=int((Decimal(original)*fx.rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    except (TypeError,ValueError,ArithmeticError,KeyError):
        return None
    if gbp<=0:
        return None
    quote={
        "source":SOURCE,"market":"CARDMARKET","aggregator":"POKEWALLET",
        "source_card_id":product["id"],"source_set_group_id":group_id,
        "source_product_url":uri,"source_field":"trend",
        "original_currency":"EUR","original_minor":original,"price_gbp_minor":gbp,
        "observed_at":observed.isoformat(),"finish":"Indicative marketplace guide",
        "valuation_role":"MIXED_NON_ENGLISH_REFERENCE" if ref["language"]=="Japanese" else "MIXED_LANGUAGE_REFERENCE",
        "physical_valuation_eligible":False,"physical_language_confirmed":False,
        "condition_specific":False,"sold_comparable":False,
        "match_basis":"EXACT_RELEASE_NUMBER_RARITY_UNIQUE_POKEWALLET_BASE_PRINTING",
        "reference_printing_id":ref["provider_id"],"reference_rarity":ref.get("rarity"),
        "reference_language":ref["language"],
        "reference_identity":{field:ref[field] for field in ("name","set_id","card_number","set_name")},
        "fx_rate_to_gbp":str(fx.rate),"fx_source":fx.source,
        "fx_effective_at":fx.effective_at.isoformat(),
        "fx_retrieved_at":fx.retrieved_at.isoformat(),
    }
    return quote


class FreePokewalletOnePieceClient:
    def __init__(self, api_key: str, *, request_limit: int, client=None):
        if not api_key or not api_key.startswith("pk_live_"):
            raise ProviderResponseError("API_KEY_NOT_LIVE")
        self.api_key=api_key
        self.limit=request_limit
        self.requests=0
        self._client=client

    async def get(self, path: str, params: dict | None=None) -> dict:
        if self.requests>=self.limit:
            raise ProviderResponseError("REQUEST_BUDGET_EXHAUSTED")
        if not (path=="/op/sets" or re.fullmatch(r"/op/sets/-?\d+",path)):
            raise ProviderResponseError("PAID_OR_UNRECOGNISED_ENDPOINT")
        self.requests+=1
        response=await self._client.get(BASE_URL+path,params=params,
            headers={"X-API-Key":self.api_key,"Accept":"application/json"})
        if response.status_code==429:
            raise ProviderResponseError("RATE_LIMITED")
        if response.status_code>=400:
            raise ProviderResponseError("UPSTREAM_HTTP_"+str(response.status_code))
        # Stop while a safety margin remains for other legitimate API users.
        for name in ("X-RateLimit-Remaining-Hour","X-RateLimit-Remaining-Day"):
            remainder=response.headers.get(name)
            if remainder is not None and remainder.isdigit() and int(remainder)<5:
                raise ProviderResponseError("PROVIDER_BUDGET_LOW")
        if len(response.content)>4_000_000:
            raise ProviderResponseError("RESPONSE_TOO_LARGE")
        try:
            data=response.json()
        except ValueError as exc:
            raise ProviderResponseError("INVALID_JSON") from exc
        if not isinstance(data,dict):
            raise ProviderResponseError("INVALID_SCHEMA")
        return data


async def refresh_pokewallet_one_piece(pool, actor, fx, api_key: str, *,
                                       dry_run: bool=True, request_limit: int=MAX_FREE_REQUESTS_PER_RUN,
                                       previous_cursor: str | None=None,
                                       http_client=None) -> dict:
    """One bounded free API pass, with dry-run by default and a round-robin cursor.

    The caller holds the existing global catalogue advisory lock and records
    the daily receipt. Nothing touches inventory, Store Price or Shopify.
    """
    now=datetime.now(timezone.utc)
    budget=min(request_limit,12 if dry_run else MAX_FREE_REQUESTS_PER_RUN)
    result={"source":SOURCE,"dry_run":dry_run,"requests":0,"set_pages":0,
            "checked_references":0,"matching_printings":0,"eligible_quotes":0,
            "writes_attempted":0,"provider_failures":0,"cursor":previous_cursor}
    client=FreePokewalletOnePieceClient(api_key,request_limit=budget)
    try:
        async with user_connection(pool,actor,str(uuid4())) as connection:
            refs=[dict(r) for r in await connection.fetch(READ_SQL)]
        result["checked_references"]=len(refs)
        groups=collect_reference_groups(refs,now)
        if not groups:
            return result
        if http_client is None:
            http_client=httpx.AsyncClient(timeout=18,follow_redirects=False)
            owns_client=True
        else:
            owns_client=False
        try:
            client._client=http_client
            lists={}
            for lang in ("Japanese","English"):
                lists[lang]=await client.get("/op/sets",{"language":"jp" if lang=="Japanese" else "en"})
            sources=unique_source_sets(lists)
            targets=sorted(((lang,code,str(item["group_id"])) for (lang,code),item in sources.items()
                            if any(key[:2]==(lang,code) for key in groups)),
                           key=lambda row:(row[0]!="Japanese",row[1],row[2]))
            if previous_cursor:
                index=next((i+1 for i,x in enumerate(targets) if f"{x[0]}:{x[2]}"==previous_cursor),0)
                targets=targets[index:]+targets[:index]
            converted=None
            for lang,code,group_id in targets:
                if client.requests>=budget:
                    break
                first=await client.get(f"/op/sets/{group_id}",{"page":1,"limit":PAGE_SIZE})
                total,items=unique_market_products(first,lang,group_id,code)
                pages=ceil(total/PAGE_SIZE)
                if pages>budget-client.requests+1:
                    # No prices based on the incomplete first page: later pages
                    # may contain competing alternate arts.
                    result["deferred_large_sets"]=result.get("deferred_large_sets",0)+1
                    continue
                result["set_pages"]+=1
                complete=list(items)
                for page in range(2,pages+1):
                    body=await client.get(f"/op/sets/{group_id}",{"page":page,"limit":PAGE_SIZE})
                    expected,new_items=unique_market_products(body,lang,group_id,code)
                    if expected!=total or body.get("page")!=page:
                        raise ProviderResponseError("PAGE_IDENTITY_CHANGED")
                    complete.extend(new_items)
                    result["set_pages"]+=1
                if len(complete)!=total or len({str(p.get("id")) for p in complete})!=total:
                    raise ProviderResponseError("INCOMPLETE_OR_DUPLICATE_SET")
                matches=matches_for_complete_set(groups,lang,code,complete)
                result["matching_printings"]+=len(matches)
                if matches:
                    if converted is None:
                        converted=await fx.quote(base_currency="EUR",quote_currency="GBP",at=now)
                    values=[]
                    for ref,product in matches:
                        quote=catalogue_guide(ref,product,group_id,converted,now)
                        if quote is None:
                            continue
                        result["eligible_quotes"]+=1
                        values.append((ref["provider"],ref["system_code"],ref["language"],
                            ref["provider_id"],[quote],quote["price_gbp_minor"],quote["price_gbp_minor"],
                            now,now,now+timedelta(days=1),ref["name"],ref["set_id"],
                            ref["card_number"],ref["set_name"],ref.get("rarity"),SOURCE))
                    if values and not dry_run:
                        for start in range(0,len(values),100):
                            async with user_connection(pool,actor,str(uuid4())) as connection:
                                await connection.executemany(WRITE_SQL,values[start:start+100])
                        result["writes_attempted"]+=len(values)
                result["cursor"]=f"{lang}:{group_id}"
        finally:
            if owns_client:
                await http_client.aclose()
    except (httpx.HTTPError,ProviderResponseError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        result["provider_failures"]+=1
        result["reason"]=str(exc) if isinstance(exc,ProviderResponseError) else type(exc).__name__
        # Already committed pages survive safely; no replacement of other
        # providers, and the next UK-day pass resumes after the last set.
    finally:
        result["requests"]=client.requests
    log.warning("Pokewallet One Piece free catalogue dry_run=%s requests=%s candidates=%s writes=%s failures=%s reason=%s",
                dry_run,result["requests"],result["eligible_quotes"],result["writes_attempted"],
                result["provider_failures"],result.get("reason","none"))
    return result
