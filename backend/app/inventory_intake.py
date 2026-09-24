from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import ManualCatalogueCreate, ManualInventoryCreate


router = APIRouter(prefix="/api/v1")

CARD_CONDITIONS = {
    "Near Mint",
    "Lightly Played",
    "Moderately Played",
    "Heavily Played",
    "Damaged",
}


def _catalogue_search_terms(query: str) -> list[str]:
    """Split a human catalogue query into literal terms.

    Every term must match at least one searchable catalogue field. This makes
    searches such as "Absol 063/094" work without turning spaces into an
    accidental exact-phrase requirement.
    """

    return [term for term in query.split() if term]



def _manual_identity_key(product: ManualCatalogueCreate) -> str:
    payload = {
        "product_type": product.product_type,
        "game": product.game.casefold(),
        "name": product.name.casefold(),
        "set_name": product.set_name.casefold(),
        "card_number": (product.card_number or "").casefold(),
        "variant": product.variant.casefold(),
        "rarity": product.rarity.casefold(),
        "language": (product.language or "").casefold(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"manual:v1:{digest}"


def _manual_intake_payload_hash(payload: ManualInventoryCreate) -> str:
    canonical = payload.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _existing_receipt(
    connection: asyncpg.Connection,
    owner_id: UUID,
    request_key: UUID,
) -> asyncpg.Record | None:
    return await connection.fetchrow(
        """
        select payload_hash, response
        from tcg.request_receipts
        where owner_id = $1 and request_key = $2
        """,
        owner_id,
        request_key,
    )


def _receipt_response(receipt: Any, payload_hash: str) -> dict:
    if receipt["payload_hash"] != payload_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different inventory intake payload",
        )

    stored = receipt["response"]
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Stored intake receipt JSON is invalid") from exc
    if not isinstance(stored, dict):
        raise RuntimeError("Stored intake receipt has an invalid response shape")

    replay = dict(stored)
    replay["replayed"] = True
    return replay


async def _find_exact_catalogue(
    connection: asyncpg.Connection,
    product: ManualCatalogueCreate,
) -> asyncpg.Record | None:
    rows = await connection.fetch(
        """
        select *
        from tcg.catalogue_products
        where product_type = $1
          and lower(btrim(game)) = lower(btrim($2))
          and lower(btrim(name)) = lower(btrim($3))
          and lower(btrim(set_name)) = lower(btrim($4))
          and lower(btrim(coalesce(card_number, ''))) = lower(btrim(coalesce($5, '')))
          and lower(btrim(variant)) = lower(btrim($6))
          and lower(btrim(rarity)) = lower(btrim($7))
          and lower(btrim(coalesce(language, ''))) = lower(btrim(coalesce($8, '')))
        order by created_at, id
        limit 2
        """,
        product.product_type,
        product.game,
        product.name,
        product.set_name,
        product.card_number,
        product.variant,
        product.rarity,
        product.language,
    )
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple catalogue products match this identity. Review catalogue data before adding inventory.",
        )
    return rows[0] if rows else None


async def _existing_intake(
    connection: asyncpg.Connection,
    owner_id: UUID,
    request_key: UUID,
) -> asyncpg.Record | None:
    return await connection.fetchrow(
        """
        select
            i.*,
            p.product_type as catalogue_product_type,
            p.game as catalogue_game,
            p.name as catalogue_name,
            p.set_name as catalogue_set_name,
            p.card_number as catalogue_card_number,
            p.variant as catalogue_variant,
            p.rarity as catalogue_rarity,
            p.language as catalogue_language
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id = i.catalogue_id
        where i.owner_id = $1 and i.intake_request_key = $2
        """,
        owner_id,
        request_key,
    )


