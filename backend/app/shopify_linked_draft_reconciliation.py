from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping
from uuid import UUID, uuid4

import asyncpg

from .db import user_connection
from .import_enrichment import _confirm_identity, _unmarked_import_identity_evidence
from .identity_review import import_exact_evidence
from .language import clean_language
from .physical_state import validate_physical_state
from .settings import Settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_completeness import (
    build_shopify_product_plan,
    product_create_input,
    required_collection_titles,
)
from .shopify_pipeline import _test_sync_missing


logger = logging.getLogger(__name__)


class ReconciliationBlocked(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _language_key(game: object, set_name: object) -> str:
    return f"{str(game or '').strip().casefold()}|{str(set_name or '').strip().casefold()}"


def parse_language_map(raw: str | None) -> dict[str, str]:
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Shopify linked-draft language map must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Shopify linked-draft language map must be a JSON object")
    result: dict[str, str] = {}
    for key, value in payload.items():
        clean_key = str(key or "").strip().casefold()
        language = clean_language(value)
        if not clean_key or not language:
            raise ValueError("Shopify linked-draft language map has an empty key/value")
        if language not in {"English", "Japanese"}:
            raise ValueError(f"Unsupported linked-draft language: {language}")
        result[clean_key] = language
    return result


def resolve_reconciliation_language(
    row: Mapping[str, Any],
    language_map: Mapping[str, str],
) -> str:
    current = clean_language(row.get("language"))
    if current:
        return current
    canonical = clean_language(row.get("catalogue_language"))
    if canonical:
        return canonical
    key = _language_key(row.get("game"), row.get("set_name"))
    language = clean_language(language_map.get(key))
    if not language:
        raise ReconciliationBlocked(
            "LANGUAGE_UNRESOLVED",
            f"No verified language mapping exists for {row.get('game')} / {row.get('set_name')}",
        )
    return language


def parse_collectr_price_override(source_record: object) -> int | None:
    source: Mapping[str, Any]
    if isinstance(source_record, Mapping):
        source = source_record
    elif isinstance(source_record, str):
        try:
            parsed = json.loads(source_record)
        except json.JSONDecodeError:
            return None
        source = parsed if isinstance(parsed, Mapping) else {}
    else:
        source = {}

    raw = str(source.get("Price Override") or "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money(minor: int) -> str:
    return f"{int(minor) / 100:.2f}"


def _remote_variant(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    variants = snapshot.get("variants")
    nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], Mapping):
        raise ReconciliationBlocked(
            "REMOTE_VARIANT_COUNT",
            "Linked Shopify product must contain exactly one variant",
        )
    return nodes[0]


def remote_launch_blockers(
    *,
    snapshot: Mapping[str, Any],
    product_gid: str,
    variant_gid: str,
    inventory_code: str,
    expected_collections: set[str],
) -> list[str]:
    blockers: list[str] = []
    if str(snapshot.get("id") or "") != product_gid:
        blockers.append("REMOTE_PRODUCT_ID_MISMATCH")

    status = str(snapshot.get("status") or "").upper()
    if status not in {"DRAFT", "ACTIVE"}:
        blockers.append("REMOTE_STATUS_UNSUPPORTED")

    media = snapshot.get("media")
    media_nodes = media.get("nodes") if isinstance(media, Mapping) else None
    if not isinstance(media_nodes, list) or not media_nodes:
        blockers.append("REMOTE_IMAGE_MISSING")

    try:
        variant = _remote_variant(snapshot)
    except ReconciliationBlocked as exc:
        blockers.append(exc.code)
        variant = {}

    if str(variant.get("id") or "") != variant_gid:
        blockers.append("REMOTE_VARIANT_ID_MISMATCH")
    inventory_item = variant.get("inventoryItem")
    if not isinstance(inventory_item, Mapping):
        blockers.append("REMOTE_INVENTORY_ITEM_MISSING")
    else:
        if str(inventory_item.get("sku") or "").strip().upper() != inventory_code.strip().upper():
            blockers.append("REMOTE_SKU_MISMATCH")
        if inventory_item.get("tracked") is not True:
            blockers.append("REMOTE_INVENTORY_NOT_TRACKED")
    try:
        quantity = int(variant.get("inventoryQuantity"))
    except (TypeError, ValueError):
        quantity = 0
    if quantity <= 0:
        blockers.append("REMOTE_OUT_OF_STOCK")

    collections = snapshot.get("collections")
    collection_nodes = collections.get("nodes") if isinstance(collections, Mapping) else None
    actual_collections = {
        str(node.get("title") or "").strip()
        for node in collection_nodes or []
        if isinstance(node, Mapping) and str(node.get("title") or "").strip()
    }
    if not expected_collections.issubset(actual_collections):
        blockers.append("REMOTE_COLLECTION_MISSING")

    return list(dict.fromkeys(blockers))


async def _load_item(
    connection: asyncpg.Connection,
    inventory_id: UUID,
    shop_domain: str,
    *,
    for_update: bool,
):
    lock = " for update of i,sil" if for_update else ""
    return await connection.fetchrow(
        f"""
        select
            i.*,
            p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
            p.rarity,p.language as catalogue_language,
            sl.id as registered_location_id,
            sl.active as registered_location_active,
            sil.id as link_id,
            sil.shop_domain,
            sil.shopify_product_gid,
            sil.shopify_variant_gid,
            sil.shopify_inventory_item_gid,
            sil.shopify_location_gid,
            sil.shopify_publication_gid,
            sil.sku as link_sku,
            sil.sync_state,
            sil.test_mode,
            sil.synced_price_minor,
            sil.reserved_order_reference,
            sil.reserved_line_reference,
            sil.version as link_version,
            exists(
                select 1
                from tcg.listing_inventory_members lim
                where lim.inventory_id=i.id
                  and lim.state <> 'REMOVED'
            ) as has_listing_membership,
            exists(
                select 1
                from tcg.inventory_reservations ir
                where ir.inventory_id=i.id
                  and ir.status='ACTIVE'
                  and ir.released_at is null
                  and ir.consumed_at is null
            ) as has_active_reservation
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
        left join tcg.storage_locations sl on sl.id=i.storage_location_id
        where i.id=$1
          and sil.shop_domain=$2
        {lock}
        """,
        inventory_id,
        shop_domain,
    )


async def _prepare_core(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    actor_user_id: UUID,
    inventory_id: UUID,
    language_map: Mapping[str, str],
    apply: bool,
) -> tuple[dict[str, Any], list[str]]:
    request_id = f"shopify-linked-draft-reconcile:{uuid4()}"
    changes: list[str] = []
    async with user_connection(pool, actor_user_id, request_id) as connection:
        row = await _load_item(
            connection,
            inventory_id,
            str(settings.shopify_shop_domain),
            for_update=apply,
        )
        if row is None:
            raise ReconciliationBlocked("LINK_NOT_FOUND", "Inventory/Shopify link was not found")
        item = dict(row)

        if item.get("test_mode"):
            raise ReconciliationBlocked("TEST_LINK_EXCLUDED", "Test-mode Shopify links are excluded")
        if str(item.get("sale_intent") or "") != "FOR_SALE":
            raise ReconciliationBlocked("NOT_FOR_SALE", "Inventory is not marked FOR_SALE")
        if str(item.get("status") or "") not in {"DRAFT", "INSPECTION", "APPROVED"}:
            raise ReconciliationBlocked("INVENTORY_STATUS", "Inventory is not launchable")
        if str(item.get("sync_state") or "") not in {"DRAFT", "PUBLISHED"}:
            raise ReconciliationBlocked("LINK_STATE", "Shopify link is not draft/published")
        if item.get("has_listing_membership"):
            raise ReconciliationBlocked("POOLED_INVENTORY", "Inventory belongs to a pooled listing")
        if item.get("has_active_reservation"):
            raise ReconciliationBlocked("RESERVED_INVENTORY", "Inventory is actively reserved")
        if item.get("reserved_order_reference") or item.get("reserved_line_reference"):
            raise ReconciliationBlocked("RESERVED_LINK", "Shopify link has an order reservation")

        language = resolve_reconciliation_language(item, language_map)
        if not item.get("identity_confirmed"):
            evidence_row = dict(item)
            if apply:
                identity_row, evidence = await _confirm_identity(
                    connection,
                    owner_id=item["owner_id"],
                    user_id=actor_user_id,
                    row=evidence_row,
                    default_language=language,
                )
            else:
                evidence = (
                    import_exact_evidence(evidence_row)
                    or _unmarked_import_identity_evidence(
                        evidence_row,
                        default_language=language,
                    )
                )
                identity_row = evidence_row if evidence is not None else None
            if identity_row is None:
                raise ReconciliationBlocked(
                    "IDENTITY_NOT_EXACT",
                    "Original import does not exactly support the selected language/identity",
                )
            item["identity_confirmed"] = True
            item["language"] = language
            changes.append(
                f"identity:{(evidence or {}).get('verification_method','CONFIRMED')}"
            )
        else:
            current_language = clean_language(item.get("language"))
            if current_language and current_language != language:
                raise ReconciliationBlocked(
                    "LANGUAGE_CONFLICT",
                    f"Existing language {current_language} conflicts with resolved {language}",
                )

        if item.get("store_price_minor") is None:
            override_minor = parse_collectr_price_override(item.get("source_record"))
            if override_minor is None:
                raise ReconciliationBlocked(
                    "PRICE_UNRESOLVED",
                    "Store price is missing and Collectr has no positive Price Override",
                )
            item["store_price_minor"] = override_minor
            if apply:
                updated = await connection.fetchrow(
                    """
                    update tcg.inventory_items
                    set store_price_minor=$2,
                        imported_price_override_minor=$2,
                        version=version+1,
                        updated_at=clock_timestamp()
                    where id=$1
                    returning *
                    """,
                    inventory_id,
                    override_minor,
                )
                if updated is None:
                    raise ReconciliationBlocked("PRICE_UPDATE_FAILED", "Price override update failed")
                changes.append(f"price_override:{override_minor}")

        simulated = dict(item)
        simulated["status"] = "APPROVED"
        simulated["identity_confirmed"] = True
        simulated["language"] = language
        missing = _test_sync_missing(
            simulated,
            physical_photo_threshold_minor=settings.media_physical_photo_threshold_minor,
        )
        if missing:
            raise ReconciliationBlocked(
                "CORE_POLICY_BLOCKED",
                "; ".join(missing),
            )

        validate_physical_state(
            product_type=str(item.get("product_type") or ""),
            condition=item.get("condition"),
            seal_status=item.get("seal_status"),
            grading_company=item.get("grading_company"),
            grade=item.get("grade"),
            certificate_number=item.get("certificate_number"),
        )

        if apply and str(item.get("status") or "") != "APPROVED":
            await connection.execute(
                """
                update tcg.inventory_items
                set status='APPROVED',
                    version=version+1,
                    updated_at=clock_timestamp()
                where id=$1
                """,
                inventory_id,
            )
            changes.append("status:APPROVED")

        refreshed = await _load_item(
            connection,
            inventory_id,
            str(settings.shopify_shop_domain),
            for_update=False,
        )
        if refreshed is None:
            raise ReconciliationBlocked("REFRESH_FAILED", "Inventory disappeared after preparation")
        result = dict(refreshed)
        if not apply:
            result.update(simulated)
        return result, changes


async def _mark_published(
    pool: asyncpg.Pool,
    *,
    actor_user_id: UUID,
    item: Mapping[str, Any],
) -> None:
    request_id = f"shopify-linked-draft-published:{uuid4()}"
    async with user_connection(pool, actor_user_id, request_id) as connection:
        async with connection.transaction():
            current = await connection.fetchrow(
                """
                select *
                from tcg.shopify_inventory_links
                where id=$1
                for update
                """,
                item["link_id"],
            )
            if current is None:
                raise RuntimeError("Shopify link disappeared before publication commit")
            if current["sync_state"] == "PUBLISHED":
                return
            if current["sync_state"] != "DRAFT":
                raise RuntimeError("Shopify link state changed before publication commit")
            result = await connection.execute(
                """
                update tcg.shopify_inventory_links
                set sync_state='PUBLISHED',
                    synced_price_minor=$2,
                    last_synced_at=clock_timestamp(),
                    version=version+1
                where id=$1
                  and sync_state='DRAFT'
                """,
                item["link_id"],
                int(item["store_price_minor"]),
            )
            if not str(result).endswith("1"):
                raise RuntimeError("Shopify link publication state update did not affect one row")
            await connection.execute(
                """
                insert into tcg.audit_events(
                    actor,request_id,action,entity_type,entity_id,old_values,new_values
                ) values(
                    $1,$2,'SHOPIFY_LINK_PUBLISHED_RECONCILIATION',
                    'SHOPIFY_INVENTORY_LINK',$3,$4::jsonb,$5::jsonb
                )
                """,
                str(actor_user_id),
                request_id,
                item["inventory_id"],
                json.dumps({
                    "link_id": str(item["link_id"]),
                    "sync_state": "DRAFT",
                }),
                json.dumps({
                    "link_id": str(item["link_id"]),
                    "sync_state": "PUBLISHED",
                    "synced_price_minor": int(item["store_price_minor"]),
                }),
            )


async def reconcile_one_linked_draft(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    inventory_id: UUID,
    language_map: Mapping[str, str],
    apply: bool,
) -> dict[str, Any]:
    try:
        item, core_changes = await _prepare_core(
            pool,
            settings=settings,
            actor_user_id=actor_user_id,
            inventory_id=inventory_id,
            language_map=language_map,
            apply=apply,
        )
        product_gid = str(item.get("shopify_product_gid") or "")
        variant_gid = str(item.get("shopify_variant_gid") or "")
        inventory_code = str(item.get("inventory_code") or "")
        if not product_gid or not variant_gid or not inventory_code:
            raise ReconciliationBlocked("LINK_INCOMPLETE", "Shopify link identifiers are incomplete")

        snapshot = await client.get_product_snapshot(product_gid)
        expected_collections = set(required_collection_titles(item))
        blockers = remote_launch_blockers(
            snapshot=snapshot,
            product_gid=product_gid,
            variant_gid=variant_gid,
            inventory_code=inventory_code,
            expected_collections=expected_collections,
        )
        if blockers:
            raise ReconciliationBlocked("REMOTE_NOT_READY", ",".join(blockers))

        variant = _remote_variant(snapshot)
        expected_price = _money(int(item["store_price_minor"]))
        remote_price = str(variant.get("price") or "")
        plan = build_shopify_product_plan(
            item,
            physical_photo_threshold_minor=settings.media_physical_photo_threshold_minor,
        )

        if not apply:
            return {
                "inventory_id": str(inventory_id),
                "inventory_code": inventory_code,
                "status": "READY",
                "language": item.get("language"),
                "price": expected_price,
                "changes": core_changes,
                "remote_price_change": remote_price != expected_price,
            }

        product_payload = product_create_input(
            plan,
            handle=str(snapshot.get("handle") or "").strip(),
        )
        await client.update_product(
            product_id=product_gid,
            product=product_payload,
        )
        if remote_price != expected_price:
            await client.update_variant_price(
                product_id=product_gid,
                variant_id=variant_gid,
                price=expected_price,
            )

        await client.set_product_status(product_id=product_gid, status="ACTIVE")
        publication_id = str(settings.shopify_publication_gid or item.get("shopify_publication_gid") or "")
        if not publication_id:
            raise ReconciliationBlocked("PUBLICATION_MISSING", "Shopify publication is not configured")
        await client.publish_product(
            product_id=product_gid,
            publication_id=publication_id,
        )
        try:
            await _mark_published(
                pool,
                actor_user_id=actor_user_id,
                item=item,
            )
        except Exception:
            try:
                await client.set_product_status(product_id=product_gid, status="DRAFT")
            except Exception:
                logger.exception(
                    "Linked-draft reconciliation compensation failed for %s",
                    inventory_code,
                )
            raise

        return {
            "inventory_id": str(inventory_id),
            "inventory_code": inventory_code,
            "status": "PUBLISHED",
            "language": item.get("language"),
            "price": expected_price,
            "changes": core_changes,
        }
    except ReconciliationBlocked as exc:
        return {
            "inventory_id": str(inventory_id),
            "status": "BLOCKED",
            "code": exc.code,
            "detail": exc.detail,
        }
    except ShopifyApiError as exc:
        return {
            "inventory_id": str(inventory_id),
            "status": "ERROR",
            "code": "SHOPIFY_API_ERROR",
            "detail": exc.detail,
            "retryable": exc.retryable,
        }
    except Exception as exc:
        logger.exception("Linked-draft reconciliation failed for %s", inventory_id)
        return {
            "inventory_id": str(inventory_id),
            "status": "ERROR",
            "code": "UNEXPECTED_ERROR",
            "detail": str(exc)[:1000],
        }


async def run_linked_draft_reconciliation(
    pool: asyncpg.Pool,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.shopify_linked_draft_reconciliation_enabled:
        return {"status": "DISABLED"}

    if not settings.shopify_catalogue_bootstrap_actor_user_id:
        raise RuntimeError("Linked-draft reconciliation actor user ID is required")
    if not settings.shopify_linked_draft_reconciliation_batch_id:
        raise RuntimeError("Linked-draft reconciliation import batch ID is required")
    if not all(
        (
            settings.shopify_shop_domain,
            settings.shopify_client_id,
            settings.shopify_client_secret,
            settings.shopify_publication_gid,
        )
    ):
        raise RuntimeError("Linked-draft reconciliation Shopify configuration is incomplete")

    actor_user_id = UUID(settings.shopify_catalogue_bootstrap_actor_user_id)
    batch_id = UUID(settings.shopify_linked_draft_reconciliation_batch_id)
    language_map = parse_language_map(settings.shopify_linked_draft_language_map_json)

    client = ShopifyAdminClient(
        shop_domain=str(settings.shopify_shop_domain),
        client_id=str(settings.shopify_client_id),
        client_secret=str(settings.shopify_client_secret),
        api_version=settings.shopify_api_version,
    )

    async with user_connection(
        pool,
        actor_user_id,
        f"shopify-linked-draft-candidates:{uuid4()}",
    ) as connection:
        rows = await connection.fetch(
            """
            select i.id
            from tcg.inventory_items i
            join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            where i.import_batch_id=$1
              and sil.shop_domain=$2
              and sil.test_mode=false
              and sil.sync_state in ('DRAFT','PUBLISHED')
              and i.sale_intent='FOR_SALE'
              and i.status in ('DRAFT','INSPECTION','APPROVED')
            order by i.created_at,i.id
            limit $3
            """,
            batch_id,
            str(settings.shopify_shop_domain),
            settings.shopify_linked_draft_reconciliation_limit,
        )

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            await reconcile_one_linked_draft(
                pool,
                settings=settings,
                client=client,
                actor_user_id=actor_user_id,
                inventory_id=row["id"],
                language_map=language_map,
                apply=settings.shopify_linked_draft_reconciliation_apply,
            )
        )

    totals: dict[str, int] = {}
    blockers: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "UNKNOWN")
        totals[status] = totals.get(status, 0) + 1
        code = str(result.get("code") or "")
        if code:
            blockers[code] = blockers.get(code, 0) + 1

    summary = {
        "status": "COMPLETE",
        "mode": "APPLY" if settings.shopify_linked_draft_reconciliation_apply else "DRY_RUN",
        "batch_id": str(batch_id),
        "considered": len(results),
        "totals": totals,
        "blockers": blockers,
        "results": results,
    }
    logger.warning("Shopify linked-draft reconciliation result: %s", json.dumps(summary))
    return summary