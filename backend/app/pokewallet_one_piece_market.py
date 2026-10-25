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
JP_CARDMARKET_NAME = re.compile(
    r"^.+\(((?:OP|EB|PRB|ST)\d{2}-\d{3})\)(?:\s*\(V\.\s*([1-9]\d*)\))?$",
    re.I,
)
SET_MARKER = re.compile(r"\[((?:OP|EB|PRB|ST)-?\d{2})(?:-?EB\d{2})?\]$")
JP_MARKER = re.compile(r"【((?:OP|EB|PRB|ST)-?\d{2})】$")
JP_SET_PREFIXES = ("ブースターパック ", "エクストラブースター ",
                   "プレミアムブースター ", "スタートデッキ ", "アルティメットデッキ ")
RARITIES = {
    "c": "common", "uc": "uncommon", "r": "rare", "sr": "superrare",
    "sec": "secretrare", "l": "leader", "sp": "special",
}
ALTERNATE_PRINT_LABELS = {
    "alternate art", "alt art", "parallel", "special", "sp", "manga",
    "super parallel", "foil", "holofoil", "textured",
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


def source_release_code(value: object, language: str) -> str | None:
    """Treat the provider's `-JP` locale suffix as metadata, not a card set.

    A Japanese entry must *also* be returned by the explicit JP-language API
    filter and carry JP language metadata; an English entry cannot claim it.
    """
    literal=str(value or "").strip().upper()
    match=re.fullmatch(r"((?:OP|EB|PRB|ST)-?\d{2})(-JP)?",literal)
    if match is None or (language=="English" and match[2]):
        return None
    return match[1].replace("-","")


def unique_source_sets(payloads: dict[str, dict]) -> dict[tuple[str, str], dict]:
    groups = defaultdict(list)
    for lang, body in payloads.items():
        if body.get("success") is not True or not isinstance(body.get("data"), list):
            raise ProviderResponseError("SETS_SCHEMA")
        for record in body["data"]:
            if not isinstance(record, dict) or record.get("language") not in ({"en"} if lang=="English" else {"jp"}):
                continue
            code = source_release_code(record.get("set_code"),lang)
            group_id = str(record.get("group_id") or "")
            if code and re.fullmatch(r"-?\d+",group_id):
                groups[(lang,code)].append(record)
    return {key:rows[0] for key,rows in groups.items() if len(rows)==1}


def source_list_diagnostics(payloads: dict[str,dict], refs_by_number: dict) -> dict:
    """Count release-identity conflicts without guessing which entry is right."""
    summary={}
    for lang, body in payloads.items():
        names=defaultdict(set)
        rows=body.get("data",[])
        for row in rows:
            if not isinstance(row,dict) or row.get("language") != ("jp" if lang=="Japanese" else "en"):
                continue
            code=source_release_code(row.get("set_code"),lang)
            if code:
                names[code].add(str(row.get("group_id")))
        wanted={key[1] for key in refs_by_number if key[0]==lang}
        ambiguous={code for code in wanted if len(names.get(code,()))>1}
        summary[lang]={"raw_records":len(rows),"valid_release_codes":len(names),
            "wanted_release_codes":len(wanted),"unmatched_release_codes":sum(code not in names for code in wanted),
            "multiple_group_ids":len(ambiguous),"ambiguous_code_sample":sorted(ambiguous)[:10]}
    return summary


def unique_market_products(body: dict, lang: str, group_id: str, code: str):
    """Reject incomplete sets; variants may be on a later page."""
    meta = body.get("set")
    if (body.get("success") is not True or not isinstance(meta, dict)
            or str(meta.get("group_id")) != group_id
            or source_release_code(meta.get("set_code"),lang) != code
            or meta.get("language") != ("jp" if lang=="Japanese" else "en")):
        raise ProviderResponseError("SET_IDENTITY_SCHEMA")
    total = body.get("total")
    page = body.get("page")
    items = body.get("data")
    if (type(total) is not int or total < 0 or total > 10000
            or type(page) is not int or page < 1 or not isinstance(items,list)):
        raise ProviderResponseError("SET_PAGINATION_SCHEMA")
    return total,items


def japanese_cardmarket_printing(product: dict, release: str) -> tuple[str, int | None] | None:
    """Recover a *printed* ID independently from Cardmarket's name and URL.

    PokéWallet's Japanese CM-only rows sometimes contain ordinal values such
    as ``1.0`` in ``card_number``. An ordinal is never an identity. Both the
    Cardmarket listing title and canonical product URL must explicitly print
    the same Bandai card number, in a Japanese release, with the same variant.
    """
    market = product.get("cardmarket")
    if not isinstance(market, dict):
        return None
    title = html.unescape(str(market.get("product_name") or "")).strip()
    name = JP_CARDMARKET_NAME.fullmatch(title)
    if name is None:
        return None
    number, title_version = name[1].upper(), name[2]
    if not number.startswith(release + "-"):
        return None
    parsed = urlsplit(str(market.get("product_url") or ""))
    parts = parsed.path.split("/")
    if (parsed.scheme != "https" or parsed.hostname not in {"cardmarket.com", "www.cardmarket.com"}
            or parsed.query or parsed.fragment or len(parts) != 7
            or parts[1].casefold() not in {"en", "it", "fr", "de", "es", "pt"}
            or [p.casefold() for p in parts[2:5]] != ["onepiece", "products", "singles"]
            or not parts[5].casefold().endswith("-japanese")):
        return None
    slug = parts[6]
    path_match = re.fullmatch(r".+-" + re.escape(number) + r"(?:-V([1-9]\d*))?", slug, re.I)
    if path_match is None:
        return None
    path_version = path_match[1]
    if (title_version is None) != (path_version is None):
        return None
    if title_version is not None and int(title_version) != int(path_version):
        return None
    return number, int(title_version) if title_version is not None else None


def matches_for_complete_set(refs_by_number: dict, lang: str, code: str, products: list[dict], diagnostics=None):
    by_number = defaultdict(list)
    jp_printings = {}
    for item in products:
        if not isinstance(item,dict):
            continue
        number = str(item.get("card_number") or "")
        if number.startswith(code + "-") and BASE_NUMBER.fullmatch(number):
            by_number[number].append(item)
        elif lang == "Japanese":
            identity = japanese_cardmarket_printing(item, code)
            if identity is not None:
                jp_printings[id(item)] = identity
                by_number[identity[0]].append(item)
    matches=[]
    counts={key:0 for key in ("wanted_reference_numbers","source_number_overlap",
        "parallel_number_collisions","unique_number_candidates","valid_product_ids",
        "matching_rarities","matching_subtypes","matching_english_names")}
    for (ref_lang, ref_code, number), refs in refs_by_number.items():
        if (ref_lang, ref_code) != (lang,code):
            continue
        counts["wanted_reference_numbers"]+=1
        candidates = by_number.get(number,())
        if candidates:counts["source_number_overlap"]+=1
        if len(candidates)>1:counts["parallel_number_collisions"]+=1
        if len(candidates)>1:
            # A publisher base printing may coexist with clearly labelled
            # alternate artworks under the same printed card number. It is
            # safe ONLY when a single source item is explicitly Normal, and
            # every competitor has an explicit non-base printing label.
            normals=[p for p in candidates if str(p.get("sub_type_name") or "").strip().casefold()=="normal"]
            competitors=[p for p in candidates if p not in normals]
            if (len(normals)==1 and len(competitors)==len(candidates)-1 and
                    all(str(p.get("sub_type_name") or "").strip().casefold() in ALTERNATE_PRINT_LABELS
                        for p in competitors)):
                candidates=normals
                counts["base_art_disambiguated"]=counts.get("base_art_disambiguated",0)+1
            elif lang=="Japanese":
                # V.1 is the only labelled base. Never choose V.2+, a sole
                # quoted product, or an unversioned product among variants.
                versions=[jp_printings.get(id(p),(None,None))[1] for p in candidates]
                if versions.count(1)==1 and all(v is not None for v in versions):
                    candidates=[candidates[versions.index(1)]]
                    counts["japanese_v1_disambiguated"]=counts.get("japanese_v1_disambiguated",0)+1
        if len(candidates) != 1:
            continue
        counts["unique_number_candidates"]+=1
        product=candidates[0]
        if lang=="Japanese" and jp_printings.get(id(product),(None,None))[1] not in (None,1):
            continue
        if not str(product.get("id") or "").startswith("op_"):
            continue
        counts["valid_product_ids"]+=1
        source_rarity=rarity(product.get("rarity"))
        reference_rarity=rarity(refs[0].get("rarity"))
        if source_rarity != reference_rarity and not (
                lang=="Japanese" and not source_rarity and id(product) in jp_printings):
            continue
        counts["matching_rarities"]+=1
        if str(product.get("sub_type_name") or "Normal").casefold() not in {"normal", "foil", "holofoil"}:
            continue
        counts["matching_subtypes"]+=1
        if lang == "English" and normalized(html.unescape(product.get("name") or "")) != normalized(html.unescape(refs[0]["name"])):
            continue
        counts["matching_english_names"]+=1
        matches.extend((ref,product) for ref in refs)
    if diagnostics is not None:
        if lang=="Japanese":
            counts["japanese_cardmarket_ids_recovered"]=len(jp_printings)
        diagnostics.update(counts)
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
        "match_basis":("EXACT_JP_CARDMARKET_TITLE_URL_RELEASE_BASE_VARIANT"
                       if ref["language"]=="Japanese" else
                       "EXACT_RELEASE_NUMBER_RARITY_UNIQUE_POKEWALLET_BASE_PRINTING"),
        "source_rarity_confirmed":bool(rarity(product.get("rarity"))) and
            rarity(product.get("rarity"))==rarity(ref.get("rarity")),
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
            "checked_references":0,"wanted_base_printings":0,"source_groups":0,
            "target_groups":0,"targets_by_language":{},"source_list_diagnostics":{},
            "input_cursor":previous_cursor,"japanese_number_examples":[],
            "japanese_product_examples":[],
            "sampled_sets":[],"collapsed_identical_duplicate_rows":0,
            "skipped_invalid_sets":0,"invalid_set_samples":[],
            "matching_printings":0,"eligible_quotes":0,
            "writes_attempted":0,"provider_failures":0,"cursor":previous_cursor}
    client=FreePokewalletOnePieceClient(api_key,request_limit=budget)
    try:
        async with user_connection(pool,actor,str(uuid4())) as connection:
            refs=[dict(r) for r in await connection.fetch(READ_SQL)]
        result["checked_references"]=len(refs)
        groups=collect_reference_groups(refs,now)
        result["wanted_base_printings"]=sum(map(len,groups.values()))
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
            result["source_groups"]=len(sources)
            result["source_list_diagnostics"]=source_list_diagnostics(lists,groups)
            targets=sorted(((lang,code,str(item["group_id"])) for (lang,code),item in sources.items()
                            if any(key[:2]==(lang,code) for key in groups)),
                           key=lambda row:(row[0]!="Japanese",row[1],row[2]))
            result["target_groups"]=len(targets)
            result["targets_by_language"]={lang:sum(t[0]==lang for t in targets)
                                            for lang in ("Japanese","English")}
            if previous_cursor:
                index=next((i+1 for i,x in enumerate(targets) if f"{x[0]}:{x[2]}"==previous_cursor),0)
                targets=targets[index:]+targets[:index]
            converted=None
            for lang,code,group_id in targets:
                if client.requests>=budget:
                    break
                total=0
                complete=[]
                bad_set=None
                try:
                    first=await client.get(f"/op/sets/{group_id}",{"page":1,"limit":PAGE_SIZE})
                    total,items=unique_market_products(first,lang,group_id,code)
                    pages=ceil(total/PAGE_SIZE)
                    if pages>budget-client.requests+1:
                        # A partial set cannot prove that a base printing is
                        # unique; resume after it rather than getting stuck.
                        result["deferred_large_sets"]=result.get("deferred_large_sets",0)+1
                        result["cursor"]=f"{lang}:{group_id}"
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
                    if len(complete)!=total or not all(isinstance(p,dict) for p in complete):
                        raise ProviderResponseError("INCOMPLETE_OR_DUPLICATE_SET")
                    by_id={}
                    for item in complete:
                        source_id=str(item.get("id") or "")
                        if not source_id or (source_id in by_id and by_id[source_id]!=item):
                            # Repeated IDs with conflicting data might be two
                            # distinct market variants; never infer a price.
                            raise ProviderResponseError("INCOMPLETE_OR_DUPLICATE_SET")
                        by_id[source_id]=item
                    result["collapsed_identical_duplicate_rows"]+=len(complete)-len(by_id)
                    complete=list(by_id.values())
                except ProviderResponseError as exc:
                    # Invalid set pages are quarantined *in full*, then the
                    # daily cursor moves on to other legitimate releases.
                    # Rate limits and upstream outages stop the entire pass.
                    if str(exc) not in {"SET_IDENTITY_SCHEMA","SET_PAGINATION_SCHEMA",
                                        "PAGE_IDENTITY_CHANGED","INCOMPLETE_OR_DUPLICATE_SET"}:
                        raise
                    bad_set=str(exc)
                if bad_set is not None:
                    result["skipped_invalid_sets"]+=1
                    result["provider_failures"]+=1
                    if len(result["invalid_set_samples"])<8:
                        result["invalid_set_samples"].append({
                            "language":lang,"set_code":code,"group_id":group_id,
                            "reason":bad_set,"declared":total,"received":len(complete),
                            "unique_product_ids":len({str(p.get("id")) for p in complete if isinstance(p,dict)})})
                    result["cursor"]=f"{lang}:{group_id}"
                    continue
                if lang=="Japanese" and not result["japanese_number_examples"]:
                    result["japanese_number_examples"]=sorted({
                        str(item.get("card_number")) for item in complete
                        if item.get("card_number") is not None})[:5]
                    # Bounded public metadata only; never log API keys,
                    # full provider payloads or customer/inventory records.
                    examples=[]
                    for item in complete[:3]:
                        if not isinstance(item,dict):
                            continue
                        market=item.get("cardmarket")
                        market=market if isinstance(market,dict) else {}
                        examples.append({
                            "card_number":str(item.get("card_number"))[:24],
                            "product_name":str(market.get("product_name"))[:130],
                            "product_path":urlsplit(str(market.get("product_url") or "")).path[:180],
                            "rarity":str(item.get("rarity"))[:30],
                            "subtype":str(item.get("sub_type_name"))[:30],
                        })
                    result["japanese_product_examples"]=examples
                set_diagnostics={}
                matches=matches_for_complete_set(groups,lang,code,complete,set_diagnostics)
                result["matching_printings"]+=len(matches)
                if len(result["sampled_sets"])<8:
                    result["sampled_sets"].append({"language":lang,"set_code":code,
                        "group_id":group_id,"source_products":len(complete),
                        "matched_reference_printings":len(matches),**set_diagnostics})
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
