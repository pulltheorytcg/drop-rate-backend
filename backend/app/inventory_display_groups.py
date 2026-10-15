"""Read-only inventory grouping. Physical records and sale quantities stay separate."""
from __future__ import annotations


def display_key_sql(item: str = "i", product: str = "p") -> str:
    """Exact printing/language/state; every graded or unsupported item is unique."""
    return f"""case when {product}.product_type in ('CARD','SEALED','COLLECTION')
      and nullif(btrim({item}.grading_company),'') is null
      and nullif(btrim({item}.grade),'') is null
      and nullif(btrim({item}.certificate_number),'') is null
      then jsonb_build_array({item}.owner_id,{item}.catalogue_id,{product}.product_type,
        coalesce(nullif(btrim({item}.language),''),{product}.language,''),
        coalesce({item}.condition,''),coalesce({item}.seal_status,''),coalesce({product}.variant,''),
        case when {item}.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
          then 'ACTIVE' else {item}.status end)
      else jsonb_build_array({item}.owner_id,{item}.id) end"""


async def inventory_group_page(connection, where: str, params: list, limit: int, offset: int):
    """Page groups BEFORE fetching/enriching copies, so a group never straddles pages.

    `where` is generated only by the existing authorized inventory endpoints;
    all user filter values remain bound parameters. The restricted connection
    and explicit owner predicate continue to apply before grouping.
    """
    row = await connection.fetchrow(f"""
      with filtered as (
        select i.id,i.updated_at,i.inventory_code,{display_key_sql()} as display_key
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        where {where}
      ), groups as (
        select display_key,array_agg(id order by updated_at desc,inventory_code) as ids,
          max(updated_at) as updated_at,min(inventory_code) as first_code
        from filtered group by display_key
      ), page as (
        select ids from groups order by updated_at desc,first_code
        limit ${len(params)+1} offset ${len(params)+2}
      )
      select (select count(*)::int from groups) as total,
        (select count(*)::int from filtered) as copy_total,
        array(select unnest(ids) from page) as ids
    """, *params, limit, offset)
    return int(row["total"]), int(row["copy_total"]), row["ids"]
