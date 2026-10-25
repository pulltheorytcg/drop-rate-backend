"""Bounded, free-only PokéWallet Dragon Ball catalogue reference guides.

Only `/dbs/search` is used. The Ultra-only `/dbs/prices/:set` endpoint is
never called. Search includes individual prices, but a response is NOT proof
that a physical card/condition/printing shares the market value.

The publisher's English release, exact printed number, card name, and source
printing uniqueness must all agree. Promo and alternate-art reference IDs are
excluded until independently mapped. Quotes are only indicative catalogue
guides, never automatic storefront or physical-inventory valuations.
"""
from __future__ import annotations

import html
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
from .dragon_ball_market import FUSION, MASTERS, REFERENCE_RELEASE_ALIASES
from .one_piece_market import WRITE_SQL, normalized
from .reference_market import _minor

log = logging.getLogger(__name__)
BASE_URL = "https://api.pokewallet.io"
SOURCE_CM = "POKEWALLET_DBS_CARDMARKET_CATALOGUE"
SOURCE_TCG = "POKEWALLET_DBS_TCGPLAYER_CATALOGUE"
SOURCES = {SOURCE_CM, SOURCE_TCG}
PAGE_SIZE = 100
MAX_FREE_REQUESTS_PER_RUN = 35  # 25 One Piece + 35 DBS leaves 40/hour shared headroom.
MASTERS_NUMBER = re.compile(r"(?:BT\d{1,2}|TB\d{1,2}|DB\d{1,2})-\d{3}")
FUSION_NUMBER = re.compile(r"(?:FB|FS|SB|ST)\d{2}-\d{2,3}")
# Cardmarket-only IDs are 64 hex characters. PokéWallet documents
# `dbs_` + hex for TCGplayer-linked products, but does NOT guarantee the
# same fixed digest length; its published example is longer.
SOURCE_ID = re.compile(r"(?:dbs_[0-9a-f]{32,128}|[0-9a-f]{64})")

READ_SQL = """select r.provider,r.system_code,r.language,r.provider_id,r.name,
 r.set_id,r.card_number,r.rarity,s.name as set_name,
 coalesce(p.market_value_minor,0)>0 as has_detail_value,
 coalesce(b.market_value_minor,0) as existing_catalogue_value,
 b.quotes->0->>'source' as existing_source,
 b.pricing_updated_at as existing_pricing_updated_at
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 where r.provider='Bandai Official' and r.language='English'
 and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
 and (s.release_date is null or s.release_date<=current_date)"""


class FreeSourceError(ValueError):
    """Invalid free result, insufficient quota, or incomplete pagination."""


def reference_release(ref: dict) -> str | None:
    if ref.get("provider") != "Bandai Official" or ref.get("language") != "English":
        return None
    number = str(ref.get("card_number") or "")
    system = ref.get("system_code")
    if system == MASTERS:
        if not MASTERS_NUMBER.fullmatch(number):
            return None
        # The official Masters reference uses an image filename for its base
        # printing; *_PR, *_BD, PR02 and all other variants are not the base.
        if ref.get("provider_id") != f"{ref.get('set_id')}:{number}.png":
            return None
        match = re.fullmatch(r"(?:Series \d+|[A-Z]+\d+) Booster -(.+)-",
                             str(ref.get("set_name") or ""), re.I)
    elif system == FUSION:
        if (not FUSION_NUMBER.fullmatch(number) or
                ref.get("provider_id") != f"{ref.get('set_id')}:{number}"):
            return None
        match = re.fullmatch(r"BOOSTER PACK -(.+)- \[FB\d{2}\]",
                             str(ref.get("set_name") or ""), re.I)
    else:
        return None
    return normalized(match[1]) if match else None


def eligible(ref: dict, now: datetime) -> bool:
    if ref.get("has_detail_value"):
        return False
    current = int(ref.get("existing_catalogue_value") or 0)
    if current <= 0:
        return True
    if ref.get("existing_source") not in SOURCES:
        return False
    checked = ref.get("existing_pricing_updated_at")
    return isinstance(checked,datetime) and checked < now - timedelta(days=1)


def wanted_groups(refs: list[dict], now: datetime) -> dict[str,list[dict]]:
    all_keys = defaultdict(list)
    wants = defaultdict(list)
    for ref in refs:
        release = reference_release(ref)
        if release is None:
            continue
        key=(ref["system_code"],ref["set_id"],ref["card_number"])
        all_keys[key].append(ref)
        if eligible(ref,now):
            wants[ref["card_number"].split("-")[0]].append(ref)
    # Another base identity for the same publisher printing is ambiguous.
    collisions={key for key, group in all_keys.items() if len(group)!=1}
    return {prefix:[ref for ref in group if
             (ref["system_code"],ref["set_id"],ref["card_number"]) not in collisions]
            for prefix,group in wants.items()}


