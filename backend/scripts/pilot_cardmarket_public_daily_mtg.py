"""Non-publishing, bounded verification of official Cardmarket Magic daily files.

No Supabase, Cloudflare, Shopify, paid API or credentials. Runs in disposable CI.
Live values, individual seller quotes and product-specific guides are NOT logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import httpx

from app.cardmarket_public_pilot import read_only_mtg_pilot, PilotError
from app.fx import EcbHistoricalFxProvider

SOURCES = {
    "product_catalogue": ("https://downloads.s3.cardmarket.com/productCatalog/"
                          "productList/products_singles_1.json"),
    "price_guide": ("https://downloads.s3.cardmarket.com/productCatalog/"
                    "priceGuide/price_guide_1.json"),
    "mtgjson_foundations": "https://mtgjson.com/api/v5/FDN.json",
}
MAX_BYTES = {"product_catalogue": 48_000_000, "price_guide": 48_000_000,
             "mtgjson_foundations": 20_000_000}
MAX_SOURCE_CARDS = 2000


def source_cards(payload: dict) -> list[dict]:
    """Only published original English paper printing IDs; no name-based mapping."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise PilotError("MTGJSON set response does not contain a data object")
    set_data = payload["data"]
    set_name, cards = set_data.get("name"), set_data.get("cards")
    if not isinstance(set_name, str) or not set_name or not isinstance(cards, list):
        raise PilotError("MTGJSON set name or source cards missing")
    if len(cards) > MAX_SOURCE_CARDS:
        raise PilotError("MTGJSON pilot reference subset exceeds safe bound")
    result = []
    for card in cards:
        if not isinstance(card, dict):
            raise PilotError("Invalid MTGJSON card record")
        availability = card.get("availability")
        if not isinstance(availability, list) or "paper" not in availability:
            continue
        if card.get("isOnlineOnly") is True:
            continue
        result.append({
            "uuid": card.get("uuid"), "name": card.get("name"),
            "set_name": set_name, "language": "English", "paper": True,
            "finishes": card.get("finishes"), "identifiers": card.get("identifiers"),
        })
    return result


async def _get(client: httpx.AsyncClient, source: str, url: str) -> tuple[dict, dict]:
    if source not in MAX_BYTES or not url.startswith("https://"):
        raise PilotError("Unapproved live source")
    max_bytes = MAX_BYTES[source]
    digest = hashlib.sha256()
    size = 0
    chunks = []
    async with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        expected = response.headers.get("content-length")
        if expected and expected.isdecimal() and int(expected) > max_bytes:
            raise PilotError("Public source exceeds bounded download limit")
        if response.url.scheme != "https" or response.url.host not in {
                "downloads.s3.cardmarket.com", "mtgjson.com", "www.mtgjson.com",
                "s3.amazonaws.com"} and not response.url.host.endswith(".s3.amazonaws.com"):
            raise PilotError("Unexpected source redirect")
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise PilotError("Public source exceeds bounded download limit")
            digest.update(chunk)
            chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeError, ValueError) as exc:
        raise PilotError("Official export did not decode as JSON") from exc
    if not isinstance(payload, dict):
        raise PilotError("Official export did not contain a JSON object")
    return payload, {"source": source, "sha256": digest.hexdigest(),
                     "bytes": size, "redirected": str(response.url) != url}


async def run() -> dict:
    timeout = httpx.Timeout(90.0, connect=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                 headers={"User-Agent": "DropRatePublicPricingPilot/1.0",
                                          "Accept": "application/json"}) as client:
        products, product_receipt = await _get(client,"product_catalogue",SOURCES["product_catalogue"])
        guides, guide_receipt = await _get(client,"price_guide",SOURCES["price_guide"])
        mtg, mtg_receipt = await _get(client,"mtgjson_foundations",SOURCES["mtgjson_foundations"])
    # Fetch ECB historical rates through the same existing auditable FX adapter.
    checked = datetime.fromisoformat(str(guides.get("createdAt") or "").replace("Z","+00:00"))
    if checked.utcoffset() is None:
        raise PilotError("Cardmarket date is not timezone-aware")
    fx = await EcbHistoricalFxProvider().quote(
        base_currency="EUR", quote_currency="GBP", at=checked)
    # The FX provider records retrieval time; capture the observation clock
    # AFTER its network retrieval so a valid quote is not future-dated.
    now = datetime.now(timezone.utc)
    rows = source_cards(mtg)
    report = read_only_mtg_pilot(
        mtg_cards=rows, products_export=products, price_export=guides, fx=fx, now=now)
    # This is a provenance/coverage receipt ONLY. Do not print card IDs or prices.
    return {
        "status": report["status"], "source_cards": len(rows),
        "crosswalk_unique_ids": report["crosswalk_unique_ids"],
        "crosswalk_collision_ids": report["crosswalk_collision_ids"],
        "candidate_count": report["candidate_count"],
        "rejected": report["rejected"],
        "diagnostic_examples": report["diagnostic_examples"],
        "products_examined": report["products_examined"],
        "guides_examined": report["guides_examined"],
        "source_checked_at": report["source_checked_at"],
        "source_receipts": [product_receipt,guide_receipt,mtg_receipt],
        "fx_source": fx.source, "fx_effective_at": fx.effective_at.isoformat(),
        "verified_sold_value_count": 0, "database_writes": 0,
        "r2_writes": 0, "shopify_changes": 0,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), sort_keys=True))
