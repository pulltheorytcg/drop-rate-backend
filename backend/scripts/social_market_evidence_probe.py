"""One-off read-only market evidence probe for approved Drop Rate social content."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from app.ebay_sold_pricing import TrawlApiError, TrawlEbaySoldClient
from app.fx import EcbHistoricalFxProvider
from app.social_market_evidence import (
    TARGETS,
    select_newest_exact_comps,
    summarise_exact_market,
)


PREFIX = "DROP_RATE_SOCIAL_MARKET_EVIDENCE "


async def run() -> dict:
    key = os.environ.get("TCG_TRAWL_API_KEY", "").strip()
    if not key:
        return {
            "probe_version": "social-market-evidence-v1",
            "status": "BLOCKED",
            "reason": "TRAWL_RUNTIME_CREDENTIAL_MISSING",
            "results": [],
        }

    client = TrawlEbaySoldClient(api_key=key)
    fx_provider = EcbHistoricalFxProvider()
    now = datetime.now(timezone.utc)
    quote = await fx_provider.quote(
        base_currency="USD",
        quote_currency="GBP",
        at=now,
    )
    quote.validate()

    requested = {
        item.strip()
        for item in os.environ.get("DROP_RATE_SOCIAL_MARKET_TARGETS", "").split(",")
        if item.strip()
    }
    selected_targets = [
        target for target in TARGETS if not requested or target.key in requested
    ]
    unknown = requested.difference({target.key for target in TARGETS})
    if unknown:
        return {
            "probe_version": "social-market-evidence-v1",
            "status": "BLOCKED",
            "reason": "UNKNOWN_TARGET_FILTER",
            "results": [],
        }

    results = []
    for target in selected_targets:
        try:
            raw = await client.sold(query=target.query, max_pages=1)
            comps = select_newest_exact_comps(raw, target=target, limit=5)
            results.append(
                summarise_exact_market(
                    target,
                    comps,
                    usd_to_gbp_rate=quote.rate,
                    fx_effective_at=quote.effective_at,
                    fx_retrieved_at=quote.retrieved_at,
                )
            )
        except TrawlApiError as exc:
            results.append(
                {
                    "target": target.key,
                    "display_name": target.display_name,
                    "status": "PROVIDER_ERROR",
                    "reason": exc.detail,
                    "provider_status_code": exc.status_code,
                    "retryable": exc.retryable,
                }
            )
        except (RuntimeError, ValueError):
            results.append(
                {
                    "target": target.key,
                    "display_name": target.display_name,
                    "status": "VALIDATION_ERROR",
                    "reason": "Provider or FX evidence failed validation",
                }
            )

    return {
        "probe_version": "social-market-evidence-v1",
        "status": "COMPLETE",
        "evidence_only": True,
        "persisted": False,
        "requested_targets": [target.key for target in selected_targets],
        "results": results,
    }


if __name__ == "__main__":
    result = asyncio.run(run())
    # Railway may elide a very large single log line. Emit one bounded target line
    # so every evidence bucket remains independently readable/auditable.
    print(
        PREFIX + json.dumps(
            {
                "probe_version": result.get("probe_version"),
                "status": result.get("status"),
                "evidence_only": result.get("evidence_only"),
                "persisted": result.get("persisted"),
                "result_count": len(result.get("results") or []),
                "requested_targets": result.get("requested_targets"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    for item in result.get("results") or []:
        compact = {
            "target": item.get("target"),
            "display_name": item.get("display_name"),
            "status": item.get("status"),
            "reason": item.get("reason"),
            "query": item.get("query"),
            "comparable_count": item.get("comparable_count"),
            "market_value_gbp_minor": item.get("market_value_gbp_minor"),
            "market_value_usd_minor": item.get("market_value_usd_minor"),
            "fx": item.get("fx"),
            "comps": [
                {
                    "item_id": comp.get("item_id"),
                    "sold_at": comp.get("sold_at"),
                    "price_gbp_minor": comp.get("price_gbp_minor"),
                    "shipping_gbp_minor": comp.get("shipping_gbp_minor"),
                    "title": comp.get("title"),
                }
                for comp in (item.get("comps") or [])
            ],
        }
        print(
            "DROP_RATE_SOCIAL_MARKET_TARGET "
            + json.dumps(compact, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
