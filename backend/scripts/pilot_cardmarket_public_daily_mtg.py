"""Non-publishing, bounded verification of official Cardmarket Magic daily files.

Default mode has no Supabase, Cloudflare, Shopify, paid API or credentials.
Explicit --archive-r2 preserves public source bytes in existing private storage.
Live values, individual seller quotes and product-specific guides are NOT logged.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
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
MTGJSON_NOTICE = """Copyright © 2018 – Present, Zach Halpern
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""


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
            "collector_number": card.get("number"), "set_code": card.get("setCode"),
            "set_name": set_name, "language": "English", "paper": True,
            "finishes": card.get("finishes"), "identifiers": card.get("identifiers"),
        })
    return result


async def _get(client: httpx.AsyncClient, source: str, url: str, *, snapshot_dir: Path | None = None) -> tuple[dict, dict]:
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
    if snapshot_dir is not None:
        (snapshot_dir / (source + ".json")).write_bytes(b"".join(chunks))
    return payload, {"source": source, "sha256": digest.hexdigest(),
                     "bytes": size, "redirected": str(response.url) != url}


async def _run(*, snapshot_dir: Path | None = None, storage=None) -> dict:
    timeout = httpx.Timeout(90.0, connect=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                 headers={"User-Agent": "DropRatePublicPricingPilot/1.0",
                                          "Accept": "application/json"}) as client:
        products, product_receipt = await _get(client,"product_catalogue",SOURCES["product_catalogue"], snapshot_dir=snapshot_dir)
        guides, guide_receipt = await _get(client,"price_guide",SOURCES["price_guide"], snapshot_dir=snapshot_dir)
        mtg, mtg_receipt = await _get(client,"mtgjson_foundations",SOURCES["mtgjson_foundations"], snapshot_dir=snapshot_dir)
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
    receipt = {
        "status": report["status"], "source_cards": len(rows),
        "crosswalk_unique_ids": report["crosswalk_unique_ids"],
        "crosswalk_collision_ids": report["crosswalk_collision_ids"],
        "expansion_cohorts_corroborated": report["expansion_cohorts_corroborated"],
        "expansion_ids_ambiguous": report["expansion_ids_ambiguous"],
        "min_distinct_anchor_names": report["min_distinct_anchor_names"],
        "candidate_count": report["candidate_count"],
        "accepted_product_ids": report["accepted_product_ids"],
        "candidate_finish_counts": report["candidate_finish_counts"],
        "guide_distinctions": report["guide_distinctions"],
        "physical_market_value_eligible": report["physical_market_value_eligible"],
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

    if storage is not None:
        receipt["r2_snapshot"] = archive_sources(storage, snapshot_dir, receipt)
        receipt["r2_writes"] = "VERIFIED_CONTENT_ADDRESSED_SNAPSHOT"
    return receipt


def archive_sources(storage, directory: Path, receipt: dict) -> dict:
    """Preserve exact public response bytes; no database or pricing publication."""
    # Verify EVERY local file before uploading any. Only the fixed public sources
    # are accepted; never archive arbitrary caller paths or user inventory.
    files = []
    sources = receipt["source_receipts"]
    if len(sources) != len(SOURCES) or {r["source"] for r in sources} != set(SOURCES):
        raise PilotError("Incomplete public source receipt")
    for source in sources:
        name = source["source"]
        path = directory / (name + ".json")
        if path.is_symlink() or not path.is_file():
            raise PilotError("Invalid snapshot file")
        size = path.stat().st_size
        if not 0 < size <= MAX_BYTES[name] or size != source["bytes"]:
            raise PilotError("Snapshot size mismatch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise PilotError("Snapshot checksum mismatch")
        files.append((source, path))
    objects = []
    for source, path in files:
        result = storage.put_verified_file(path, category="exports", content_type="application/json")
        if (result.get("verified") is not True or result.get("sha256") != source["sha256"]
                or result.get("size_bytes") != source["bytes"]):
            raise PilotError("Remote snapshot verification failed")
        objects.append({"source": source["source"], "source_url": SOURCES[source["source"]], **result})
    manifest = {"schema": "drop-rate-cardmarket-public-source-snapshot-v1",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "objects": objects, "pilot_receipt": receipt,
                "rights_basis": "https://insight.cardmarket.com/en/Articles/the-state-of-cardmarket-2024",
                "mtgjson_license_url": "https://mtgjson.com/license/",
                "mtgjson_license_notice": MTGJSON_NOTICE,
                "publication": "SOURCE_ARCHIVE_ONLY_NOT_MARKET_VALUE"}
    path = directory / "cardmarket-source.manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True))
    result = storage.put_verified_file(path, category="exports", content_type="application/json")
    if (result.get("verified") is not True or result.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
            or result.get("size_bytes") != path.stat().st_size):
        raise PilotError("Remote manifest verification failed")
    return {"manifest": result, "objects_verified": len(objects), "database_writes": 0}


async def run(*, archive_r2: bool = False) -> dict:
    if not archive_r2:
        return await _run()
    from app.object_storage import configured_object_storage
    storage = configured_object_storage()
    if storage is None:
        raise PilotError("Existing object storage is not configured")
    with tempfile.TemporaryDirectory(prefix="cardmarket-public-snapshot-") as directory:
        return await _run(snapshot_dir=Path(directory), storage=storage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-r2", action="store_true", help="Archive verified public source bytes to existing R2; no database writes")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(archive_r2=args.archive_r2)), sort_keys=True))
