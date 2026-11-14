"""Read-only Cardmarket catalogue metadata/artwork coverage audit.

The free official download may contain marketplace product/expansion IDs without
the collector number or artwork required for accurate independent variant
matching. Never infer a physical card identity from a character name alone.
No database writes, listing values or listing-page scraping.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json

import httpx

from app.cardmarket_public_pilot import PilotError, _rows
from scripts.audit_cardmarket_bulk_feed import _read_source, _HOST

SOURCES={"pokemon":6,"one_piece":18}
IDENTITY_COLUMNS=(
    "idProduct","name","idExpansion","idCategory","categoryName",
    "number","rarity","image","imageUrl","language","expansionName",
    "idMetacard","cardNumber","variant","finish"
)


def field_coverage(export: dict, *, game: str, now: datetime) -> dict:
    if game not in SOURCES:
        raise PilotError("Unknown official game")
    products, observed=_rows(export,"products",now=now)
    presence=Counter()
    identities=set()
    images=0
    for record in products:
        ident=record.get("idProduct")
        if type(ident) is not int or ident<=0 or ident in identities:
            raise PilotError("Invalid or ambiguous first-party product ID")
        identities.add(ident)
        for key in IDENTITY_COLUMNS:
            if (key in record and record[key] is not None and
                    record[key]!="" and record[key]!=[]):
                presence[key]+=1
    return {
        "game":game, "source_updated_at":observed.isoformat(),
        "product_rows":len(products),
        "populated_fields":{key:presence[key] for key in IDENTITY_COLUMNS},
        "has_card_number_and_image":sum(
            bool(r.get("number") or r.get("cardNumber")) and
            bool(r.get("image") or r.get("imageUrl"))
            for r in products
        ),
        "has_card_number_and_rarity":sum(
            bool(r.get("number") or r.get("cardNumber")) and bool(r.get("rarity"))
            for r in products
        ),
        "cardmarket_source_image_rights_not_assumed":True,
        "crosswalk_publishable_from_name_only":False,
        "db_writes":0,
    }


async def run():
    timeout=httpx.Timeout(90.0,connect=15.0,pool=15.0)
    results={}
    async with httpx.AsyncClient(
        timeout=timeout,follow_redirects=False,
        headers={"User-Agent":"DropRateFirstPartyMetadataAudit/1.0","Accept":"application/json"}
    ) as client:
        for game,game_id in SOURCES.items():
            payload,receipt=await _read_source(
                client,_HOST+f"productList/products_singles_{game_id}.json")
            results[game]=field_coverage(payload,game=game,now=datetime.now(timezone.utc))
            results[game]["source_sha256"]=receipt["sha256"]
    return {
        "status":"OFFICIAL_BULK_METADATA_AUDIT_READ_ONLY",
        "source":"Cardmarket official daily public singles product catalogue",
        "sources":results,
        "requests":{"cardmarket":len(results)},
        "db_writes":0,"shopify_writes":0,
    }


if __name__=="__main__":
    try:
        print("CARDMARKET_METADATA_FIELD_RESULT "+
              json.dumps(asyncio.run(run()),sort_keys=True),flush=True)
    except Exception as exc:
        print("CARDMARKET_METADATA_FIELD_RESULT "+
              json.dumps({"status":"FAILED_CLOSED","error_type":type(exc).__name__,
                          "db_writes":0,"shopify_writes":0},sort_keys=True),flush=True)
        raise SystemExit(2) from None