def _existing_response(row: asyncpg.Record) -> dict:
    catalogue = {
        "id": row["catalogue_id"],
        "product_type": row["catalogue_product_type"],
        "game": row["catalogue_game"],
        "name": row["catalogue_name"],
        "set_name": row["catalogue_set_name"],
        "card_number": row["catalogue_card_number"],
        "variant": row["catalogue_variant"],
        "rarity": row["catalogue_rarity"],
        "language": row["catalogue_language"],
    }
    inventory = {
        key: row[key]
        for key in (
            "id",
            "inventory_code",
            "catalogue_id",
            "owner_id",
            "acquisition_cost_minor",
            "acquisition_date",
            "currency",
            "condition",
            "seal_status",
            "grading_company",
            "grade",
            "certificate_number",
            "language",
            "location",
            "storage_location_id",
            "store_price_minor",
            "identity_confirmed",
            "status",
            "notes",
            "version",
            "created_at",
            "updated_at",
            "intake_request_key",
        )
    }
    return {
        "inventory": inventory,
        "catalogue": catalogue,
        "catalogue_created": False,
        "catalogue_reused": False,
        "replayed": True,
    }


def _validate_physical_state(product_type: str, payload: ManualInventoryCreate) -> None:
    if product_type == "CARD":
        if payload.seal_status is not None:
            raise HTTPException(status_code=422, detail="Raw cards do not use seal_status")
        if payload.condition is not None and payload.condition not in CARD_CONDITIONS:
            raise HTTPException(
                status_code=422,
                detail="Card condition must use the Drop Rate / TCGplayer condition scale",
            )
    else:
        if payload.condition is not None:
            raise HTTPException(
                status_code=422,
                detail="Sealed or collection products use seal_status instead of raw card condition",
            )
        if payload.grading_company is not None or payload.grade is not None:
            raise HTTPException(
                status_code=422,
                detail="Grading fields are only supported for card inventory",
            )
        if payload.certificate_number is not None:
            raise HTTPException(
                status_code=422,
                detail="Certificate number is only supported for graded card inventory",
            )


