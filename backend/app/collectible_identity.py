from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1/catalogue", tags=["collectible-identity"])


@router.get("/systems")
async def collectible_systems(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Read the configured collectible/game systems and their taxonomy dimensions."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select
                s.code,s.display_name,s.franchise,s.system_kind,s.publisher,
                s.lifecycle_status,s.official_url,s.metadata,
                coalesce(t.dimensions,'[]'::jsonb) as dimensions
            from tcg.collectible_systems s
            left join lateral (
                select jsonb_agg(
                    jsonb_build_object(
                        'scope_kind',x.scope_kind,
                        'dimension_code',x.dimension_code,
                        'display_name',x.display_name,
                        'cardinality',x.cardinality,
                        'required_for_verified',x.required_for_verified,
                        'official_source_url',x.official_source_url
                    )
                    order by x.scope_kind,x.dimension_code
                ) as dimensions
                from tcg.taxonomy_schemas x
                where x.system_code=s.code
            ) t on true
            order by s.system_kind,s.display_name
            """
        )

    return jsonable_encoder({"systems": [dict(row) for row in rows]})


@router.get("/taxonomy/{system_code}")
async def collectible_taxonomy(
    system_code: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Return all currently registered taxonomy values for one collectible system."""

    code = system_code.strip().upper()
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        system = await connection.fetchrow(
            """
            select code,display_name,franchise,system_kind,publisher,
                   lifecycle_status,official_url,metadata
            from tcg.collectible_systems
            where code=$1
            """,
            code,
        )
        if system is None:
            raise HTTPException(status_code=404, detail="Collectible system not found")

        rows = await connection.fetch(
            """
            select
                s.scope_kind,s.dimension_code,s.display_name,s.cardinality,
                s.required_for_verified,s.official_source_url,s.metadata,
                coalesce(
                    jsonb_agg(
                        jsonb_build_object(
                            'value_code',v.value_code,
                            'display_name',v.display_name,
                            'aliases',v.aliases,
                            'canonical',v.canonical,
                            'active',v.active,
                            'source_reference',v.source_reference,
                            'metadata',v.metadata
                        )
                        order by
                            case when v.value_code='UNKNOWN' then 1 else 0 end,
                            v.display_name,
                            v.value_code
                    ) filter (where v.value_code is not null),
                    '[]'::jsonb
                ) as values
            from tcg.taxonomy_schemas s
            left join tcg.taxonomy_values v
              on v.system_code=s.system_code
             and v.scope_kind=s.scope_kind
             and v.dimension_code=s.dimension_code
            where s.system_code=$1
            group by
                s.scope_kind,s.dimension_code,s.display_name,s.cardinality,
                s.required_for_verified,s.official_source_url,s.metadata
            order by s.scope_kind,s.dimension_code
            """,
            code,
        )

    return jsonable_encoder(
        {
            "system": dict(system),
            "dimensions": [dict(row) for row in rows],
            "unknown_values_fail_closed": True,
        }
    )


@router.get("/identity/{catalogue_id}")
async def collectible_identity(
    catalogue_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Inspect the universal identity structure for one canonical catalogue product."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        product = await connection.fetchrow(
            """
            select
                p.id,p.identity_key,p.product_type,p.game,p.name,p.set_name,
                p.card_number,p.variant,p.rarity,p.language,p.created_at,
                pr.system_code,pr.collectible_type,pr.identity_status,
                pr.set_code,pr.printing_code,pr.release_region,pr.release_date,
                pr.attributes as profile_attributes,pr.version as profile_version
            from tcg.catalogue_products p
            left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
            where p.id=$1
            """,
            catalogue_id,
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Catalogue product not found")

        assignments = await connection.fetch(
            """
            select
                a.id,a.dimension_code,a.value_code,v.display_name,
                a.is_primary,a.verification_status,a.source_kind,
                a.source_reference,a.verified_by_user_id,a.verified_at,
                a.metadata,a.version,a.created_at,a.updated_at
            from tcg.catalogue_taxonomy_assignments a
            join tcg.taxonomy_values v
              on v.system_code=a.system_code
             and v.scope_kind=a.scope_kind
             and v.dimension_code=a.dimension_code
             and v.value_code=a.value_code
            where a.catalogue_id=$1
            order by a.dimension_code,a.is_primary desc,v.display_name
            """,
            catalogue_id,
        )

        provider_mappings = await connection.fetch(
            """
            select
                id,source_provider,provider_entity_type,provider_id,
                provider_variant_key,provider_language,source_reference,
                match_status,verification_basis,confidence,
                verified_by_user_id,verified_at,metadata,version,
                created_at,updated_at
            from tcg.provider_catalogue_mappings
            where catalogue_id=$1
            order by source_provider,provider_entity_type,provider_id
            """,
            catalogue_id,
        )

        card_printing = await connection.fetchrow(
            """
            select
                cp.catalogue_id,cp.system_code,cp.printing_key,
                cp.identity_status,cp.attributes,cp.version,
                g.id as gameplay_identity_id,g.native_identity_key,
                g.canonical_name,g.card_number as gameplay_card_number,
                g.identity_status as gameplay_identity_status,
                g.attributes as gameplay_attributes,g.version as gameplay_version
            from tcg.card_printings cp
            join tcg.card_gameplay_identities g on g.id=cp.gameplay_identity_id
            where cp.catalogue_id=$1
            """,
            catalogue_id,
        )

        sealed = await connection.fetchrow(
            """
            select
                catalogue_id,system_code,manufacturer_sku,barcode_gtin,
                identity_status,contents,attributes,version,
                created_at,updated_at
            from tcg.sealed_product_details
            where catalogue_id=$1
            """,
            catalogue_id,
        )

        comic = await connection.fetchrow(
            """
            select
                catalogue_id,system_code,series_title,volume_identifier,
                issue_number,printing_number,release_year,cover_code,
                cover_artist,barcode_gtin,identity_status,attributes,
                version,created_at,updated_at
            from tcg.comic_printing_details
            where catalogue_id=$1
            """,
            catalogue_id,
        )

        inventory = await connection.fetch(
            """
            select
                i.id,i.inventory_code,i.owner_id,o.display_name as owner_name,
                o.owner_type,i.status,i.acquisition_cost_minor,i.currency,
                i.condition,i.grading_company,i.grade,i.certificate_number,
                i.language,i.location,i.storage_location_id,i.seal_status,
                i.market_value_minor,i.recommended_retail_minor,
                i.store_price_minor,i.identity_confirmed,i.version
            from tcg.inventory_items i
            join tcg.owners o on o.id=i.owner_id
            where i.catalogue_id=$1
            order by i.status,i.inventory_code
            """,
            catalogue_id,
        )

    product_row = dict(product)
    profile = None
    if product_row.get("system_code"):
        profile = {
            "system_code": product_row.pop("system_code"),
            "collectible_type": product_row.pop("collectible_type"),
            "identity_status": product_row.pop("identity_status"),
            "set_code": product_row.pop("set_code"),
            "printing_code": product_row.pop("printing_code"),
            "release_region": product_row.pop("release_region"),
            "release_date": product_row.pop("release_date"),
            "attributes": product_row.pop("profile_attributes"),
            "version": product_row.pop("profile_version"),
        }
    else:
        for key in (
            "system_code","collectible_type","identity_status","set_code",
            "printing_code","release_region","release_date",
            "profile_attributes","profile_version",
        ):
            product_row.pop(key, None)

    return jsonable_encoder(
        {
            "catalogue_product": product_row,
            "profile": profile,
            "card_printing": dict(card_printing) if card_printing else None,
            "sealed_product": dict(sealed) if sealed else None,
            "comic_printing": dict(comic) if comic else None,
            "taxonomy": [dict(row) for row in assignments],
            "provider_mappings": [dict(row) for row in provider_mappings],
            "physical_inventory": [dict(row) for row in inventory],
            "legacy_fields_are_compatibility_only": True,
        }
    )
