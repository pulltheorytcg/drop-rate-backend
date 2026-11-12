"""Coverage work queue across legacy SQL printings and R2-first catalogues.

Plan-only. This does not create fabricated values, copy R2 objects, or run
unlicensed provider calls. Every published source/game has an explicit row.
"""
from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_business_founder
from .auth import AuthenticatedUser, require_user
from .catalogue_coverage import shared_price_coverage
from .db import user_connection

router = APIRouter(prefix="/api/v1/pricing", tags=["market-coverage"])

def _count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0

def _kind(system: str) -> str:
    return {
        "POKEMON_TCG": "Pokémon",
        "ONE_PIECE_CARD_GAME": "One Piece",
        "DRAGON_BALL_SUPER_MASTERS": "Dragon Ball Masters",
        "DRAGON_BALL_SUPER_FUSION_WORLD": "Dragon Ball Fusion World",
        "NARUTO_KAYOU": "Naruto Kayou",
        "NARUTO_BANDAI_LEGACY": "Naruto Legacy",
    }.get(system, system)

def build_market_coverage_work_queue(coverage: dict[str, Any]) -> dict[str, Any]:
    """Make an exhaustive and evidence-honest per-source backlog.

    SQL priced reference counts can include guides; they are never upgraded
    to sold-verified UK value coverage. R2 metadata lacks market-value counts,
    so an unmeasured item is NOT automatically counted as missing or priced.
    """
    summary = coverage.get("summary") or {}
    context = coverage.get("catalogue") or {}
    rows: list[dict[str, Any]] = []
    legacy_totals = Counter()
    for src in summary.get("by_game") or []:
        if not isinstance(src, dict) or src.get("kind") != "CARD":
            continue
        statuses = src.get("status_counts") or {}
        if not isinstance(statuses, dict):
            continue
        digital = _count(statuses.get("NOT_APPLICABLE_DIGITAL"))
        total = max(0, _count(src.get("total")) - digital)
        if not total:
            continue
        priced = min(total, _count(src.get("priced")))
        missing = total - priced
        legacy_totals["tracked"] += total
        legacy_totals["guide_inclusive_current"] += priced
        legacy_totals["missing_reference_evidence"] += missing
        reason = sorted(
            ((code, _count(n)) for code, n in statuses.items()
             if code not in {"REFERENCE_AVAILABLE","NOT_APPLICABLE_DIGITAL"}
             and _count(n)>0),
            key=lambda pair: (-pair[1], pair[0]),
        )
        rows.append({
            "catalogue_tier": "SQL_LEGACY",
            "game": _kind(str(src.get("system_code") or "")),
            "system_code": src.get("system_code"),
            "language": src.get("language"),
            "reference_count": total,
            "current_reference_prices": priced,
            "reference_prices_missing": missing,
            "market_value_coverage": "UK_SOLD_NOT_MEASURED",
            "priority": "HIGH" if missing else "EVIDENCE_REVIEW",
            "largest_blocker": reason[0][0] if reason else None,
            "largest_blocker_count": reason[0][1] if reason else 0,
            "next_action": "Acquire permitted recent UK paid-sale evidence for exact printing/condition/grade",
            "market_value_must_be_sold_backed": True,
        })

    r2_totals = Counter()
    seen = set()
    for src in context.get("published_sources") or []:
        if not isinstance(src, dict):
            continue
        system = str(src.get("system_code") or "")
        language = str(src.get("language") or "")
        provider = str(src.get("provider") or "")
        identity = (provider,system,language)
        if identity in seen:
            raise ValueError("Duplicate published R2 first-partition metadata")
        seen.add(identity)
        count = _count(src.get("stored_references"))
        if not count:
            continue
        r2_totals["tracked"] += count
        r2_totals["partitions"] += 1
        rows.append({
            "catalogue_tier": "R2_FIRST",
            "game": src.get("game") or system,
            "system_code": system,
            "language": language,
            "provider": provider,
            "category": src.get("category", "OTHER"),
            "reference_count": count,
            "current_reference_prices": None,
            "reference_prices_missing": None,
            "market_value_coverage": "NOT_MEASURED",
            "priority": "SOURCE_ACCESS_REQUIRED",
            "largest_blocker": "NO_APPROVED_EXACT_PRICE_FEED",
            "largest_blocker_count": None,
            "next_action": "Verify exact source/printing, then obtain permitted UK paid sales; no RRP or asking-price fallback",
            "market_value_must_be_sold_backed": True,
        })
    for source in context.get("unpublished_tcg_games") or []:
        if not isinstance(source, dict):
            continue
        rows.append({
            "catalogue_tier": "UNPUBLISHED",
            "game": source.get("game"),
            "system_code": source.get("system_code"),
            "language": None,
            "reference_count": None,
            "current_reference_prices": None,
            "reference_prices_missing": None,
            "market_value_coverage": "CATALOGUE_NOT_PUBLISHED",
            "priority": "CATALOGUE_IMPORT_REQUIRED",
            "largest_blocker": "NOT_PUBLISHED",
            "largest_blocker_count": None,
            "next_action": "Publish a permitted canonical catalogue before acquiring valuations",
            "market_value_must_be_sold_backed": True,
        })
    severity = {"HIGH":0,"SOURCE_ACCESS_REQUIRED":1,"CATALOGUE_IMPORT_REQUIRED":2,"EVIDENCE_REVIEW":3}
    rows.sort(key=lambda x:(severity.get(x["priority"],4),
                            -(_count(x["reference_prices_missing"])
                              or _count(x["reference_count"])),
                            str(x["game"]),str(x["language"])))
    return {
        "scope": "GLOBAL_CANONICAL_REFERENCE_PRINTINGS_NOT_OWNED_ITEMS",
        "price_definition": "ACTUAL_UK_COMPLETED_SALES_ONLY",
        "no_guessed_values": True,
        "no_asking_as_market_value": True,
        "total_stored_references": context.get("stored_physical_tcg_references"),
        "reference_count_includes_unreleased_printings": True,
        "legacy_sql": {
            "references": legacy_totals["tracked"],
            "guide_inclusive_current_reference_prices": legacy_totals["guide_inclusive_current"],
            "missing_or_ineligible_reference_prices": legacy_totals["missing_reference_evidence"],
            "verified_uk_sold_coverage": None,
        },
        "r2_first": {
            "stored_references_including_other_collectibles": r2_totals["tracked"],
            "published_partitions": r2_totals["partitions"],
            "market_value_coverage": "NOT_MEASURED",
        },
        "groups": rows,
        "groups_count": len(rows),
        "status": "SOURCE_ACCESS_REQUIRED",
        "notice": ("Coverage of official source metadata or price guides is NOT completed-sale "
                   "Market Value coverage. R2-first prices are unmeasured; never treat them "
                   "as zero or current prices. Existing FastAPI engine stays authoritative."),
    }


@router.get("/coverage-work-queue")
async def market_value_coverage_queue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,user.user_id,request.state.request_id,
        readonly_snapshot=True,
    ) as connection:
        await require_business_founder(connection)
    # Reuses the existing coalesced (2-minute) SQL+R2 publication report.
    # No whole-catalogue R2 object hydration; no additional expensive scan.
    existing = await shared_price_coverage(
        request.app.state.db_pool,user.user_id,request.state.request_id
    )
    return jsonable_encoder(build_market_coverage_work_queue(existing))
