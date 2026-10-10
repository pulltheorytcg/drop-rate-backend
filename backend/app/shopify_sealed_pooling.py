"""Deterministic, auditable plan for published identical sealed Shopify products.

This module provides pure product identity, eligibility and remote readback checks.
It never creates a product or moves physical stock by itself. Admin-controlled
application must stage remote stock as unavailable before updating ownership
links and audit every operation; see docs/SHOPIFY_SEALED_POOLING.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .seller_inventory_policy import seller_held_consignment


_ONE_COPY_SEALED_SENTENCE = " is an individually tracked sealed TCG product from Drop Rate inventory."
_POOLED_SEALED_SENTENCE = (
    " is a sealed TCG product offered from interchangeable verified physical packs. "
    "Each pack remains individually tracked in Drop Rate inventory."
)
_SINGLE_INVENTORY_ROW = re.compile(
    r"<li\b[^>]*>\s*<strong>\s*Inventory\s+ID:\s*</strong>.*?</li>",
    re.IGNORECASE | re.DOTALL,
)


def pooled_sealed_description_html(value: str) -> str:
    """Remove copy-specific identifiers without changing the original store brand."""
    source = str(value or "").strip()
    if _POOLED_SEALED_SENTENCE in source and "Inventory ID:" not in source:
        return source
    if _ONE_COPY_SEALED_SENTENCE not in source:
        raise ValueError("Unrecognised Drop Rate sealed-product copy; cannot safely pool")
    if len(_SINGLE_INVENTORY_ROW.findall(source)) != 1:
        raise ValueError("Expected exactly one single-copy Inventory ID line")
    result = _SINGLE_INVENTORY_ROW.sub("", source)
    result = result.replace(_ONE_COPY_SEALED_SENTENCE, _POOLED_SEALED_SENTENCE, 1)
    if "Inventory ID:" in result:
        raise ValueError("Pooled description still contains a single physical Inventory ID")
    return result


def sealed_pool_identity(row: Mapping[str, Any]) -> dict[str, str]:
    catalogue_id = str(row.get("catalogue_id") or "").strip()
    language = str(row.get("language") or row.get("catalogue_language") or "").strip().casefold()
    seal = str(row.get("seal_status") or "").strip().casefold()
    packaging = str(row.get("sealed_product_type") or "BOOSTER_PACK").strip().casefold()
    variant = str(row.get("variant") or "").strip().casefold()
    if not catalogue_id or not language or seal != "sealed":
        raise ValueError("A verified canonical sealed-product identity is required")
    identity = {
        "catalogue_id": catalogue_id,
        "product_type": "SEALED",
        "packaging": packaging,
        "language": language,
        "seal_status": "sealed",
        "variant": variant,
        "pooling_mode": "POOLED",
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint": digest,
        "listing_key": f"shopify-pool:sealed:{digest}",
        "sku": f"DRP-S-{digest[:20].upper()}",
    }


def evaluate_published_sealed_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Sealed pooling requires at least one physical record")
    identity = sealed_pool_identity(rows[0])
    blocks: list[str] = []
    if len(rows) < 2:
        blocks.append("pool requires at least two physical copies")
    if len({str(r.get("shopify_product_gid")) for r in rows}) < 2:
        blocks.append("copies already share one Shopify product")
    if len({str(r.get("owner_id")) for r in rows}) != 1:
        blocks.append("multi-owner sealed pooling requires separate approval")
    if len({str(r.get("catalogue_id")) for r in rows}) != 1:
        blocks.append("canonical product mismatch")
    if len({str(r.get("language") or r.get("catalogue_language")) for r in rows}) != 1:
        blocks.append("mixed languages")
    if len({str(r.get("sealed_product_type") or "BOOSTER_PACK") for r in rows}) != 1:
        blocks.append("packaging mismatch")
    if len({str(r.get("variant") or "") for r in rows}) != 1:
        blocks.append("variant mismatch")
    prices={r.get("store_price_minor") for r in rows}
    if None in prices or len(prices)!=1 or next(iter(prices),0)<100:
        blocks.append("Store Prices differ or are unavailable")
    if any(r.get("synced_price_minor")!=r.get("store_price_minor") for r in rows):
        blocks.append("Shopify synced price drift")
    for r in rows:
        if r.get("product_type")!="SEALED":
            blocks.append("only sealed products may enter this pool")
        if r.get("seal_status")!="SEALED":
            blocks.append("unsealed or unknown physical product")
        if r.get("language")!=r.get("catalogue_language"):
            blocks.append("language differs from canonical product")
        if r.get("catalogue_identity_status")!="VERIFIED" or r.get("identity_confirmed") is not True:
            blocks.append("unverified canonical identity")
        if r.get("status")!="APPROVED" or r.get("sale_intent")!="FOR_SALE":
            blocks.append("physical inventory not approved for sale")
        if any(r.get(k) for k in ("condition","grading_company","grade","certificate_number")):
            blocks.append("sealed pool cannot include conditioned or graded cards")
        if r.get("acquisition_cost_minor") is None and not seller_held_consignment(r):
            blocks.append("unknown cost requires exact seller-held approval")
        if r.get("storage_location_id") is None and not seller_held_consignment(r):
            blocks.append("unknown storage requires exact seller-held approval")
        if r.get("sync_state")!="PUBLISHED" or r.get("test_mode") is not False:
            blocks.append("Shopify link is not a live published record")
        if r.get("reserved_order_reference") or r.get("reserved_line_reference"):
            blocks.append("linked copy reserved by order")
        if r.get("has_active_reservation") or r.get("has_listing_membership") or r.get("has_live_ebay_link"):
            blocks.append("copy reserved or listed on another channel")
        if not r.get("created_by_user_id"):
            blocks.append("Shopify publishing actor not known")
    for field in ("shopify_location_gid","shopify_publication_gid","shop_domain"):
        values={str(r.get(field) or "") for r in rows}
        if len(values)!=1 or not next(iter(values)):
            blocks.append(field+" mismatch")
    if any(sealed_pool_identity(r)["listing_key"] != identity["listing_key"] for r in rows):
        blocks.append("pooled sealed identity mismatch")
    # Retain the oldest physical product URL as the customer-facing anchor.
    ordered=sorted(rows,key=lambda r:(str(r.get("inventory_created_at") or ""),
                                    str(r.get("inventory_code") or "")))
    return {
        "pool": identity,
        "ready": not blocks,
        "blockers": list(dict.fromkeys(blocks)),
        "quantity": len(rows),
        "price_minor": next(iter(prices)) if len(prices)==1 else None,
        "anchor_product_gid": ordered[0].get("shopify_product_gid"),
        "anchor_variant_gid": ordered[0].get("shopify_variant_gid"),
        "anchor_inventory_item_gid": ordered[0].get("shopify_inventory_item_gid"),
        "other_products": list(dict.fromkeys(str(r["shopify_product_gid"]) for r in ordered[1:])),
        "members": ordered,
    }


def validate_sealed_remote_snapshots(
    group: Mapping[str, Any], snapshots: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Read-only remote safety gate; no barcode/cost or owner identity guessing."""
    blockers=[]
    expected=Counter(str(row.get("shopify_product_gid")) for row in group["members"])
    originals=[]
    for product_id,quantity in expected.items():
        remote=snapshots.get(product_id)
        if not isinstance(remote, Mapping):
            blockers.append("missing Shopify product snapshot");continue
        variants=remote.get("variants")
        nodes=variants.get("nodes") if isinstance(variants, Mapping) else None
        if not isinstance(nodes,list) or len(nodes)!=1 or not isinstance(nodes[0],Mapping):
            blockers.append("expected exactly one Shopify variant");continue
        variant=nodes[0]
        item=variant.get("inventoryItem")
        if not isinstance(item, Mapping):
            blockers.append("missing Shopify inventory item");continue
        physical=next(row for row in group["members"] if row["shopify_product_gid"]==product_id)
        if str(remote.get("status"))!="ACTIVE":
            blockers.append("Shopify product not ACTIVE")
        if str(variant.get("id"))!=str(physical.get("shopify_variant_gid")):
            blockers.append("Shopify variant drift")
        if str(item.get("id"))!=str(physical.get("shopify_inventory_item_gid")):
            blockers.append("Shopify inventory item drift")
        if item.get("tracked") is not True or variant.get("inventoryPolicy")!="DENY":
            blockers.append("untracked inventory or oversell policy")
        if int(variant.get("inventoryQuantity") or 0)!=quantity:
            blockers.append("available quantity drift")
        if str(variant.get("price"))!=f"{int(group['price_minor'])/100:.2f}":
            blockers.append("Shopify price drift")
        media=remote.get("media")
        images=media.get("nodes") if isinstance(media, Mapping) else None
        if not isinstance(images,list) or len(images)!=1 or not images[0].get("id"):
            blockers.append("expected one approved product image")
        originals.append((
            tuple(str(x.get("id")) for x in images or []),
            str(remote.get("title") or ""),
            tuple(sorted(remote.get("tags") or [])),
            str(remote.get("vendor") or ""),
            str(remote.get("productType") or ""),
            tuple(sorted((x.get("title") or "") for x in (remote.get("collections") or {}).get("nodes",[]))),
        ))
    if len(set(originals))>1:
        blockers.append("remote titles, artwork, tags or collections differ")
    return list(dict.fromkeys(blockers))
