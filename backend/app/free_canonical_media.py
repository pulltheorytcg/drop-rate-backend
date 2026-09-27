from __future__ import annotations

import asyncio
from typing import Annotated, Any, Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .language import clean_language
from .media_resolver import physical_photo_policy
from .ownership import current_owner as _owner
from .punk_records_client import (
    PUNK_RECORDS_REPO_URL,
    PunkRecordsClient,
    PunkRecordsError,
)
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .tcgdex_client import (
    TCGDEX_DATABASE_URL,
    TCGDEX_SOURCE_URL,
    TcgDexApiError,
    TcgDexClient,
)


router = APIRouter(prefix="/api/v1/media/free", tags=["media"])

LEGAL_BASIS_URL = "https://www.legislation.gov.uk/ukpga/1988/48/section/63"
RIGHTS_BASIS = (
    "Product-listing-only use to advertise the sale of genuine physical inventory "
    "under UK CDPA 1988 s63. Provider dataset licences do not grant ownership of "
    "underlying publisher artwork. Not approved for social, SEO artwork, merch, "
    "AI training or unrelated marketing."
)
FREE_MEDIA_MAX_CONCURRENCY = 8


class FreeMediaResolveRequest(BaseModel):
    apply: bool = False
    limit: int = Field(default=100, ge=1, le=100)
    catalogue_ids: list[UUID] | None = Field(default=None, max_length=100)


class FreeMediaShopifySyncRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=100)


class FreeMediaReviewRequest(BaseModel):
    version: int = Field(ge=1)
    decision: str = Field(pattern="^(APPROVE|REJECT)$")


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _supported_provider(game: object, language: object) -> str | None:
    normalized_game = _norm(game)
    normalized_language = clean_language(language)
    if normalized_language != "Japanese":
        return None
    if normalized_game in {"pokemon", "pokémon"}:
        return "TCGdex"
    if normalized_game in {"one piece", "one piece card game"}:
        return "Punk Records"
    return None


def _shopify_client() -> ShopifyAdminClient:
    settings = get_settings()
    if (
        not settings.shopify_shop_domain
        or not settings.shopify_client_id
        or not settings.shopify_client_secret
    ):
        raise HTTPException(status_code=409, detail="Shopify is not configured")
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


