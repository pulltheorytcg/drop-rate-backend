from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

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


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select id, display_name, owner_type, founder_slot
        from tcg.owners
        where active
        order by founder_slot nulls last
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


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
        pattern = f"%{query}%"
        rows = await connection.fetch(
            """
            select
                id, product_type, game, name, set_name, card_number,
                variant, rarity, language
            from tcg.catalogue_products
            where name ilike $1
               or set_name ilike $1
               or coalesce(card_number, '') ilike $1
               or game ilike $1
            order by
                case when lower(coalesce(card_number, '')) = lower($2) then 0 else 1 end,
                name, set_name, card_number nulls last
            limit $3
            """,
            pattern,
            query,
            limit,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/inventory/intake", status_code=201)
async def create_inventory_intake(
    payload: ManualInventoryCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)

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
                try:
                    catalogue = await connection.fetchrow(
                        """
                        insert into tcg.catalogue_products(
                            identity_key, product_type, game, name, set_name,
                            card_number, variant, rarity, language
                        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
                    catalogue_created = True
                except asyncpg.UniqueViolationError:
                    catalogue = await _find_exact_catalogue(connection, payload.new_catalogue)
                    if catalogue is None:
                        raise HTTPException(
                            status_code=409,
                            detail="Catalogue identity was created concurrently. Search the catalogue and retry.",
                        )
                    catalogue_reused = True

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
                store_price_minor, identity_confirmed, status, notes
            ) values (
                $1, $2, $3, $4,
                $5, $6, 'GBP',
                $7, $8, $9, $10,
                $11, $12, $13,
                $14, $15, 'DRAFT', $16
            )
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
        )

        return jsonable_encoder(
            {
                "inventory": dict(inventory),
                "catalogue": dict(catalogue),
                "catalogue_created": catalogue_created,
                "catalogue_reused": catalogue_reused,
            }
        )
