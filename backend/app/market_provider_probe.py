from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .parse_client import ParseApiError, ParseHttpClient
from .settings import get_settings


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

# Current public Parse Getcollectr API used only by the non-persistent probe.
# The production Collectr adapter remains separately gated until its full
# product/detail contract is re-validated for ingestion.
COLLECTR_PROBE_SCRAPER_ID = "431c8f3b-b286-45b3-bc03-24589edf1797"


PROBES: tuple[dict[str, Any], ...] = (
    {
        "source": "EBAY",
        "label": "eBay UK active",
        "scraper_id": "923c816c-9218-4c32-ae0c-2eac3d514be5",
        "endpoint": "search_listings",
        "params": {"query": "Charizard", "page": 1, "category_id": "0"},
    },
    {
        "source": "EBAY",
        "label": "eBay UK sold",
        "scraper_id": "923c816c-9218-4c32-ae0c-2eac3d514be5",
        "endpoint": "search_sold_listings",
        "params": {"query": "Charizard", "page": 1, "category_id": "0"},
    },
    {
        "source": "CARDMARKET",
        "label": "Cardmarket search",
        "scraper_id": "6e8ae7ea-a15a-4125-aada-1e116c8060b5",
        "endpoint": "search_singles",
        "params": {"game": "Pokemon", "query": "Charizard", "page": 1},
    },
    {
        "source": "TCGPLAYER",
        "label": "TCGPlayer search",
        "scraper_id": "5d1e8a71-43a6-400a-9f41-6f2a4ad5cbe7",
        "endpoint": "search_cards",
        "params": {"query": "Charizard", "limit": 10, "offset": 0},
    },
    {
        "source": "COLLECTR",
        "label": "Collectr search",
        "scraper_id": COLLECTR_PROBE_SCRAPER_ID,
        "endpoint": "search_cards",
        "params": {"query": "Charizard", "page": 1},
    },
)


def _safe_sample(item: dict[str, Any]) -> dict[str, Any]:
    """Return only harmless discovery fields; never raw provider payloads."""

    allowed = (
        "title",
        "name",
        "product_name",
        "card_name",
        "product_id",
        "card_number",
        "set_name",
        "expansion",
        "rarity",
        "lowest_price",
        "market_price",
        "price",
    )
    sample: dict[str, Any] = {}
    for key in allowed:
        value = item.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is not None:
                sample[key] = value
    return sample


def _summarise_payload(data: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(key) for key in data)
    list_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for key, value in data.items():
        if not isinstance(value, list):
            continue
        list_counts[str(key)] = len(value)
        if samples:
            continue
        for item in value[:3]:
            if isinstance(item, dict):
                safe = _safe_sample(item)
                if safe:
                    samples.append(safe)

    return {"keys": keys, "list_counts": list_counts, "samples": samples}


@router.post("/provider-probe")
async def provider_probe(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Probe provider discovery endpoints without touching Drop Rate market data.

    Exactly five Parse calls are made sequentially so the free-tier 5 req/min
    allowance is respected. Current canonical Parse releases are used rather than
    pinned snapshots. No observations, mappings, pricing snapshots or inventory
    rows are written.
    """

    settings = get_settings()
    if not settings.parse_api_key:
        raise HTTPException(status_code=409, detail="Parse provider access is not configured")

    client = ParseHttpClient(api_key=settings.parse_api_key, timeout_seconds=20.0)
    results: list[dict[str, Any]] = []

    for probe in PROBES:
        try:
            data = await client.get(
                scraper_id=probe["scraper_id"],
                endpoint=probe["endpoint"],
                snapshot_version=None,
                params=probe["params"],
            )
            summary = _summarise_payload(data)
            result_count = max(summary["list_counts"].values(), default=0)
            results.append(
                {
                    "source": probe["source"],
                    "label": probe["label"],
                    "endpoint": probe["endpoint"],
                    "status": "SUCCEEDED" if result_count > 0 else "EMPTY",
                    "result_count": result_count,
                    **summary,
                }
            )
        except ParseApiError as exc:
            results.append(
                {
                    "source": probe["source"],
                    "label": probe["label"],
                    "endpoint": probe["endpoint"],
                    "status": "FAILED",
                    "result_count": 0,
                    "keys": [],
                    "list_counts": {},
                    "samples": [],
                    "error": {
                        "detail": exc.detail,
                        "provider_status_code": exc.status_code,
                        "retryable": exc.retryable,
                    },
                }
            )
        except Exception:
            results.append(
                {
                    "source": probe["source"],
                    "label": probe["label"],
                    "endpoint": probe["endpoint"],
                    "status": "FAILED",
                    "result_count": 0,
                    "keys": [],
                    "list_counts": {},
                    "samples": [],
                    "error": {"detail": "Provider probe failed validation"},
                }
            )

    return jsonable_encoder({"persisted": False, "probe_count": len(results), "results": results})
