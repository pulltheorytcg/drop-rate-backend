"""Read-only audit of ONE Cardmarket public catalogue/guide pair.

Example:
  PYTHONPATH=backend python backend/scripts/audit_cardmarket_bulk_feed.py \\
    --game pokemon --kind singles --read-only

Makes exactly two unauthenticated GETs to official download files, no retries,
files, DB calls, price publication, R2 uploads or app configuration changes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

import httpx

from app.cardmarket_bulk_feed_audit import GAME_IDS, PRODUCT_KINDS, audit_bulk_exports
from app.cardmarket_public_pilot import PilotError

_HOST = "https://downloads.s3.cardmarket.com/productCatalog/"
_MAX_BYTES = 64_000_000


async def _read_source(client: httpx.AsyncClient, url: str) -> tuple[dict, dict]:
    if not url.startswith(_HOST) or (
        "/productList/products_" not in url and "/priceGuide/price_guide_" not in url
    ):
        raise PilotError("Unexpected Cardmarket source URL")
    digest = hashlib.sha256()
    chunks = []
    length = 0
    async with client.stream("GET", url, follow_redirects=False) as response:
        if response.status_code != 200:
            raise PilotError("Cardmarket public source unavailable")
        declared = response.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BYTES):
            raise PilotError("Cardmarket source exceeds byte limit")
        async for chunk in response.aiter_bytes():
            length += len(chunk)
            if length > _MAX_BYTES:
                raise PilotError("Cardmarket source exceeds byte limit")
            digest.update(chunk)
            chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeError, ValueError) as exc:
        raise PilotError("Cardmarket source is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PilotError("Cardmarket source is not a JSON object")
    return payload, {"sha256": digest.hexdigest(), "bytes": length}


async def run(game: str, kind: str) -> dict:
    if game not in GAME_IDS or kind not in PRODUCT_KINDS:
        raise PilotError("Unsupported Cardmarket feed")
    game_id = GAME_IDS[game]
    catalogue_url = _HOST + "productList/products_" + kind + "_" + str(game_id) + ".json"
    guide_url = _HOST + "priceGuide/price_guide_" + str(game_id) + ".json"
    timeout = httpx.Timeout(90.0, connect=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                 headers={"User-Agent": "DropRateReadOnlyAudit/1.0",
                                          "Accept": "application/json"}) as client:
        products, products_hash = await _read_source(client, catalogue_url)
        guides, guide_hash = await _read_source(client, guide_url)
    from datetime import datetime, timezone
    result = audit_bulk_exports(game=game, product_kind=kind,
                                products_export=products, price_export=guides,
                                now=datetime.now(timezone.utc))
    result["source_receipts"] = {
        "catalogue": products_hash, "price_guide": guide_hash
    }
    result["provider_requests"] = 2
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=tuple(GAME_IDS), required=True)
    parser.add_argument("--kind", choices=PRODUCT_KINDS, required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.game, args.kind)), sort_keys=True))


if __name__ == "__main__":
    main()
