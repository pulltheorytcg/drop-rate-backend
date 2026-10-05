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

    results = []
    for target in TARGETS:
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
        "results": results,
    }


if __name__ == "__main__":
    print(
        PREFIX + json.dumps(asyncio.run(run()), sort_keys=True, separators=(",", ":")),
        flush=True,
    )