@router.get("/catalogue/search")
async def search_catalogue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search needs at least 2 characters")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)
        terms = _catalogue_search_terms(query)
        rows = await connection.fetch(
            """
            select
                id, product_type, game, name, set_name, card_number,
                variant, rarity, language
            from tcg.catalogue_products p
            where not exists (
                select 1
                from unnest($1::text[]) as search(term)
                where not (
                    strpos(lower(p.name), lower(search.term)) > 0
                    or strpos(lower(p.set_name), lower(search.term)) > 0
                    or strpos(lower(coalesce(p.card_number, '')), lower(search.term)) > 0
                    or strpos(lower(p.game), lower(search.term)) > 0
                    or strpos(lower(coalesce(p.variant, '')), lower(search.term)) > 0
                    or strpos(lower(coalesce(p.rarity, '')), lower(search.term)) > 0
                    or strpos(lower(coalesce(p.language, '')), lower(search.term)) > 0
                )
            )
            order by
                case
                    when lower(coalesce(p.card_number, '')) = any($2::text[]) then 0
                    else 1
                end,
                case when lower(p.name) = lower($3) then 0 else 1 end,
                p.name, p.set_name, p.card_number nulls last, p.variant
            limit $4
            """,
            terms,
            [term.casefold() for term in terms],
            query,
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/inventory/intake", status_code=201)
async def create_inventory_intake(
    payload: ManualInventoryCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
) -> dict:
    try:
        request_key = UUID(idempotency_key.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Idempotency-Key must be a UUID") from exc

    payload_hash = _manual_intake_payload_hash(payload)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)

        receipt = await _existing_receipt(connection, owner["id"], request_key)
        if receipt is not None:
            return jsonable_encoder(_receipt_response(receipt, payload_hash))

        # There are no legacy manual intakes in production at rollout time. If an
        # inventory row ever exists without its matching receipt, fail closed: we
        # cannot prove that a reused key represents the same original request.
        existing = await _existing_intake(connection, owner["id"], request_key)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key already exists without a verifiable intake receipt",
            )

        catalogue_created = False
        catalogue_reused = False

        if payload.catalogue_id is not None:
            catalogue = await connection.fetchrow(
                "select * from tcg.catalogue_products where id = $1",
                payload.catalogue_id,
            )
            if catalogue is None:
                raise HTTPException(status_code=404, detail="Catalogue product not found")
        else:
            assert payload.new_catalogue is not None
            catalogue = await _find_exact_catalogue(connection, payload.new_catalogue)
            if catalogue is not None:
                catalogue_reused = True
            else:
                catalogue = await connection.fetchrow(
                    """
                    insert into tcg.catalogue_products(
                        identity_key, product_type, game, name, set_name,
                        card_number, variant, rarity, language
                    ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    on conflict (identity_key) do nothing
                    returning *
                    """,
                    _manual_identity_key(payload.new_catalogue),
                    payload.new_catalogue.product_type,
                    payload.new_catalogue.game,
                    payload.new_catalogue.name,
                    payload.new_catalogue.set_name,
                    payload.new_catalogue.card_number,
                    payload.new_catalogue.variant,
                    payload.new_catalogue.rarity,
                    payload.new_catalogue.language,
                )
                if catalogue is None:
                    catalogue = await _find_exact_catalogue(connection, payload.new_catalogue)
                    if catalogue is None:
                        raise HTTPException(
                            status_code=409,
                            detail="Catalogue identity was created concurrently. Search the catalogue and retry.",
                        )
                    catalogue_reused = True
                else:
                    catalogue_created = True

        _validate_physical_state(catalogue["product_type"], payload)

        if payload.storage_location_id is not None:
            location = await connection.fetchrow(
                """
                select id, code, active
                from tcg.storage_locations
                where id = $1 and owner_id = $2
                """,
                payload.storage_location_id,
                owner["id"],
            )
            if location is None:
                raise HTTPException(status_code=404, detail="Storage location not found")
            if not location["active"]:
                raise HTTPException(status_code=422, detail="Cannot assign inventory to an inactive location")

        inventory_id = uuid4()
        inventory_code = f"INV-{inventory_id.hex.upper()}"
        physical_language = payload.language or catalogue["language"]

        inventory = await connection.fetchrow(
            """
            insert into tcg.inventory_items(
                id, inventory_code, catalogue_id, owner_id,
                acquisition_cost_minor, acquisition_date, currency,
                condition, seal_status, grading_company, grade,
                certificate_number, language, storage_location_id,
                store_price_minor, identity_confirmed, status, notes,
                intake_request_key
            ) values (
                $1, $2, $3, $4,
                $5, $6, 'GBP',
                $7, $8, $9, $10,
                $11, $12, $13,
                $14, $15, 'DRAFT', $16,
                $17
            )
            on conflict (intake_request_key) do nothing
            returning *
            """,
            inventory_id,
            inventory_code,
            catalogue["id"],
            owner["id"],
            payload.acquisition_cost_minor,
            payload.acquisition_date,
            payload.condition,
            payload.seal_status,
            payload.grading_company,
            payload.grade,
            payload.certificate_number,
            physical_language,
            payload.storage_location_id,
            payload.store_price_minor,
            payload.identity_confirmed,
            payload.notes,
            request_key,
        )

        if inventory is None:
            receipt = await _existing_receipt(connection, owner["id"], request_key)
            if receipt is not None:
                return jsonable_encoder(_receipt_response(receipt, payload_hash))
            raise HTTPException(
                status_code=409,
                detail="Inventory intake conflicted without a verifiable receipt; retry with a new Idempotency-Key",
            )

        response = jsonable_encoder(
            {
                "inventory": dict(inventory),
                "catalogue": dict(catalogue),
                "catalogue_created": catalogue_created,
                "catalogue_reused": catalogue_reused,
                "replayed": False,
            }
        )

        receipt_insert = await connection.fetchrow(
            """
            insert into tcg.request_receipts(owner_id, request_key, payload_hash, response)
            values ($1, $2, $3, $4::jsonb)
            on conflict (owner_id, request_key) do nothing
            returning id
            """,
            owner["id"],
            request_key,
            payload_hash,
            json.dumps(response),
        )
        if receipt_insert is None:
            receipt = await _existing_receipt(connection, owner["id"], request_key)
            if receipt is None:
                raise HTTPException(status_code=409, detail="Inventory intake receipt conflicted; retry")
            return jsonable_encoder(_receipt_response(receipt, payload_hash))

        return response
