"""Bounded union of new R2 starter references and existing collectible records.

Sports/figures are partial, modest-sized reference collections, unlike the
large TCG partitions. Publishing a starter must not replace the verified SQL
references or hide a collector's existing items. This explicit 5,000-row bound
fails closed rather than silently truncating either side. Larger coverage will
need a separately reviewed cursor merge, not an increased unchecked limit.
"""
from __future__ import annotations

from fastapi import HTTPException

from . import catalogue_r2_live, r2_first_service

MAX_MERGED_ROWS = 5_000
SYSTEM_CATEGORIES = {"SPORTS_CARDS": "SPORTS", "FIGURES": "FIGURES"}


async def browse_collectibles(connection, *, owner_id, q="", system_code="", language="",
                             category="", set_id="", provider=None, product_type="",
                             owned="all", sort="name", limit=40, offset=0,
                             slab_number="", slab_name="", slab_set=""):
    from . import catalogue_browser as browser
    from .catalogue_collectibles import with_collectible_details

    expected_category = SYSTEM_CATEGORIES.get(system_code)
    if expected_category is None or category not in ("", expected_category):
        return {"items": [], "has_more": False, "total_count": 0, "offset": offset}
    if offset > MAX_MERGED_ROWS:
        raise HTTPException(422, "Choose a set or narrow the collectible search")
    reference_rows = []
    if owned != "owned":
        references = await r2_first_service.browse(connection, owner_id=owner_id,
            q=q, system_code=system_code, language=language, category=expected_category,
            set_id=set_id, provider=provider, product_type=product_type, owned=owned,
            sort=sort, limit=MAX_MERGED_ROWS + 1, offset=0)
        if references["has_more"] or len(references["items"]) > MAX_MERGED_ROWS:
            raise HTTPException(422, "Choose a set or narrow the collectible search")
        reference_rows = references["items"]
    # The existing owner-authorized SQL path retains its RLS, physical values,
    # released-only filters and canonical identity rules. No SQL writes occur.
    query, params = browser.product_query(owner_id=owner_id, q=q, system_code=system_code,
        language=language, category=expected_category, set_id=set_id, provider=provider,
        product_type=product_type, owned=owned, sort=sort, limit=MAX_MERGED_ROWS, offset=0)
    live = await catalogue_r2_live.read(connection)
    canonical = [dict(row) for row in await catalogue_r2_live.fetch(connection, query, params, live)]
    if len(canonical) + len(reference_rows) > MAX_MERGED_ROWS:
        raise HTTPException(422, "Choose a set or narrow the collectible search")
    merged = browser._sort_explicit_reference_rows([*canonical, *reference_rows], sort=sort, q=q)
    page = merged[offset:offset + limit]
    # Only enrich the visible canonical page. The legacy enrichment intentionally
    # removes unchecked embedded details, so don't feed the R2 partial forms to it.
    canonical_page = [row for row in page if not row["key"].startswith("x:")]
    enriched = {row["key"]: row for row in await with_collectible_details(connection, canonical_page)}
    output = [enriched.get(row["key"], row) for row in page]
    slab_search = bool(slab_number or slab_name or slab_set)
    if slab_search:
        output = [row for row in output if browser.slab_candidate_supported(
            row, card_name=slab_name, card_number=slab_number, set_name=slab_set)]
    return {"items": [browser.with_artwork_path(browser.with_signed_mirror(row)) for row in output],
        "has_more": offset + limit < len(merged), "total_count": len(merged), "offset": offset,
        "catalogue_scope": "R2_REFERENCE_PLUS_CANONICAL", "includes_r2_metadata": bool(reference_rows),
        "coverage": "PARTIAL_REFERENCE_CATALOGUE", "slab_review_required": slab_search,
        "slab_search_bounded": slab_search and offset + limit < len(merged)}


async def sets_collectibles(connection, *, owner_id, system_code, language="", q="", limit=40, offset=0):
    """Keep existing canonical sets alongside the small published starter sets."""
    from . import catalogue_browser as browser
    if system_code not in SYSTEM_CATEGORIES:
        return {"items": [], "has_more": False, "total_count": 0, "offset": offset}
    if offset > MAX_MERGED_ROWS:
        raise HTTPException(422, "Narrow the collectible set search")
    reference_page = await r2_first_service.sets(connection, owner_id=owner_id,
        system_code=system_code, language=language, q=q, limit=MAX_MERGED_ROWS + 1, offset=0)
    live = await catalogue_r2_live.read(connection)
    canonical = await catalogue_r2_live.fetch(connection, browser.SETS_SQL,
        [owner_id, [system_code], language, q, MAX_MERGED_ROWS + 1, 0], live)
    if reference_page["has_more"] or len(reference_page["items"]) + len(canonical) > MAX_MERGED_ROWS:
        raise HTTPException(422, "Narrow the collectible set search")
    # Provider/system/language/set identity is exact; names alone never merge.
    unique = {}
    for row in [*canonical, *reference_page["items"]]:
        identity = tuple(row.get(field) for field in ("provider", "system_code", "language", "set_id"))
        unique[identity] = dict(row)
    rows = sorted(unique.values(), key=lambda row: (
        str(row.get("set_name") or row.get("name") or "").casefold(),
        str(row.get("provider") or ""), str(row.get("language") or ""), str(row.get("set_id") or "")))
    return {"items": [browser.set_metadata_only(row) for row in rows[offset:offset+limit]],
        "has_more": offset + limit < len(rows), "offset": offset, "total_count": len(rows),
        "catalogue_scope": "R2_REFERENCE_PLUS_CANONICAL", "coverage": "PARTIAL_REFERENCE_CATALOGUE"}
