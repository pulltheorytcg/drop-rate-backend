from __future__ import annotations

import asyncio
import logging
from pathlib import PurePosixPath
from typing import Any, Mapping
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import asyncpg

from .db import user_connection
from .settings import Settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_completeness import build_shopify_product_plan, product_create_input


logger = logging.getLogger(__name__)

_PRODUCT_SET_MUTATION = """
mutation BootstrapDropRateProduct(
  $identifier: ProductSetIdentifiers
  $input: ProductSetInput!
) {
  productSet(identifier: $identifier, input: $input, synchronous: true) {
    product {
      id
      handle
      status
      title
      variants(first: 1) {
        nodes {
          id
          sku
          price
          inventoryQuantity
          inventoryItem {
            id
            tracked
          }
        }
      }
      media(first: 1) {
        nodes {
          ... on MediaImage {
            id
            status
            alt
            image {
              url
            }
          }
        }
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
"""


def _money(minor: int | None) -> str:
    return f"{int(minor or 0) / 100:.2f}"


def _handle(inventory_code: str) -> str:
    return f"drop-rate-{inventory_code.casefold().replace('_', '-').replace(' ', '-')}"


def _media_filename(item: Mapping[str, Any]) -> str:
    source = str(item.get("public_source_url") or "").strip()
    suffix = PurePosixPath(urlsplit(source).path).suffix.casefold()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"{item['inventory_code']}{suffix}"


def build_catalogue_product_input(
    item: Mapping[str, Any],
    *,
    location_id: str,
    physical_photo_threshold_minor: int,
) -> dict[str, Any]:
    plan = build_shopify_product_plan(
        item,
        physical_photo_threshold_minor=physical_photo_threshold_minor,
    )
    payload = product_create_input(plan, handle=_handle(str(item["inventory_code"])))

    tags = list(payload.get("tags") or [])
    if item.get("store_price_minor") is None and "Action Required:Pricing" not in tags:
        tags.append("Action Required:Pricing")
    payload["tags"] = tags

    file_id = str(item.get("shopify_file_gid") or "").strip()
    file_status = str(item.get("shopify_file_status") or "").strip().upper()
    if file_id and file_status == "READY":
        payload["files"] = [{"id": file_id}]
    else:
        payload["files"] = [{
            "contentType": "IMAGE",
            "filename": _media_filename(item),
            "originalSource": str(item["public_source_url"]).strip(),
            "alt": str(item.get("alt_text") or plan["title"]).strip(),
        }]

    payload["productOptions"] = [{
        "name": "Title",
        "values": [{"name": "Default Title"}],
    }]

    inventory_item: dict[str, Any] = {
        "sku": str(item["inventory_code"]),
        "tracked": True,
    }
    if item.get("acquisition_cost_minor") is not None:
        inventory_item["cost"] = _money(int(item["acquisition_cost_minor"]))

    payload["variants"] = [{
        "optionValues": [{"optionName": "Title", "name": "Default Title"}],
        "price": _money(
            int(item["store_price_minor"])
            if item.get("store_price_minor") is not None
            else None
        ),
        "sku": str(item["inventory_code"]),
        "inventoryPolicy": "DENY",
        "inventoryItem": inventory_item,
        "inventoryQuantities": [{
            "locationId": location_id,
            "name": "on_hand",
            "quantity": 1,
        }],
    }]
    payload["status"] = "DRAFT"
    return payload


async def _product_set_with_retry(
    client: ShopifyAdminClient,
    *,
    identifier: dict[str, Any],
    payload: dict[str, Any],
    attempts: int = 3,
) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        try:
            data = await client.graphql(
                query=_PRODUCT_SET_MUTATION,
                variables={"identifier": identifier, "input": payload},
            )
            result = data.get("productSet")
            if not isinstance(result, dict):
                raise ShopifyApiError("Shopify productSet returned an invalid response")
            return result
        except ShopifyApiError as exc:
            if not exc.retryable or attempt >= attempts:
                raise
            await asyncio.sleep(float(2 ** (attempt - 1)))
    raise ShopifyApiError("Shopify productSet exhausted retry attempts")


