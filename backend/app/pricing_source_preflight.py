"""Manual, read-only CardTrader pricing source preflight.

This is intentionally NOT the scheduled catalogue refresher and cannot apply
prices or bypass the production operator bulk hold. It establishes whether
fresh, exact-printing, 3-independent-seller evidence is available *before*
any controlled catalogue pricing release. It reuses the existing deterministic
CardTrader adapter and its original marketplace permissions.
"""
from __future__ import annotations

from collections.abc import Mapping

from .cardtrader_bulk_guides import refresh_cardtrader_expansion_guides

MAX_PREFLIGHT_EXPANSIONS = 2


def compact_preflight_report(report: Mapping) -> dict:
    """Return only aggregate evidence; no seller identities, tokens or raw API."""
    if not isinstance(report, Mapping):
        raise ValueError("Invalid pricing source report")
    if report.get("dry_run") is not True:
        raise ValueError("Price-source preflight must remain read-only")
    if report.get("writes_attempted", 0) != 0 or report.get("writes_applied", 0) != 0:
        raise ValueError("Source preflight attempted to alter prices")
    if report.get("inventory_writes", 0) != 0 or report.get("store_price_writes", 0) != 0:
        raise ValueError("Source preflight attempted to alter inventory/Shopify prices")
    details = report.get("by_release") or {}
    if not isinstance(details, Mapping) or len(details) > MAX_PREFLIGHT_EXPANSIONS:
        raise ValueError("Unbounded pricing source report")
    safe = {
        "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
        "source": "CARDTRADER_EXPANSION_ASKING",
        "evidence_kind": "ACTIVE_ASKING_NOT_SOLD",
        "mode": "DRY_RUN",
        "requests": int(report.get("provider_calls", 0)),
        "expansions": int(report.get("sets_checked", 0)),
        "canonical_references_examined": int(report.get("references_examined", 0)),
        "exact_printings": int(report.get("exact_printings", 0)),
        "eligible_quotes": int(report.get("eligible_quotes", 0)),
        "provider_failures": int(report.get("provider_failures", 0)),
        "failure_class": (
            report.get("reason") if report.get("reason") in {
                "CardTraderApiError", "ValueError", "TypeError", "KeyError", "RuntimeError"
            } else None
        ),
        "inventory_writes": 0,
        "store_price_writes": 0,
        "catalogue_price_writes": 0,
        "by_release": [],
    }
    for release_id, row in details.items():
        if not isinstance(row, Mapping):
            continue
        safe["by_release"].append({
            "release": str(release_id)[:64],
            "references": int(row.get("references", 0)),
            "missing_before": int(row.get("missing_before", 0)),
            "exact_printings": int(row.get("matched", 0)),
            "blueprints_with_offers": int(row.get("blueprints_with_offers", 0)),
            "candidate_source_offers": int(row.get("candidate_source_offers", 0)),
            "three_seller_candidates": int(row.get("with_three_matching_sellers", 0)),
            "qualified_quotes": int(row.get("quotes", 0)),
            "provider_failed": bool(row.get("error_type")),
            "failure_class": (
                row.get("error_type") if row.get("error_type") in {
                    "CardTraderApiError", "ValueError", "TypeError", "KeyError", "RuntimeError"
                } else None
            ),
            "http_status": (
                row.get("http_status")
                if type(row.get("http_status")) is int
                and 400 <= row["http_status"] <= 599
                else None
            ),
        })
    return safe


async def preview_cardtrader_expansions(pool, actor, fx, client, *,
                                        expansion_limit=1, previous_cursor=None,
                                        refresh=refresh_cardtrader_expansion_guides):
    if type(expansion_limit) is not int or not 1 <= expansion_limit <= MAX_PREFLIGHT_EXPANSIONS:
        raise ValueError("Preflight allows only 1 or 2 expansions")
    if previous_cursor is not None and (
        not isinstance(previous_cursor, str) or len(previous_cursor) > 128
        or not previous_cursor.isprintable()
    ):
        raise ValueError("Invalid prior cursor")
    report = await refresh(
        pool, actor, fx, client, dry_run=True,
        expansion_limit=expansion_limit,
        previous_cursor=previous_cursor,
    )
    result = compact_preflight_report(report)
    result["requested_expansions"] = expansion_limit
    result["cursor_moved"] = report.get("cursor") != previous_cursor
    return result
