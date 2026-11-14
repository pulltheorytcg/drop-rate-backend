"""Read-only exact-source diagnostic for newest Pokémon Cardmarket gaps.

No catalogue mutations, valuation calculation, grade inference, or printing
selection. Official source-file intersections are NOT proof of an item sale.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .cardmarket_public_pilot import PilotError, _id, _rows
from .cardmarket_bulk_crosswalk import _product_name_matches, _text

SET_ID = "me06"
MAX_SET_CARDS = 500
MAX_DETAIL_REQUESTS = 12


def select_samples(manifest: dict, *, max_details: int = MAX_DETAIL_REQUESTS) -> list[dict]:
    if (not isinstance(manifest, dict) or manifest.get("id") != SET_ID
            or not isinstance(manifest.get("cards"), list)
            or not 1 <= len(manifest["cards"]) <= MAX_SET_CARDS
            or not 1 <= max_details <= MAX_DETAIL_REQUESTS):
        raise PilotError("Unexpected official Pokémon set manifest")
    cards = manifest["cards"]
    ids = set()
    for row in cards:
        if not isinstance(row, dict):
            raise PilotError("Malformed source card")
        local, provider_id = row.get("localId"), row.get("id")
        if (not isinstance(local, str) or not local.isascii()
                or not local.isalnum() or len(local)>12
                or provider_id != SET_ID+"-"+local or provider_id in ids
                or not isinstance(row.get("name"), str) or not row["name"].strip()):
            raise PilotError("Ambiguous source-set card ID or name")
        ids.add(provider_id)
    # Deterministic, distributed sampling of commons, rares and secret numbers.
    picks = sorted({min(len(cards)-1, (j*(len(cards)-1))//max(1, max_details-1))
                    for j in range(max_details)})
    return [cards[i] for i in picks]


def release_listing_evidence(manifest: dict, singles_export: dict,
                             nonsingles_export: dict, *, now: datetime) -> dict:
    """Diagnostic named-release presence; never a source-ID price match."""
    if not isinstance(manifest,dict) or manifest.get("id") != SET_ID:
        raise PilotError("Unexpected set identity")
    name = manifest.get("name")
    if not isinstance(name,str) or not name.strip():
        raise PilotError("Unexpected set name")
    token = "".join(ch for ch in name.casefold() if ch.isalnum())
    if len(token) < 6:
        raise PilotError("Unusable official set-title token")
    singles,_ = _rows(singles_export,"products",now=now)
    other,_ = _rows(nonsingles_export,"products",now=now)
    result = {}
    for kind,source in (("single",singles),("non_single",other)):
        hits=[]
        for row in source:
            source_name=row.get("name")
            if (not isinstance(source_name,str) or
                    token not in "".join(ch for ch in source_name.casefold() if ch.isalnum())):
                continue
            hits.append({"id":_id(row.get("idProduct")),"name":source_name,
                         "expansion":_id(row.get("idExpansion")),
                         "category":row.get("categoryName")})
        result[kind+"_release_title_mentions"]=len(hits)
        result[kind+"_release_title_examples"]=hits[:8]
    result["release_title_is_not_printing_match"]=True
    return result


def detail_evidence(manifest: dict, detailed_cards: list[dict],
                    products_export: dict, guide_export: dict, *,
                    now: datetime) -> dict[str, Any]:
    samples = select_samples(manifest)
    if not isinstance(detailed_cards, list) or len(detailed_cards) != len(samples):
        raise PilotError("Detail response must exactly match bounded sample")
    products, product_at = _rows(products_export, "products", now=now)
    guides, guide_at = _rows(guide_export, "priceGuides", now=now)
    if abs((product_at-guide_at).total_seconds()) > 2*86400:
        raise PilotError("Official Cardmarket snapshots not aligned")
    by_id, prices = {}, set()
    for row in products:
        source_id = _id(row.get("idProduct"))
        if source_id is None or source_id in by_id:
            raise PilotError("Duplicate/invalid Cardmarket catalogue ID")
        by_id[source_id] = row
    for row in guides:
        source_id = _id(row.get("idProduct"))
        if source_id is None or source_id in prices:
            raise PilotError("Duplicate/invalid Cardmarket guide ID")
        prices.add(source_id)
    sample_receipt = []
    matched_ids = set()
    expansion_names = defaultdict(set)
    # Name-overlap is a *diagnostic only*, not a valid product match.
    for row in products:
        if _text(row.get("categoryName")) not in {"pokemon single", "pokémon single"}:
            continue
        expansion = _id(row.get("idExpansion"))
        if expansion is None:
            continue
        for candidate in samples:
            if _text(row.get("name")) == _text(candidate["name"]):
                expansion_names[expansion].add(_text(candidate["name"]))

    for short, detailed in zip(samples, detailed_cards):
        if (not isinstance(detailed, dict)
                or detailed.get("id") != short["id"]
                or detailed.get("name") != short["name"]
                or str(detailed.get("localId")) != str(short["localId"])
                or (isinstance(detailed.get("set"),dict)
                    and detailed["set"].get("id") != SET_ID)):
            raise PilotError("Source card detail changed printing identity")
        variants = detailed.get("variants_detailed") or []
        if not isinstance(variants, list) or len(variants) > 40:
            raise PilotError("Invalid official variants list")
        declared = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise PilotError("Malformed official variant")
            product_id = _id((variant.get("thirdParty") or {}).get("cardmarket"))
            advertised = _id(((variant.get("pricing") or {}).get("cardmarket") or {}).get("idProduct"))
            if product_id is None:
                continue
            product = by_id.get(product_id)
            observed = {
                "source_id": product_id,
                "variant_type": variant.get("type"),
                "variant_id_present": bool(variant.get("variantId")),
                "matches_detail_quote_id": advertised == product_id,
                "catalogue_found": product is not None,
                "guide_found": product_id in prices,
                "category": product.get("categoryName") if product else None,
                "expansion_id": product.get("idExpansion") if product else None,
                "exact_name": _text(product.get("name")) == _text(short["name"]) if product else False,
            }
            if product is not None and product_id in prices:
                matched_ids.add(product_id)
            declared.append(observed)
        sample_receipt.append({
            "provider_id": short["id"], "local_id": short["localId"],
            "name": short["name"], "detail_variants": len(variants),
            "direct_cardmarket_ids": len({x["source_id"] for x in declared}),
            "direct_source_ids": declared[:12],
        })
    coexpansions = [
        {"expansion_id": ident, "overlapping_sample_names": len(names)}
        for ident, names in expansion_names.items() if len(names) >= 4
    ]
    coexpansions.sort(key=lambda x: (-x["overlapping_sample_names"],x["expansion_id"]))
    return {
        "status": "READ_ONLY_NO_PRICE_PUBLICATION",
        "set_id": SET_ID, "set_name": manifest.get("name"),
        "set_cards": len(manifest["cards"]),
        "sampled_cards": len(samples),
        "samples_with_direct_cardmarket_id": sum(bool(x["direct_cardmarket_ids"]) for x in sample_receipt),
        "sampled_direct_ids_with_guide": len(matched_ids),
        "cardmarket_product_rows": len(products),
        "cardmarket_guide_rows": len(guides),
        "product_export_at": product_at.isoformat(),
        "guide_export_at": guide_at.isoformat(),
        "source_name_overlap_expansions_NOT_MATCHES": coexpansions[:10],
        "samples": sample_receipt,
        "verified_printing_price_matches": 0,
        "db_writes": 0, "shopify_writes": 0, "uk_sold_market_values": 0,
    }
