from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .ebay_official_client import EbayApiError, EbayOfficialClient
from .parse_client import ParseApiError, ParseHttpClient
from .settings import get_settings


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

# Parse's marketplace page has its own catalogue page ID, but calls must use
# the scraper ID published in the endpoint URL. This is used only by the
# non-persistent provider probe.
COLLECTR_PROBE_SCRAPER_ID = "deec24d2-ffc5-41bd-b3fd-99cd817443e2"


SUPPORTING_PROBES: tuple[dict[str, Any], ...] = (
    {
        "source": "CARDMARKET",
        "label": "Cardmarket search",
        "scraper_id": "6e8ae7ea-a15a-4125-aada-1e116c8060b5",
        "endpoint": "search_singles",
        "result_key": "results",
        "params": {"game": "Pokemon", "query": "Charizard", "page": 1},
    },
    {
        "source": "TCGPLAYER",
        "label": "TCGPlayer search",
        "scraper_id": "5d1e8a71-43a6-400a-9f41-6f2a4ad5cbe7",
        "endpoint": "search_cards",
        "result_key": "cards",
        "params": {"query": "Charizard", "limit": 10, "offset": 0},
    },
    {
        "source": "COLLECTR",
        "label": "Collectr search",
        "scraper_id": COLLECTR_PROBE_SCRAPER_ID,
        "endpoint": "search_cards",
        "result_key": "items",
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


def _summarise_payload(data: dict[str, Any], *, result_key: str) -> dict[str, Any]:
    keys = sorted(str(key) for key in data)
    list_counts = {
        str(key): len(value)
        for key, value in data.items()
        if isinstance(value, list)
    }
    result_rows = data.get(result_key)
    if not isinstance(result_rows, list):
        raise ValueError("Provider response is missing the expected result array")

    samples: list[dict[str, Any]] = []
    for item in result_rows[:3]:
        if isinstance(item, dict):
            safe = _safe_sample(item)
            if safe:
                samples.append(safe)

    return {
        "keys": keys,
        "list_counts": list_counts,
        "result_key": result_key,
        "result_count": len(result_rows),
        "samples": samples,
    }


@router.post("/provider-probe")
async def provider_probe(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Probe providers without persisting market observations or pricing.

    eBay ACTIVE uses the official Browse API. eBay SOLD is reported explicitly
    as restricted unless Marketplace Insights access is separately configured.
    Supporting providers continue to use their permitted Parse-backed adapters.
    """

    settings = get_settings()
    results: list[dict[str, Any]] = []

    if settings.ebay_client_id and settings.ebay_client_secret:
        ebay = EbayOfficialClient(
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            marketplace_id=settings.ebay_marketplace_id,
            timeout_seconds=20.0,
        )
        try:
            data = await ebay.search_items(
                query="Charizard",
                limit=10,
                item_location_country="GB",
            )
            summary = _summarise_payload(data, result_key="itemSummaries")
            result_count = int(summary["result_count"])
            results.append(
                {
                    "source": "EBAY",
                    "label": "eBay UK active · official Browse",
                    "endpoint": "GET /buy/browse/v1/item_summary/search",
                    "status": "SUCCEEDED" if result_count > 0 else "EMPTY",
                    **summary,
                }
            )
        except EbayApiError as exc:
            results.append(
                {
                    "source": "EBAY",
                    "label": "eBay UK active · official Browse",
                    "endpoint": "GET /buy/browse/v1/item_summary/search",
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
                    "source": "EBAY",
                    "label": "eBay UK active · official Browse",
                    "endpoint": "GET /buy/browse/v1/item_summary/search",
                    "status": "FAILED",
                    "result_count": 0,
                    "keys": [],
                    "list_counts": {},
                    "samples": [],
                    "error": {"detail": "Official eBay probe failed validation"},
                }
            )
    else:
        results.append(
            {
                "source": "EBAY",
                "label": "eBay UK active · official Browse",
                "endpoint": "GET /buy/browse/v1/item_summary/search",
                "status": "NOT_CONFIGURED",
                "result_count": 0,
                "keys": [],
                "list_counts": {},
                "samples": [],
                "error": {"detail": "Official eBay production credentials are not configured"},
            }
        )

    results.append(
        {
            "source": "EBAY",
            "label": "eBay UK sold history",
            "endpoint": "Marketplace Insights",
            "status": "RESTRICTED",
            "result_count": 0,
            "keys": [],
            "list_counts": {},
            "samples": [],
            "error": {
                "detail": "Sold history is not inferred from Browse. Marketplace Insights access must be granted separately by eBay."
            },
        }
    )

    if settings.parse_api_key:
        client = ParseHttpClient(api_key=settings.parse_api_key, timeout_seconds=20.0)
        for probe in SUPPORTING_PROBES:
            try:
                data = await client.get(
                    scraper_id=probe["scraper_id"],
                    endpoint=probe["endpoint"],
                    snapshot_version=None,
                    params=probe["params"],
                )
                summary = _summarise_payload(data, result_key=probe["result_key"])
                result_count = int(summary["result_count"])
                results.append(
                    {
                        "source": probe["source"],
                        "label": probe["label"],
                        "endpoint": probe["endpoint"],
                        "status": "SUCCEEDED" if result_count > 0 else "EMPTY",
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
    else:
        for probe in SUPPORTING_PROBES:
            results.append(
                {
                    "source": probe["source"],
                    "label": probe["label"],
                    "endpoint": probe["endpoint"],
                    "status": "NOT_CONFIGURED",
                    "result_count": 0,
                    "keys": [],
                    "list_counts": {},
                    "samples": [],
                    "error": {"detail": "Parse provider access is not configured"},
                }
            )

    return jsonable_encoder({"persisted": False, "probe_count": len(results), "results": results})