async def _resolve_one(
    row: Mapping[str, Any],
    *,
    tcgdex: TcgDexClient,
    punk: PunkRecordsClient,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    language = row.get("language") or row.get("catalogue_language")
    provider = _supported_provider(row.get("game"), language)
    if provider is None:
        return {
            **dict(row),
            "result": {
                "resolved": False,
                "reason": "no free exact-image provider for this game/language",
            },
        }

    async with semaphore:
        try:
            if provider == "TCGdex":
                result = await tcgdex.resolve_japanese_card(
                    set_name=str(row.get("set_name") or ""),
                    card_number=str(row.get("card_number") or ""),
                    variant=str(row.get("variant") or ""),
                )
            else:
                result = await punk.resolve_japanese_card(
                    card_number=str(row.get("card_number") or ""),
                    variant=str(row.get("variant") or ""),
                    name=str(row.get("name") or ""),
                )
        except (TcgDexApiError, PunkRecordsError) as exc:
            result = {
                "resolved": False,
                "reason": exc.detail,
                "retryable": exc.retryable,
                "provider_status_code": exc.status_code,
            }

    return {**dict(row), "result": result}


@router.get("/status")
async def free_media_status(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    return {
        "configured": True,
        "cost": "FREE",
        "api_key_required": False,
        "providers": [
            {
                "name": "TCGdex",
                "game": "Pokemon",
                "language": "Japanese",
                "source": TCGDEX_SOURCE_URL,
                "database": TCGDEX_DATABASE_URL,
            },
            {
                "name": "Punk Records",
                "game": "One Piece",
                "language": "Japanese",
                "source": PUNK_RECORDS_REPO_URL,
            },
        ],
        "legal_basis_url": LEGAL_BASIS_URL,
        "product_publications": 0,
    }


@router.post("/resolve")
async def resolve_free_canonical_media(
    payload: FreeMediaResolveRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        params: list[Any] = [owner["id"]]
        catalogue_filter = ""
        if payload.catalogue_ids:
            params.append(payload.catalogue_ids)
            catalogue_filter = f"and p.id = any(${len(params)}::uuid[])"
        params.append(payload.limit)
        limit_index = len(params)

        rows = await connection.fetch(
            f"""
            select distinct on (p.id)
                p.id as catalogue_id,p.product_type,p.game,p.name,p.set_name,
                p.card_number,p.variant,p.language as catalogue_language,
                i.language,i.store_price_minor,i.market_value_minor,
                i.recommended_retail_minor,i.condition,i.condition_review_status,
                i.grading_company,i.grade,i.identity_confirmed
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            left join tcg.listing_inventory_members lim
              on lim.inventory_id=i.id and lim.state <> 'REMOVED'
            where i.owner_id=$1
              and i.status='APPROVED'
              and p.product_type='CARD'
              and sil.id is null
              and lim.id is null
              {catalogue_filter}
              and not exists (
                select 1
                from tcg.media_assets m
                where m.catalogue_id=p.id
                  and m.scope='CANONICAL_CARD'
                  and m.side='FRONT'
                  and m.rights_tier='STOREFRONT_ALLOWED'
                  and m.source_status='ACTIVE'
                  and m.approval_status='APPROVED'
                  and m.rights_status='VERIFIED'
              )
            order by p.id,i.updated_at desc
            limit ${limit_index}
            """,
            *params,
        )

    eligible: list[dict[str, Any]] = []
    skipped_policy: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for source in rows:
        item = dict(source)
        policy = physical_photo_policy(
            item,
            threshold_minor=settings.media_physical_photo_threshold_minor,
        )
        if policy["physicalPhotosRequired"]:
            skipped_policy.append(
                {
                    "catalogue_id": str(item["catalogue_id"]),
                    "game": item["game"],
                    "name": item["name"],
                    "card_number": item["card_number"],
                    "reason": "physical photos required",
                    "policy_reasons": policy["reasons"],
                }
            )
            continue

        provider = _supported_provider(
            item.get("game"),
            item.get("language") or item.get("catalogue_language"),
        )
        if provider is None:
            unsupported.append(
                {
                    "catalogue_id": str(item["catalogue_id"]),
                    "game": item["game"],
                    "name": item["name"],
                    "card_number": item["card_number"],
                    "reason": "no free exact-image provider for this game/language",
                }
            )
            continue
        eligible.append(item)

    tcgdex = TcgDexClient()
    punk = PunkRecordsClient()
    semaphore = asyncio.Semaphore(FREE_MEDIA_MAX_CONCURRENCY)
    looked_up = await asyncio.gather(
        *[
            _resolve_one(
                row,
                tcgdex=tcgdex,
                punk=punk,
                semaphore=semaphore,
            )
            for row in eligible
        ]
    )

    resolved = [row for row in looked_up if row["result"].get("resolved")]
    unresolved = [row for row in looked_up if not row["result"].get("resolved")]
    inserted: list[dict[str, Any]] = []

    if payload.apply and resolved:
        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            owner = await _owner(connection)
            for row in resolved:
                result = row["result"]
                provider = str(result["provider"])
                provider_id = str(result["provider_id"])
                language = clean_language(
                    row.get("language") or row.get("catalogue_language")
                )
                variant = " ".join(str(row.get("variant") or "").strip().split())
                alt_text = " · ".join(
                    part
                    for part in (
                        str(row.get("name") or "").strip(),
                        str(row.get("set_name") or "").strip(),
                        str(row.get("card_number") or "").strip(),
                        language or "",
                    )
                    if part
                )[:500]

                source_note = (
                    f"Exact deterministic {provider} match · "
                    f"provider id {provider_id}"
                )
                asset = await connection.fetchrow(
                    """
                    insert into tcg.media_assets(
                      owner_id,catalogue_id,scope,side,source_type,rights_tier,
                      source_provider,provider_asset_id,source_reference,
                      public_source_url,permission_evidence_url,media_language,
                      media_variant,rights_status,rights_basis,approval_status,
                      alt_text,created_by_user_id,rights_verified_at,
                      source_status,source_status_note,source_checked_at
                    ) values(
                      $1,$2,'CANONICAL_CARD','FRONT','LICENSED_PROVIDER',
                      'STOREFRONT_ALLOWED',$3,$4,$5,$6,$7,$8,$9,
                      'VERIFIED',$10,'PENDING',$11,$12,clock_timestamp(),
                      'ACTIVE',$13,clock_timestamp()
                    )
                    on conflict do nothing
                    returning *
                    """,
                    owner["id"],
                    row["catalogue_id"],
                    provider,
                    provider_id,
                    str(result["source_reference"]),
                    str(result["image_url"]),
                    LEGAL_BASIS_URL,
                    language,
                    variant,
                    RIGHTS_BASIS,
                    alt_text,
                    user.user_id,
                    source_note[:1000],
                )
                if asset is not None:
                    inserted.append(dict(asset))

    def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(row["result"])
        return {
            "catalogue_id": str(row["catalogue_id"]),
            "game": row["game"],
            "name": row["name"],
            "set_name": row["set_name"],
            "card_number": row["card_number"],
            "variant": row["variant"],
            "language": row["language"] or row["catalogue_language"],
            "provider": result.get("provider"),
            "result": result,
        }

    provider_counts: dict[str, int] = {}
    for row in resolved:
        provider = str(row["result"].get("provider") or "Unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    return jsonable_encoder(
        {
            "apply": payload.apply,
            "cost": "FREE",
            "considered": len(rows),
            "eligible": len(eligible),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "unsupported": len(unsupported),
            "skipped_physical_policy": len(skipped_policy),
            "inserted": len(inserted),
            "provider_counts": provider_counts,
            "resolved_items": [public_row(row) for row in resolved],
            "unresolved_items": [public_row(row) for row in unresolved],
            "unsupported_items": unsupported,
            "skipped_items": skipped_policy,
            "product_publications": 0,
        }
    )


@router.get("/review-queue")
async def free_media_review_queue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Return free-provider canonical images enriched with inventory facts."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                m.id,m.version,m.catalogue_id,m.public_source_url,
                m.shopify_cdn_url,m.source_provider,m.provider_asset_id,
                m.source_reference,m.media_language,m.media_variant,
                m.approval_status,m.rights_status,m.source_status,
                m.shopify_file_status,m.created_at,m.approved_at,
                p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
                coalesce(m.media_language,p.language) as language,
                o.display_name as owner_name,o.owner_type,
                coalesce(s.copy_count,0) as copy_count,
                coalesce(s.inventory_codes,'{}'::text[]) as inventory_codes,
                coalesce(s.conditions,'{}'::text[]) as conditions,
                coalesce(s.grades,'{}'::text[]) as grades,
                coalesce(s.locations,'{}'::text[]) as locations,
                coalesce(s.inventory_statuses,'{}'::text[]) as inventory_statuses,
                s.min_store_price_minor,s.max_store_price_minor,
                s.min_market_value_minor,s.max_market_value_minor,
                s.min_acquisition_cost_minor,s.max_acquisition_cost_minor
            from tcg.media_assets m
            join tcg.catalogue_products p on p.id=m.catalogue_id
            join tcg.owners o on o.id=m.owner_id
            left join lateral (
                select
                    count(*)::integer as copy_count,
                    array_agg(i.inventory_code order by i.inventory_code) as inventory_codes,
                    array_agg(distinct i.condition)
                      filter (where i.condition is not null) as conditions,
                    array_agg(
                      distinct concat_ws(' ',i.grading_company,i.grade)
                    ) filter (
                      where nullif(btrim(coalesce(i.grading_company,'')),'') is not null
                         or nullif(btrim(coalesce(i.grade,'')),'') is not null
                    ) as grades,
                    array_agg(distinct i.location)
                      filter (where nullif(btrim(coalesce(i.location,'')),'') is not null) as locations,
                    array_agg(distinct i.status) as inventory_statuses,
                    min(i.store_price_minor) as min_store_price_minor,
                    max(i.store_price_minor) as max_store_price_minor,
                    min(i.market_value_minor) as min_market_value_minor,
                    max(i.market_value_minor) as max_market_value_minor,
                    min(i.acquisition_cost_minor) as min_acquisition_cost_minor,
                    max(i.acquisition_cost_minor) as max_acquisition_cost_minor
                from tcg.inventory_items i
                where i.owner_id=m.owner_id
                  and i.catalogue_id=m.catalogue_id
            ) s on true
            where m.owner_id=$1
              and m.scope='CANONICAL_CARD'
              and m.side='FRONT'
              and m.source_provider in ('TCGdex','Punk Records')
              and m.source_status='ACTIVE'
              and m.rights_status='VERIFIED'
            order by
              case m.approval_status
                when 'PENDING' then 0
                when 'APPROVED' then 1
                else 2
              end,
              p.game,p.set_name,p.card_number,p.name,m.created_at
            """,
            owner["id"],
        )

    items = [dict(row) for row in rows]
    return jsonable_encoder(
        {
            "items": items,
            "counts": {
                "total": len(items),
                "pending": sum(
                    1 for item in items
                    if item["approval_status"] == "PENDING"
                ),
                "approved": sum(
                    1 for item in items
                    if item["approval_status"] == "APPROVED"
                ),
                "rejected": sum(
                    1 for item in items
                    if item["approval_status"] == "REJECTED"
                ),
            },
            "shopify_sync_requires_human_approval": True,
        }
    )


@router.post("/review/{asset_id}")
async def review_free_canonical_media(
    asset_id: UUID,
    payload: FreeMediaReviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Human founder review of a deterministic free-provider image match."""

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        current = await connection.fetchrow(
            """
            select *
            from tcg.media_assets
            where id=$1
              and owner_id=$2
              and source_provider in ('TCGdex','Punk Records')
              and scope='CANONICAL_CARD'
              and side='FRONT'
            for update
            """,
            asset_id,
            owner["id"],
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Canonical media asset not found")
        if int(current["version"]) != payload.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Media asset changed",
                    "current_version": current["version"],
                },
            )
        if str(current["source_status"] or "") != "ACTIVE":
            raise HTTPException(
                status_code=422,
                detail="Inactive or revoked media cannot be reviewed",
            )
        if str(current["rights_status"] or "") != "VERIFIED":
            raise HTTPException(
                status_code=422,
                detail="Media rights must be verified before human review",
            )
        if (
            str(current["shopify_file_status"] or "") != "NOT_UPLOADED"
            and payload.decision == "REJECT"
        ):
            raise HTTPException(
                status_code=409,
                detail="Reject the image before it is synced to Shopify Files",
            )

        if payload.decision == "APPROVE":
            row = await connection.fetchrow(
                """
                update tcg.media_assets
                set approval_status='APPROVED',
                    approved_by_user_id=$4,
                    approved_at=clock_timestamp(),
                    source_status_note='Exact provider match visually verified by founder',
                    updated_at=clock_timestamp(),
                    version=version+1
                where id=$1 and owner_id=$2 and version=$3
                returning *
                """,
                asset_id, owner["id"], payload.version, user.user_id,
            )
        else:
            row = await connection.fetchrow(
                """
                update tcg.media_assets
                set approval_status='REJECTED',
                    approved_by_user_id=null,
                    approved_at=null,
                    source_status_note='Provider image rejected during founder visual review',
                    updated_at=clock_timestamp(),
                    version=version+1
                where id=$1 and owner_id=$2 and version=$3
                returning *
                """,
                asset_id, owner["id"], payload.version,
            )

        if row is None:
            raise HTTPException(status_code=409, detail="Media asset changed during review")
        return jsonable_encoder(
            {
                "asset": dict(row),
                "decision": payload.decision,
                "shopify_ready": (
                    payload.decision == "APPROVE"
                    and row["shopify_file_status"] == "READY"
                ),
            }
        )


@router.post("/sync-shopify")
async def sync_free_media_to_shopify(
    payload: FreeMediaShopifySyncRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Stage approved free-provider images into Shopify Files only."""

    client = _shopify_client()

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select *
            from tcg.media_assets
            where owner_id=$1
              and source_provider in ('TCGdex','Punk Records')
              and scope='CANONICAL_CARD'
              and side='FRONT'
              and rights_tier='STOREFRONT_ALLOWED'
              and source_status='ACTIVE'
              and approval_status='APPROVED'
              and rights_status='VERIFIED'
              and shopify_file_status in ('NOT_UPLOADED','UPLOADED','PROCESSING','READY')
              and (
                shopify_file_status <> 'READY'
                or nullif(btrim(coalesce(shopify_cdn_url,'')),'') is null
              )
            order by created_at,id
            limit $2
            """,
            owner["id"],
            payload.limit,
        )

    results: list[dict[str, Any]] = []
    for asset_row in rows:
        asset = dict(asset_row)
        status = str(asset.get("shopify_file_status") or "")
        source_url = str(asset.get("public_source_url") or "").strip()
        if not source_url.startswith("https://"):
            results.append(
                {
                    "asset_id": str(asset["id"]),
                    "provider": asset.get("source_provider"),
                    "status": "BLOCKED",
                    "reason": "missing HTTPS source image",
                }
            )
            continue

        try:
            if status == "NOT_UPLOADED":
                file_row = await client.create_file_from_url(
                    source_url=source_url,
                    alt_text=str(asset.get("alt_text") or ""),
                )
            else:
                file_id = str(asset.get("shopify_file_gid") or "").strip()
                if not file_id:
                    results.append(
                        {
                            "asset_id": str(asset["id"]),
                            "provider": asset.get("source_provider"),
                            "status": "BLOCKED",
                            "reason": "Shopify file ID missing",
                        }
                    )
                    continue
                file_row = await client.get_file(file_id)
        except ShopifyApiError as exc:
            results.append(
                {
                    "asset_id": str(asset["id"]),
                    "provider": asset.get("source_provider"),
                    "status": "FAILED",
                    "reason": "Shopify media request failed",
                    "retryable": exc.retryable,
                }
            )
            continue

        if not isinstance(file_row, dict):
            results.append(
                {
                    "asset_id": str(asset["id"]),
                    "provider": asset.get("source_provider"),
                    "status": "FAILED",
                    "reason": "invalid Shopify media response",
                }
            )
            continue

        file_id = str(file_row.get("id") or "").strip()
        file_status = str(file_row.get("fileStatus") or "").strip().upper()
        image = file_row.get("image")
        cdn_url = (
            str(image.get("url") or "").strip()
            if isinstance(image, dict)
            else ""
        )
        if not file_id or file_status not in {
            "UPLOADED",
            "PROCESSING",
            "READY",
            "FAILED",
        }:
            results.append(
                {
                    "asset_id": str(asset["id"]),
                    "provider": asset.get("source_provider"),
                    "status": "FAILED",
                    "reason": "unsupported Shopify file state",
                }
            )
            continue

        async with user_connection(
            request.app.state.db_pool,
            user.user_id,
            request.state.request_id,
        ) as connection:
            owner = await _owner(connection)
            updated = await connection.fetchrow(
                """
                update tcg.media_assets
                set shopify_file_gid=$3,
                    shopify_file_status=$4,
                    shopify_error=case
                      when $4='FAILED' then 'Shopify file processing failed'
                      else null
                    end,
                    shopify_cdn_url=case
                      when nullif($5,'') is not null then $5
                      else shopify_cdn_url
                    end,
                    source_checked_at=clock_timestamp(),
                    source_status_note='Free canonical image checked during Shopify file sync',
                    updated_at=clock_timestamp(),
                    version=version+1
                where id=$1
                  and owner_id=$2
                  and source_provider in ('TCGdex','Punk Records')
                returning *
                """,
                asset["id"],
                owner["id"],
                file_id,
                file_status,
                cdn_url,
            )
        results.append(
            {
                "asset_id": str(asset["id"]),
                "provider": asset.get("source_provider"),
                "status": file_status,
                "shopify_file_id": file_id,
                "shopify_cdn_url": (
                    str(updated["shopify_cdn_url"] or "")
                    if updated is not None
                    else cdn_url
                ),
            }
        )

    return jsonable_encoder(
        {
            "cost": "FREE",
            "considered": len(rows),
            "ready": sum(1 for row in results if row["status"] == "READY"),
            "processing": sum(
                1
                for row in results
                if row["status"] in {"UPLOADED", "PROCESSING"}
            ),
            "failed": sum(
                1
                for row in results
                if row["status"] in {"FAILED", "BLOCKED"}
            ),
            "items": results,
            "product_publications": 0,
        }
    )
