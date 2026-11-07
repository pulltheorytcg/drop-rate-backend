"""Owner-scoped collection filters. All selections apply before pagination."""
from __future__ import annotations

from typing import Literal

CollectionCategory = Literal["", "TCG", "SPORTS", "COMICS", "MANGA", "FIGURES"]
CollectionFormat = Literal["", "CARD", "SEALED"]
CollectionGrading = Literal["", "RAW", "GRADED"]
CollectionSort = Literal["updated", "newest", "oldest", "name", "name_desc", "value_desc", "value_asc"]
ListingState = Literal["", "PERSONAL", "ALL_FOR_SALE", "PREPARING", "REVIEW", "READY", "LISTED"]
ACTIVE_COLLECTION_SQL = "i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')"

# Category and physical format are separate. Future configured sports/figure
# systems can use the same filter; a sealed product remains within its category.
COLLECTION_CATEGORY_SQL = """case
 when p.product_type='FIGURE' then 'FIGURES'
 when exists(select 1 from tcg.catalogue_product_profiles cp
   join tcg.collectible_systems cs on cs.code=cp.system_code
   where cp.catalogue_id=p.id and cs.system_kind='SPORTS_CARD') then 'SPORTS'
 when p.product_type='COMIC' and (lower(btrim(p.game))='manga'
   or exists(select 1 from tcg.catalogue_product_profiles cp
     where cp.catalogue_id=p.id and cp.system_code='MANGA')) then 'MANGA'
 when p.product_type='COMIC' then 'COMICS'
 when p.product_type in ('CARD','SEALED','COLLECTION') then 'TCG'
 else '' end"""

PUBLISHED_SQL = """exists(select 1 from tcg.shopify_inventory_links sl
 where sl.inventory_id=i.id and sl.owner_id=i.owner_id and not sl.test_mode
   and sl.sync_state='PUBLISHED')"""
GRADED_SQL = """(nullif(btrim(i.grading_company),'') is not null
 or nullif(btrim(i.grade),'') is not null
 or nullif(btrim(i.certificate_number),'') is not null)"""
COLLECTION_NAME_SQL = """case when p.product_type in ('SEALED','COLLECTION')
 then coalesce((select nullif(named_sealed.attributes->>'display_name_en','')
   from tcg.sealed_product_details named_sealed where named_sealed.catalogue_id=p.id),p.name)
 else p.name end"""


def append_collection_filters(filters: list[str], params: list, *, category="", game="",
                              language="", grading="", format="", listing_state="",
                              prepare_selling=False):
    """Extend the endpoint's explicit owner filter without interpolating input."""
    def bound(expression, value):
        params.append(value)
        filters.append(f"{expression}=${len(params)}")

    if category:
        bound(f"({COLLECTION_CATEGORY_SQL})", category)
    if game:
        bound("p.game", game.strip())
    if language:
        bound("coalesce(nullif(btrim(i.language),''),p.language,'')", language.strip())
    if grading:
        filters.append(GRADED_SQL if grading == "GRADED" else f"not {GRADED_SQL}")
    if format:
        filters.append("p.product_type in ('SEALED','COLLECTION')" if format == "SEALED"
                       else "p.product_type='CARD'")
    if prepare_selling:
        filters.append("i.status in ('DRAFT','INSPECTION','APPROVED')")
    if listing_state == "PERSONAL":
        filters.append("i.sale_intent='PERSONAL_COLLECTION' and i.status in ('DRAFT','INSPECTION','APPROVED')")
    elif listing_state == "ALL_FOR_SALE":
        filters.append("i.sale_intent='FOR_SALE' and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')")
    elif listing_state == "LISTED":
        filters.append(PUBLISHED_SQL)
    elif listing_state in {"PREPARING", "REVIEW", "READY"}:
        filters.append("i.sale_intent='FOR_SALE'")
        bound("i.status", {"PREPARING": "DRAFT", "REVIEW": "INSPECTION", "READY": "APPROVED"}[listing_state])
        filters.append(f"not {PUBLISHED_SQL}")


def collection_order_sql(sort: str = "updated", *, grouped=False) -> str:
    """Return an allowlisted ordering, never a user-provided SQL fragment.

    Value sorting uses inventory_value_page instead: stale physical money
    columns cannot represent the enriched values actually displayed.
    """
    if grouped:
        choices = {"updated": "updated_at desc,first_code", "newest": "created_at desc,first_code",
                   "oldest": "created_at,first_code", "name": "sort_name,first_code",
                   "name_desc": "sort_name desc,first_code"}
    else:
        choices = {"updated": "i.updated_at desc,i.inventory_code", "newest": "i.created_at desc,i.inventory_code",
                   "oldest": "i.created_at,i.inventory_code", "name": f"lower({COLLECTION_NAME_SQL}),i.inventory_code",
                   "name_desc": f"lower({COLLECTION_NAME_SQL}) desc,i.inventory_code"}
    return choices.get(sort, choices["updated"])


async def collection_facets(connection, owner_id):
    """Only this owner's available facets, across all pages of the collection."""
    rows = await connection.fetch(f"""
      select distinct ({COLLECTION_CATEGORY_SQL}) as category,p.game,
        coalesce(nullif(btrim(i.language),''),p.language,'') as language
      from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
      where i.owner_id=$1 and {ACTIVE_COLLECTION_SQL}
      order by category,p.game,language
    """, owner_id)
    return {"categories": sorted({r["category"] for r in rows if r["category"]}),
            "games": sorted({r["game"] for r in rows if r["game"]}),
            "languages": sorted({r["language"] for r in rows if r["language"]}),
            "combinations": [dict(r) for r in rows]}


async def collection_state_counts(connection, owner_id):
    """Actionable overview totals use the identical collection predicates."""
    params = [owner_id]
    expressions = []
    for label, state in (("personal", "PERSONAL"), ("for_sale", "ALL_FOR_SALE"),
                         ("preparing", "PREPARING"), ("review", "REVIEW"),
                         ("ready", "READY"), ("listed", "LISTED")):
        filters = []
        append_collection_filters(filters, params, listing_state=state)
        expressions.append(f"count(*) filter(where {' and '.join(filters)})::int as {label}")
    row = await connection.fetchrow(f"""select {', '.join(expressions)}
      from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
      where i.owner_id=$1 and {ACTIVE_COLLECTION_SQL}""", *params)
    return {key: int(value or 0) for key, value in dict(row).items()}
