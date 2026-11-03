"""Reviewed sports/figure facts for a bounded catalogue page."""
from __future__ import annotations

import json
from uuid import UUID

from pydantic import ValidationError

from .manual_collectible_identity import FigureDetailsCreate, SportsCardCreate


MAX_PAGE_REFERENCES = 81  # The browser's maximum page plus its has-more row.
DETAIL_TYPES = {
    ("SPORTS_CARDS", "CARD"): ("sports_card", SportsCardCreate),
    ("FIGURES", "FIGURE"): ("figure_details", FigureDetailsCreate),
}


async def with_collectible_details(connection, rows):
    """Return allowlisted edition facts, never submission or source metadata.

    This is a separate bounded page read: private attributes never enter the
    shared R2 projection. Legacy pages do not issue an additional query.
    """
    items = [dict(row) for row in rows]
    eligible = []
    for item in items:
        # Never preserve an unchecked embedded object from an upstream source.
        item.pop("sports_card", None)
        item.pop("figure_details", None)
        if (item.get("system_code"), item.get("product_type")) not in DETAIL_TYPES:
            continue
        try:
            catalogue_id = UUID(str(item.get("catalogue_id")))
        except (ValueError, TypeError, AttributeError):
            continue
        eligible.append((item, catalogue_id))
    if not eligible:
        return items
    ids = sorted({catalogue_id for _, catalogue_id in eligible}, key=str)
    if len(ids) > MAX_PAGE_REFERENCES:
        raise ValueError("Collectible details require a bounded catalogue page")
    records = await connection.fetch("""
        select pr.catalogue_id,pr.system_code,pr.collectible_type,pr.identity_status,
               pr.attributes->'sports_card' as sports_card,
               pr.attributes->'figure_details' as figure_details
        from tcg.catalogue_product_profiles pr
        join tcg.catalogue_products p on p.id=pr.catalogue_id and p.product_type=pr.collectible_type
        where pr.catalogue_id=any($1::uuid[]) and pr.identity_status='VERIFIED'
          and ((pr.system_code='SPORTS_CARDS' and pr.collectible_type='CARD')
            or (pr.system_code='FIGURES' and pr.collectible_type='FIGURE'))
        """, ids)
    by_id = {str(row["catalogue_id"]): dict(row) for row in records}
    for item, catalogue_id in eligible:
        row = by_id.get(str(catalogue_id))
        expected = (item["system_code"], item["product_type"])
        if (not row or row.get("identity_status") != "VERIFIED"
                or (row.get("system_code"), row.get("collectible_type")) != expected):
            continue
        field, model = DETAIL_TYPES[expected]
        source = row.get(field)
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except json.JSONDecodeError:
                continue
        if not isinstance(source, dict):
            continue
        try:
            details = model.model_validate({key: source[key] for key in model.model_fields if key in source})
        except ValidationError:
            continue
        item[field] = details.model_dump(mode="json")
    return items
