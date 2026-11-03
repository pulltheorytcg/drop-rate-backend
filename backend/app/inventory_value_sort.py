"""Sort the complete owned selection using its actual displayed reference values.

This path reads persisted evidence only. It never prices stock, calls providers,
or caches private collection data. Enrichment precedes group pagination and its
same snapshot is reused in the returned page, so the ordering and labels agree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException

from .inventory_display_groups import display_key_sql
from .inventory_reference_values import add_shared_reference_values


MAX_VALUE_SORT_COPIES = 10_000
CURRENT_DISPLAY_STATUSES = {"AVAILABLE", "REFERENCE_ESTIMATE", "CATALOGUE_GUIDE", "CONDITION_REFERENCE"}
VALUE_FIELDS = ("reference_value", "catalogue_reference", "market_value_minor",
                "recommended_retail_minor", "pricing_updated_at", "pricing_method", "pricing_limitation")
COPY_BASIS_FIELDS = ("version", "catalogue_id", "product_type", "language", "catalogue_language",
                    "condition", "seal_status", "grading_company", "grade", "status")


def displayed_reference(item):
    reference = item.get("reference_value") or {}
    return reference if reference.get("status") in {"AVAILABLE", "REFERENCE_ESTIMATE"} else item.get("catalogue_reference") or reference


def displayed_value_minor(item):
    """Match reference-value-display.js, including explicitly labelled history."""
    reference = displayed_reference(item)
    if not reference:
        value = item.get("market_value_minor")
        return value if type(value) is int else None
    value = reference.get("market_value_minor")
    if reference.get("status") in CURRENT_DISPLAY_STATUSES and type(value) is int:
        return value
    historical = reference.get("last_known_minor")
    checked = reference.get("checked_at")
    if type(historical) is int and checked:
        if isinstance(checked, datetime):
            return historical
        try:
            datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            return historical
        except ValueError:
            pass
    return None


def _display_rank(item):
    """Use the same representative preference as inventory-groups.js."""
    reference = displayed_reference(item)
    if type(reference.get("market_value_minor")) is int:
        return 4 if reference.get("status") == "AVAILABLE" else 3
    if not reference and type(item.get("market_value_minor")) is int:
        return 4
    return 1 if type(reference.get("last_known_minor")) is int else 0


@dataclass
class ValueSortedPage:
    total: int
    copy_total: int
    ids: list
    snapshots: dict

    def apply(self, items):
        """Reject a concurrent physical edit instead of displaying mismatched values."""
        if {str(item["id"]) for item in items} != set(self.snapshots):
            raise HTTPException(409, "Your collection changed while sorting. Refresh to load current values.")
        for item in items:
            snapshot = self.snapshots[str(item["id"])]
            if any(item.get(key) != snapshot.get(key) for key in COPY_BASIS_FIELDS):
                raise HTTPException(409, "An item changed while sorting. Refresh to load current values.")
            for field in VALUE_FIELDS:
                if field in snapshot:
                    item[field] = snapshot[field]
                else:
                    item.pop(field, None)


async def inventory_value_page(connection, where, params, limit, offset, *, grouped, descending):
    # The cap is explicit, never a partial ranking. Filtering first lets large
    # accounts narrow a selection without loading media for every owned item.
    rows = await connection.fetch(f"""
      select i.id,i.inventory_code,i.catalogue_id,i.version,i.status,
        i.condition,i.seal_status,i.grading_company,i.grade,
        coalesce(i.language,p.language) as language,p.language as catalogue_language,
        p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
        ({display_key_sql()})::text as display_key
      from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
      where {where}
      order by i.updated_at desc,i.inventory_code
      limit ${len(params)+1}
    """, *params, MAX_VALUE_SORT_COPIES + 1)
    if len(rows) > MAX_VALUE_SORT_COPIES:
        raise HTTPException(422, f"Value sorting supports up to {MAX_VALUE_SORT_COPIES:,} matching copies. Choose a category, game or other filter to narrow your collection.")
    items = await add_shared_reference_values(connection, [dict(row) for row in rows])
    groups = {}
    for item in items:
        key = item["display_key"] if grouped else str(item["id"])
        groups.setdefault(key, []).append(item)

    def order(copies):
        displayed = max(copies, key=_display_rank)
        value = displayed_value_minor(displayed)
        tie = min((str(copy.get("inventory_code") or ""), str(copy["id"])) for copy in copies)
        return (value is None, -value if value is not None and descending else value or 0, tie)

    ordered = sorted(groups.values(), key=order)
    page = [item for copies in ordered[offset:offset + limit] for item in copies]
    return ValueSortedPage(len(groups), len(items), [item["id"] for item in page],
                           {str(item["id"]): item for item in page})