async def _candidate_rows(
    pool: asyncpg.Pool,
    *,
    actor_user_id: UUID,
) -> list[dict[str, Any]]:
    async with user_connection(
        pool,
        actor_user_id,
        f"shopify-catalogue-bootstrap-read:{uuid4()}",
    ) as connection:
        rows = await connection.fetch(
            """
            select
                i.id,i.catalogue_id,i.owner_id,i.inventory_code,i.version,i.status,
                i.sale_intent,i.identity_confirmed,i.acquisition_cost_minor,
                i.store_price_minor,i.market_value_minor,i.recommended_retail_minor,
                i.storage_location_id,i.language,i.condition,i.seal_status,
                i.grading_company,i.grade,i.condition_review_status,
                p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
                p.rarity,p.language as catalogue_language,
                m.id as media_id,m.public_source_url,m.alt_text,
                m.shopify_file_gid,m.shopify_file_status,m.shopify_cdn_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            join lateral (
                select ma.*
                from tcg.media_assets ma
                where ma.catalogue_id=i.catalogue_id
                  and ma.scope='CANONICAL_CARD'
                  and ma.side='FRONT'
                  and ma.source_status='ACTIVE'
                  and ma.rights_status='VERIFIED'
                  and ma.rights_tier='STOREFRONT_ALLOWED'
                  and nullif(btrim(coalesce(ma.rights_basis,'')),'') is not null
                  and nullif(btrim(coalesce(ma.media_language,'')),'') is not null
                  and (
                    p.language is null
                    or lower(btrim(ma.media_language))=lower(btrim(p.language))
                  )
                  and lower(btrim(coalesce(ma.media_variant,'')))=
                      lower(btrim(coalesce(p.variant,'')))
                  and coalesce(ma.shopify_cdn_url,ma.public_source_url) is not null
                order by
                    case ma.approval_status when 'APPROVED' then 0 else 1 end,
                    case ma.shopify_file_status when 'READY' then 0 else 1 end,
                    ma.created_at desc
                limit 1
            ) m on true
            left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            left join tcg.listing_inventory_members lim
              on lim.inventory_id=i.id and lim.state <> 'REMOVED'
            where i.sale_intent='FOR_SALE'
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and sil.id is null
              and lim.id is null
            order by
                case i.status when 'APPROVED' then 0
                              when 'INSPECTION' then 1
                              else 2 end,
                i.updated_at,
                i.inventory_code
            """
        )
    return [dict(row) for row in rows]


