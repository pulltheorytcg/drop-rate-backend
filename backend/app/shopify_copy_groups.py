from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from .shopify_client import ShopifyAdminClient


MAX_COPY_HANDLES = 20


def product_handle_for_inventory(inventory_code: str) -> str:
    clean = str(inventory_code or "").strip()
    if not clean:
        raise ValueError("Inventory code is required")
    return f"drop-rate-{clean.casefold().replace('_', '-').replace(' ', '-')}"


def copy_group_metafields(
    *,
    catalogue_id: UUID | str,
    handles: Sequence[str],
    total_count: int,
) -> list[dict[str, str]]:
    clean_catalogue_id = str(catalogue_id).strip()
    clean_handles = [str(handle).strip() for handle in handles if str(handle).strip()]
    if not clean_catalogue_id:
        raise ValueError("Catalogue ID is required")
    if not clean_handles:
        raise ValueError("At least one copy handle is required")
    if len(clean_handles) > MAX_COPY_HANDLES:
        raise ValueError("Copy handle list exceeds Shopify Liquid safety limit")
    if total_count < len(clean_handles):
        raise ValueError("Copy group total cannot be smaller than visible handles")

    return [
        {
            "namespace": "drop_rate",
            "key": "catalogue_id",
            "type": "single_line_text_field",
            "value": clean_catalogue_id,
        },
        {
            "namespace": "drop_rate",
            "key": "copy_handles",
            "type": "list.single_line_text_field",
            "value": json.dumps(clean_handles, separators=(",", ":")),
        },
        {
            "namespace": "drop_rate",
            "key": "copy_group_size",
            "type": "number_integer",
            "value": str(total_count),
        },
        {
            "namespace": "drop_rate",
            "key": "copy_group_truncated",
            "type": "boolean",
            "value": "true" if total_count > len(clean_handles) else "false",
        },
    ]


def _handles_for_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    current_inventory_code: str,
) -> list[str]:
    ordered = [
        product_handle_for_inventory(str(row["inventory_code"]))
        for row in rows
    ]
    current = product_handle_for_inventory(current_inventory_code)
    if len(ordered) <= MAX_COPY_HANDLES:
        return ordered
    if current in ordered[:MAX_COPY_HANDLES]:
        return ordered[:MAX_COPY_HANDLES]
    return [*ordered[: MAX_COPY_HANDLES - 1], current]


async def sync_shopify_copy_group_metadata(
    connection: Any,
    client: ShopifyAdminClient,
    *,
    catalogue_id: UUID | str,
) -> dict[str, Any]:
    rows = await connection.fetch(
        """
        select
          sil.shopify_product_gid,
          i.inventory_code,
          i.store_price_minor,
          sil.linked_at
        from tcg.inventory_items i
        join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
        where i.catalogue_id=$1::uuid
          and i.sale_intent='FOR_SALE'
          and i.status in ('APPROVED','RESERVED')
          and sil.sync_state='PUBLISHED'
          and sil.sold_at is null
        order by
          i.store_price_minor nulls last,
          sil.linked_at,
          i.inventory_code,
          sil.shopify_product_gid
        """,
        str(catalogue_id),
    )
    normalized = [dict(row) for row in rows]
    if not normalized:
        return {
            "status": "NO_PUBLISHED_COPIES",
            "catalogue_id": str(catalogue_id),
            "copies": 0,
            "updated_products": 0,
            "truncated": False,
        }

    updated = 0
    total = len(normalized)
    for row in normalized:
        handles = _handles_for_row(
            normalized,
            current_inventory_code=str(row["inventory_code"]),
        )
        await client.set_product_metafields(
            product_id=str(row["shopify_product_gid"]),
            metafields=copy_group_metafields(
                catalogue_id=catalogue_id,
                handles=handles,
                total_count=total,
            ),
        )
        updated += 1

    return {
        "status": "SYNCED",
        "catalogue_id": str(catalogue_id),
        "copies": total,
        "updated_products": updated,
        "truncated": total > MAX_COPY_HANDLES,
    }