def complete_search_page(body: dict, query: str, page: int) -> tuple[list[dict],int]:
    pagination=body.get("pagination")
    if (not isinstance(body,dict) or not isinstance(pagination,dict)
            or str(body.get("query") or "").casefold()!=query.casefold()
            or not isinstance(body.get("results"),list)):
        raise FreeSourceError("SEARCH_SCHEMA")
    total=pagination.get("total")
    pages=pagination.get("total_pages")
    if (type(total) is not int or type(pages) is not int or
            type(pagination.get("page")) is not int or
            pagination["page"]!=page or total<0 or pages<0 or
            pages != ceil(total/PAGE_SIZE) or total>100_000 or
            (isinstance(body.get("metadata"),dict) and
             body["metadata"].get("truncated") is True)):
        raise FreeSourceError("INCOMPLETE_SEARCH")
    results=body["results"]
    expected_count=min(PAGE_SIZE,max(0,total-(page-1)*PAGE_SIZE))
    if (len(results)!=expected_count or
            any(not isinstance(r,dict) for r in results)):
        raise FreeSourceError("INCOMPLETE_SEARCH")
    return results,pages


def verified_matches(refs: list[dict], products: list[dict]) -> tuple[list[tuple[dict,dict]],dict]:
    grouped = defaultdict(list)
    for product in products:
        info=product.get("card_info")
        if (not SOURCE_ID.fullmatch(str(product.get("id") or ""))
                or not isinstance(info,dict)
                or info.get("product_type")!="card"
                or not isinstance(info.get("set_id"),str) or not info["set_id"]):
            continue
        number=str(info.get("card_number") or "")
        if not (MASTERS_NUMBER.fullmatch(number) or FUSION_NUMBER.fullmatch(number)):
            continue
        grouped[(number,normalized(html.unescape(info.get("set_name") or "")))].append(product)
    matches=[]
    diagnostic={"considered":len(refs),"candidate_numbers":0,"unique_sources":0,
                "matching_release":0,"matching_name":0,"matching_rarity":0}
    for ref in refs:
        expected=reference_release(ref)
        alias=REFERENCE_RELEASE_ALIASES.get(
            (ref["system_code"],ref["set_id"],ref["set_name"]))
        releases={expected,normalized(alias) if alias else expected}
        candidates=[p for release in releases for p in
                    grouped.get((ref["card_number"],release),[])]
        if candidates:
            diagnostic["candidate_numbers"]+=1
        # Some Cardmarket and TCGplayer source IDs represent different art
        # variants under the same number. Never pick the one with a price.
        if len(candidates)!=1:
            continue
        diagnostic["unique_sources"]+=1
        source=candidates[0]
        info=source["card_info"]
        source_release=normalized(html.unescape(info.get("set_name") or ""))
        if source_release not in releases:
            continue
        diagnostic["matching_release"]+=1
        if normalized(html.unescape(info.get("name") or "")) != normalized(html.unescape(ref["name"])):
            continue
        diagnostic["matching_name"]+=1
        source_rarity=normalized(info.get("rarity") or "")
        reference_rarity=normalized(str(ref.get("rarity") or "").split("[")[0])
        if source_rarity and reference_rarity and source_rarity!=reference_rarity:
            continue
        diagnostic["matching_rarity"]+=1
        matches.append((ref,source))
    return matches,diagnostic