async def _record_product(
    pool: asyncpg.Pool,
    *,
    item: Mapping[str, Any],
    product: Mapping[str, Any],
    media: Mapping[str, Any] | None,
    shop_domain: str,
    location_id: str,
    publication_id: str,
    actor_user_id: UUID,
) -> str:
    variants = product.get("variants")
    variant_nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(variant_nodes, list) or len(variant_nodes) != 1:
        return "INVALID_VARIANT"
    variant = variant_nodes[0]
    if not isinstance(variant, Mapping):
        return "INVALID_VARIANT"
    inventory_item = variant.get("inventoryItem")
    if not isinstance(inventory_item, Mapping):
        return "INVALID_INVENTORY_ITEM"

    product_id = str(product.get("id") or "").strip()
    variant_id = str(variant.get("id") or "").strip()
    inventory_item_id = str(inventory_item.get("id") or "").strip()
    if not product_id or not variant_id or not inventory_item_id:
        return "MISSING_REMOTE_ID"

    async with user_connection(
        pool,
        actor_user_id,
        f"shopify-catalogue-bootstrap-write:{uuid4()}",
    ) as connection:
        async with connection.transaction():
            current = await connection.fetchrow(
                """
                select id,owner_id,inventory_code,sale_intent,status,store_price_minor
                from tcg.inventory_items
                where id=$1
                for update
                """,
                item["id"],
            )
            if current is None:
                return "INVENTORY_MISSING"
            if current["sale_intent"] != "FOR_SALE":
                return "SALE_INTENT_CHANGED"
            if current["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
                return "INVENTORY_STATE_CHANGED"

            existing = await connection.fetchrow(
                """
                select id,shopify_product_gid
                from tcg.shopify_inventory_links
                where inventory_id=$1
                for update
                """,
                item["id"],
            )
            if existing is not None:
                if str(existing["shopify_product_gid"]) == product_id:
                    return "ALREADY_LINKED"
                return "LINK_CONFLICT"

            await connection.execute(
                """
                insert into tcg.shopify_inventory_links(
                    inventory_id,owner_id,created_by_user_id,listing_key,
                    allocation_priority,shop_domain,shopify_product_gid,
                    shopify_variant_gid,shopify_inventory_item_gid,
                    shopify_location_gid,shopify_publication_gid,sku,
                    sync_state,test_mode,synced_price_minor
                ) values(
                    $1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,
                    'DRAFT',false,$12
                )
                """,
                current["id"],
                current["owner_id"],
                actor_user_id,
                f"catalogue:{current['id']}",
                shop_domain,
                product_id,
                variant_id,
                inventory_item_id,
                location_id,
                publication_id,
                current["inventory_code"],
                current["store_price_minor"],
            )

            if isinstance(media, Mapping):
                media_id = str(media.get("id") or "").strip()
                remote_status = str(media.get("status") or "").strip().upper()
                image = media.get("image")
                cdn_url = (
                    str(image.get("url") or "").strip()
                    if isinstance(image, Mapping)
                    else ""
                )
                if media_id and remote_status in {"READY", "PROCESSING", "FAILED"}:
                    await connection.execute(
                        """
                        update tcg.media_assets m
                        set approval_status='APPROVED',
                            approved_by_user_id=$2,
                            approved_at=coalesce(m.approved_at,clock_timestamp()),
                            rights_verified_at=coalesce(
                                m.rights_verified_at,clock_timestamp()
                            ),
                            source_checked_at=clock_timestamp(),
                            source_status_note=(
                                'Storefront-allowed canonical media approved '
                                'during requested Shopify catalogue sync'
                            ),
                            shopify_file_gid=$3,
                            shopify_file_status=$4,
                            shopify_cdn_url=case
                              when nullif($5,'') is not null then $5
                              else m.shopify_cdn_url
                            end,
                            shopify_error=case when $4='FAILED'
                              then 'Shopify media processing failed' else null end,
                            updated_at=clock_timestamp(),
                            version=version+1
                        where m.id=$1
                          and m.scope='CANONICAL_CARD'
                          and m.side='FRONT'
                          and m.source_status='ACTIVE'
                          and m.rights_status='VERIFIED'
                          and m.rights_tier='STOREFRONT_ALLOWED'
                        """,
                        item["media_id"],
                        actor_user_id,
                        media_id,
                        remote_status,
                        cdn_url,
                    )
    return "LINKED"


async def run_shopify_catalogue_bootstrap(
    pool: asyncpg.Pool,
    settings: Settings,
) -> dict[str, Any]:
    if (
        not settings.shopify_shop_domain
        or not settings.shopify_client_id
        or not settings.shopify_client_secret
        or not settings.shopify_location_gid
        or not settings.shopify_publication_gid
        or not settings.shopify_catalogue_bootstrap_actor_user_id
    ):
        logger.error("Shopify catalogue bootstrap skipped: Shopify is not fully configured")
        return {"status": "SKIPPED_CONFIGURATION"}

    try:
        actor_user_id = UUID(settings.shopify_catalogue_bootstrap_actor_user_id)
    except (TypeError, ValueError):
        logger.error("Shopify catalogue bootstrap skipped: actor user id is invalid")
        return {"status": "SKIPPED_ACTOR_CONFIGURATION"}

    async with user_connection(
        pool,
        actor_user_id,
        f"shopify-catalogue-bootstrap-actor-check:{uuid4()}",
    ) as connection:
        actor_is_platform_admin = bool(
            await connection.fetchval(
                """
                select exists(
                    select 1
                    from tcg.owner_memberships
                    where user_id=tcg.current_user_id()
                      and active
                      and role='PLATFORM_ADMIN'
                )
                """
            )
        )
    if not actor_is_platform_admin:
        logger.error("Shopify catalogue bootstrap skipped: actor is not platform admin")
        return {"status": "SKIPPED_ACTOR_ACCESS"}

    client = ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )
    candidates = await _candidate_rows(pool, actor_user_id=actor_user_id)
    logger.info(
        "Shopify catalogue bootstrap starting with %s unlinked inventory items",
        len(candidates),
    )

    linked = 0
    already_linked = 0
    failed = 0
    skipped = 0

    for index, item in enumerate(candidates, start=1):
        handle = _handle(str(item["inventory_code"]))
        payload = build_catalogue_product_input(
            item,
            location_id=settings.shopify_location_gid,
            physical_photo_threshold_minor=settings.media_physical_photo_threshold_minor,
        )
        try:
            result = await _product_set_with_retry(
                client,
                identifier={"handle": handle},
                payload=payload,
            )
        except ShopifyApiError:
            failed += 1
            logger.exception(
                "Shopify catalogue bootstrap API failure for %s",
                item["inventory_code"],
            )
            continue

        errors = result.get("userErrors")
        if isinstance(errors, list) and errors:
            failed += 1
            logger.warning(
                "Shopify catalogue bootstrap user error for %s: %s",
                item["inventory_code"],
                [str(error.get("message") or "") for error in errors if isinstance(error, Mapping)],
            )
            continue

        product = result.get("product")
        if not isinstance(product, Mapping):
            failed += 1
            logger.warning(
                "Shopify catalogue bootstrap returned no product for %s",
                item["inventory_code"],
            )
            continue

        media_connection = product.get("media")
        media_nodes = (
            media_connection.get("nodes")
            if isinstance(media_connection, Mapping)
            else None
        )
        media = (
            media_nodes[0]
            if isinstance(media_nodes, list)
            and media_nodes
            and isinstance(media_nodes[0], Mapping)
            else None
        )
        state = await _record_product(
            pool,
            item=item,
            product=product,
            media=media,
            shop_domain=settings.shopify_shop_domain,
            location_id=settings.shopify_location_gid,
            publication_id=settings.shopify_publication_gid,
            actor_user_id=actor_user_id,
        )
        if state == "LINKED":
            linked += 1
        elif state == "ALREADY_LINKED":
            already_linked += 1
        elif state in {
            "SALE_INTENT_CHANGED",
            "INVENTORY_STATE_CHANGED",
            "INVENTORY_MISSING",
        }:
            skipped += 1
        else:
            failed += 1
            logger.warning(
                "Shopify catalogue bootstrap reconciliation failure for %s: %s",
                item["inventory_code"],
                state,
            )

        if index % 25 == 0 or index == len(candidates):
            logger.info(
                "Shopify catalogue bootstrap progress %s/%s linked=%s failed=%s skipped=%s",
                index,
                len(candidates),
                linked,
                failed,
                skipped,
            )
        await asyncio.sleep(0.05)

    summary = {
        "status": "COMPLETE",
        "considered": len(candidates),
        "linked": linked,
        "already_linked": already_linked,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info("Shopify catalogue bootstrap complete: %s", summary)
    return summary
