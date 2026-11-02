"""Read-only, conservative planning for additional canonical card references.

This is an advisory projection, NEVER an import authorization. The existing
database-capacity guard and source/rights/ownership checks still run at apply.
"""
from __future__ import annotations

from dataclasses import dataclass

from .database_capacity import (
    FREE_DATABASE_LIMIT_BYTES,
    REFRESH_PAUSE_BYTES,
)


@dataclass(frozen=True)
class CardReferenceFootprint:
    database_bytes: int
    reference_card_rows: int
    reference_card_table_bytes: int


def forecast_card_reference_growth(
    footprint: CardReferenceFootprint,
    *,
    proposed_reference_cards: int,
) -> dict:
    """Project reference_cards heap/TOAST/index growth with a 50% cushion.

    The historical per-row average is only a heuristic: source-specific JSON,
    index page splits, new sets and related tables can materially change it.
    Consequently even a below-guard result is never marked import-approved.
    """
    for label, value in (
        ("database_bytes", footprint.database_bytes),
        ("reference_card_rows", footprint.reference_card_rows),
        ("reference_card_table_bytes", footprint.reference_card_table_bytes),
        ("proposed_reference_cards", proposed_reference_cards),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")
    if footprint.reference_card_rows < 1000 or footprint.reference_card_table_bytes <= 0:
        raise ValueError("Insufficient existing reference-card footprint for a forecast")
    if footprint.reference_card_table_bytes > footprint.database_bytes:
        raise ValueError("Reference-card relation cannot exceed the database size")

    # Ceiling integer arithmetic makes the observed average explicit and
    # avoids machine-dependent floating-point rounding.
    observed_bytes_per_card = (
        footprint.reference_card_table_bytes + footprint.reference_card_rows - 1
    ) // footprint.reference_card_rows
    baseline_growth_bytes = observed_bytes_per_card * proposed_reference_cards
    planning_growth_bytes = (baseline_growth_bytes * 3 + 1) // 2
    projected_database_bytes = footprint.database_bytes + planning_growth_bytes
    if footprint.database_bytes >= REFRESH_PAUSE_BYTES:
        status = "BLOCKED_BY_CURRENT_IMPORT_GUARD"
    elif proposed_reference_cards == 0:
        status = "NO_IMPORT_REQUESTED"
    elif projected_database_bytes >= REFRESH_PAUSE_BYTES:
        status = "BLOCKED_BY_PROJECTED_IMPORT_GUARD"
    else:
        status = "REVIEW_ONLY_NOT_IMPORT_AUTHORIZATION"

    return {
        "status": status,
        "database_bytes": footprint.database_bytes,
        "reference_card_rows": footprint.reference_card_rows,
        "reference_card_table_bytes": footprint.reference_card_table_bytes,
        "observed_bytes_per_card": observed_bytes_per_card,
        "proposed_reference_cards": proposed_reference_cards,
        "baseline_growth_bytes": baseline_growth_bytes,
        "planning_cushion_percent": 50,
        "planning_growth_bytes": planning_growth_bytes,
        "projected_database_bytes": projected_database_bytes,
        "import_pause_bytes": REFRESH_PAUSE_BYTES,
        "free_database_limit_bytes": FREE_DATABASE_LIMIT_BYTES,
        "remaining_free_database_bytes_now": max(
            0, FREE_DATABASE_LIMIT_BYTES - footprint.database_bytes
        ),
        "includes": "reference_cards table, indexes and TOAST only",
        "excludes": [
            "reference_sets and source-specific detail tables",
            "market observations and price evidence",
            "audit events, ancillary indexes and database maintenance growth",
            "physical inventory and owner records",
        ],
        "authorizes_import": False,
    }