def source_guide(ref: dict, product: dict, rates: dict, observed: datetime) -> dict | None:
    selected=None
    cm=product.get("cardmarket")
    if isinstance(cm,dict) and isinstance(cm.get("prices"),list):
        normal=[p for p in cm["prices"] if isinstance(p,dict) and
                p.get("variant_type")=="normal"]
        finish="Normal"
        if not normal:
            # Some base printings are foil-only. An explicit sole foil is a
            # foil guide, not an invented normal price.
            normal=[p for p in cm["prices"] if isinstance(p,dict) and
                    p.get("variant_type")=="foil"]
            finish="Holofoil"
        if len(normal)==1:
            try:
                value=_minor(normal[0].get("trend"))
                if value>0:
                    selected=(SOURCE_CM,"CARDMARKET","EUR","trend",value,cm.get("product_url"),finish)
            except (ValueError,TypeError,ArithmeticError):
                pass
    tcg=product.get("tcgplayer")
    if selected is None and isinstance(tcg,dict) and isinstance(tcg.get("prices"),list):
        normal=[p for p in tcg["prices"] if isinstance(p,dict) and
                str(p.get("sub_type_name") or "").casefold()=="normal"]
        finish="Normal"
        if not normal:
            normal=[p for p in tcg["prices"] if isinstance(p,dict) and
                    str(p.get("sub_type_name") or "").casefold()=="foil"]
            finish="Holofoil"
        if len(normal)==1:
            try:
                value=_minor(normal[0].get("market_price"))
                if value>0:
                    selected=(SOURCE_TCG,"TCGPLAYER","USD","market_price",value,tcg.get("url"),finish)
            except (ValueError,TypeError,ArithmeticError):
                pass
    if selected is None:
        return None
    source,market,currency,field,original,url,finish=selected
    if url:
        parsed=urlsplit(str(url))
        allowed={"www.cardmarket.com","cardmarket.com"} if market=="CARDMARKET" else {
            "www.tcgplayer.com","tcgplayer.com"}
        if parsed.scheme!="https" or parsed.hostname not in allowed:
            return None
    fx=rates.get(currency)
    if fx is None:
        return None
    converted=int((Decimal(original)*fx.rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    if converted<=0:
        return None
    info=product["card_info"]
    return {
        "source":source,"aggregator":"POKEWALLET","market":market,
        "source_card_id":product["id"],"source_set_id":info["set_id"],
        "source_product_url":url,"source_field":field,
        "original_currency":currency,"original_minor":original,
        "price_gbp_minor":converted,"observed_at":observed.isoformat(),
        "finish":finish,"guide_scope":"Indicative base-printing marketplace guide",
        "valuation_role":"MIXED_LANGUAGE_REFERENCE","physical_valuation_eligible":False,
        "physical_language_confirmed":False,"condition_specific":False,"sold_comparable":False,
        "match_basis":"EXACT_BANDAI_RELEASE_NUMBER_NAME_UNIQUE_BASE_PRINTING",
        "reference_printing_id":ref["provider_id"],"reference_rarity":ref.get("rarity"),
        "reference_language":ref["language"],
        "reference_identity":{k:ref[k] for k in ("name","set_id","card_number","set_name")},
        "fx_rate_to_gbp":str(fx.rate),"fx_source":fx.source,
        "fx_effective_at":fx.effective_at.isoformat(),
        "fx_retrieved_at":fx.retrieved_at.isoformat(),
    }


class FreeDragonBallClient:
    def __init__(self,api_key: str,limit: int,http_client):
        if not api_key.startswith("pk_live_") or not 1<=limit<=MAX_FREE_REQUESTS_PER_RUN:
            raise FreeSourceError("INVALID_KEY_OR_BUDGET")
        self.key,self.limit,self.http=api_key,limit,http_client
        self.requests=0

    async def search(self,query: str,page: int) -> dict:
        if not re.fullmatch(r"[A-Z]{1,3}\d{1,2}",query) or self.requests>=self.limit:
            raise FreeSourceError("INVALID_QUERY_OR_BUDGET")
        self.requests+=1
        response=await self.http.get(BASE_URL+"/dbs/search",
            params={"q":query,"page":page,"limit":PAGE_SIZE},
            headers={"X-API-Key":self.key,"Accept":"application/json"})
        if response.status_code==429:
            raise FreeSourceError("RATE_LIMITED")
        if response.status_code>=400:
            raise FreeSourceError("UPSTREAM_HTTP_"+str(response.status_code))
        for name in ("X-RateLimit-Remaining-Hour","X-RateLimit-Remaining-Day"):
            amount=response.headers.get(name)
            if amount is not None and amount.isdigit() and int(amount)<5:
                raise FreeSourceError("SHARED_QUOTA_LOW")
        if len(response.content)>4_000_000:
            raise FreeSourceError("RESPONSE_TOO_LARGE")
        body=response.json()
        if not isinstance(body,dict):
            raise FreeSourceError("SEARCH_SCHEMA")
        return body


async def refresh_pokewallet_dragon_ball(pool,actor,fx,api_key: str, *,
                                         dry_run=True,request_limit=MAX_FREE_REQUESTS_PER_RUN,
                                         previous_cursor=None,http_client=None) -> dict:
    """Free, round-robin search batches; full query pages or no quote."""
    now=datetime.now(timezone.utc)
    budget=min(request_limit,8 if dry_run else MAX_FREE_REQUESTS_PER_RUN)
    report={"source":"POKEWALLET_DBS_FREE","dry_run":dry_run,"requests":0,
            "checked_references":0,"target_prefixes":0,"matches":0,
            "eligible_quotes":0,"writes_attempted":0,"cursor":previous_cursor,
            "input_cursor":previous_cursor,"sampled_queries":[],"provider_failures":0}
    client=None
    owns_http=False
    try:
        async with user_connection(pool,actor,str(uuid4())) as connection:
            refs=[dict(r) for r in await connection.fetch(READ_SQL)]
        report["checked_references"]=len(refs)
        groups=wanted_groups(refs,now)
        targets=sorted((k for k,v in groups.items() if v),key=lambda k:(-len(groups[k]),k))
        report["target_prefixes"]=len(targets)
        if previous_cursor in targets:
            index=targets.index(previous_cursor)+1
            targets=targets[index:]+targets[:index]
        if http_client is None:
            http_client=httpx.AsyncClient(timeout=18,follow_redirects=False)
            owns_http=True
        client=FreeDragonBallClient(api_key,budget,http_client)
        rates={}
        for prefix in targets:
            if client.requests>=budget:
                break
            report["cursor"]=prefix
            try:
                first=await client.search(prefix,1)
                products,pages=complete_search_page(first,prefix,1)
                if pages>budget-client.requests+1:
                    report["deferred_queries"]=report.get("deferred_queries",0)+1
                    continue
                complete=list(products)
                for page in range(2,pages+1):
                    next_body=await client.search(prefix,page)
                    chunk,count=complete_search_page(next_body,prefix,page)
                    if count!=pages:
                        raise FreeSourceError("PAGINATION_CHANGED")
                    complete.extend(chunk)
                if len(complete)!=(first["pagination"]["total"]):
                    raise FreeSourceError("INCOMPLETE_SEARCH")
                ids=[str(p.get("id")) for p in complete]
                if len(ids)!=len(set(ids)):
                    raise FreeSourceError("DUPLICATE_SOURCE_ID")
                matches,counts=verified_matches(groups[prefix],complete)
                report["matches"]+=len(matches)
                if len(report["sampled_queries"])<10:
                    report["sampled_queries"].append({
                        "prefix":prefix,"source_rows":len(complete),
                        "matched":len(matches),**counts})
                values=[]
                for ref,product in matches:
                    # Never ask for USD FX if the free Cardmarket EUR quote
                    # is usable. Request each rate once for this bounded run.
                    if "EUR" not in rates:
                        rates["EUR"]=await fx.quote(base_currency="EUR",
                                                     quote_currency="GBP",at=now)
                    quote=source_guide(ref,product,rates,now)
                    if quote is None and "USD" not in rates:
                        rates["USD"]=await fx.quote(base_currency="USD",
                                                     quote_currency="GBP",at=now)
                        quote=source_guide(ref,product,rates,now)
                    if quote is None:
                        continue
                    report["eligible_quotes"]+=1
                    values.append((ref["provider"],ref["system_code"],ref["language"],
                        ref["provider_id"],[quote],quote["price_gbp_minor"],
                        quote["price_gbp_minor"],now,now,now+timedelta(days=1),
                        ref["name"],ref["set_id"],ref["card_number"],ref["set_name"],
                        ref.get("rarity"),quote["source"]))
                if values and not dry_run:
                    for start in range(0,len(values),100):
                        async with user_connection(pool,actor,str(uuid4())) as connection:
                            await connection.executemany(WRITE_SQL,values[start:start+100])
                    report["writes_attempted"]+=len(values)
            except FreeSourceError as exc:
                if str(exc) in {"INCOMPLETE_SEARCH","PAGINATION_CHANGED",
                                "DUPLICATE_SOURCE_ID","SEARCH_SCHEMA"}:
                    report["invalid_queries"]=report.get("invalid_queries",0)+1
                    continue
                raise
    except (httpx.HTTPError,FreeSourceError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        report["provider_failures"]+=1
        report["reason"]=str(exc) if isinstance(exc,FreeSourceError) else type(exc).__name__
    finally:
        if client is not None:
            report["requests"]=client.requests
        if owns_http:
            await http_client.aclose()
    log.warning("Pokewallet free DBS request=%s quote=%s writes=%s failures=%s",
                report["requests"],report["eligible_quotes"],
                report["writes_attempted"],report["provider_failures"])
    return report
