from __future__ import annotations

import asyncio
import re
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
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .tcggraph_client import TcgGraphApiError, TcgGraphClient


router = APIRouter(prefix="/api/v1/media/tcggraph", tags=["media"])


TCGGRAPH_TERMS_URL = "https://tcggraph.com/legal/terms"
RIGHTS_BASIS = (
    "TCGGraph API licence permits displaying and caching card images in Drop Rate; "
    "Drop Rate use is restricted to genuine-card product listings."
)

GAME_SLUGS = {
    "pokemon": "pokemon",
    "pokémon": "pokemon",
    "one piece": "one-piece",
    "one piece card game": "one-piece",
    "dragon ball": "dragon-ball-super",
    "dragon ball z": "dragon-ball-super",
    "dragon ball super": "dragon-ball-super",
}

LANGUAGE_CODES = {
    "english": "en",
    "en": "en",
    "japanese": "ja",
    "jp": "ja",
    "ja": "ja",
}

BASE_VARIANTS = {"", "normal", "base", "regular"}
FOIL_VARIANTS = {"holofoil", "holo", "foil"}
REVERSE_VARIANTS = {"reverse holofoil", "reverse holo", "reverse foil"}


class TcgGraphResolveRequest(BaseModel):
    apply: bool = False
    limit: int = Field(default=100, ge=1, le=100)
    catalogue_ids: list[UUID] | None = Field(default=None, max_length=100)


class TcgGraphShopifySyncRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value))


def _language_code(value: object) -> str | None:
    cleaned = clean_language(value)
    if cleaned:
        return LANGUAGE_CODES.get(cleaned.casefold())
    return LANGUAGE_CODES.get(_norm(value))


def _game_slug(value: object) -> str | None:
    return GAME_SLUGS.get(_norm(value))


def _collector_parts(value: object) -> tuple[str, str]:
    text = str(value or "").strip()
    if "_" in text:
        base, suffix = text.split("_", 1)
        return base.upper(), suffix.casefold()
    return text.upper(), ""


def _number_equivalent(left: object, right: object) -> bool:
    def canonical(value: object) -> str:
        text = str(value or "").strip().upper()
        chunks = re.split(r"([/-])", text)
        out: list[str] = []
        for chunk in chunks:
            if chunk.isdigit():
                out.append(str(int(chunk)))
            else:
                out.append(chunk)
        return "".join(out)
    return canonical(left) == canonical(right)


def _image_url(images: object) -> str | None:
    if not isinstance(images, Mapping):
        return None
    for key in ("large", "normal", "small"):
        value = images.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return None


def _printing_image(
    card: Mapping[str, Any],
    *,
    variant: str,
) -> tuple[str | None, str | None, str | None]:
    printings = card.get("printings")
    rows = [row for row in printings if isinstance(row, Mapping)] if isinstance(printings, list) else []

    normalized = _norm(variant)
    wanted: list[Mapping[str, Any]] = []
    if normalized in FOIL_VARIANTS:
        wanted = [
            row for row in rows
            if "foil" in _norm(row.get("key")) or "holo" in _norm(row.get("label"))
        ]
        wanted = [
            row for row in wanted
            if "reverse" not in _norm(row.get("key"))
            and "reverse" not in _norm(row.get("label"))
        ]
    elif normalized in REVERSE_VARIANTS:
        wanted = [
            row for row in rows
            if "reverse" in _norm(row.get("key"))
            or "reverse" in _norm(row.get("label"))
        ]
    elif normalized in BASE_VARIANTS:
        wanted = [
            row for row in rows
            if _norm(row.get("key")) in {"normal", "base"}
            or _norm(row.get("label")) in {"normal", "base"}
        ]

    if len(wanted) > 1:
        unique = {
            (_norm(row.get("key")), _image_url(row.get("images")))
            for row in wanted
        }
        if len(unique) > 1:
            return None, None, "multiple provider finishes match local variant"

    if wanted:
        row = wanted[0]
        url = _image_url(row.get("images")) or _image_url(card.get("images"))
        return url, str(row.get("key") or "").strip() or None, None

    if normalized in BASE_VARIANTS:
        return _image_url(card.get("images")), None, None
    return None, None, "provider finish does not match local variant"


def resolve_exact_card(
    local: Mapping[str, Any],
    provider_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return one exact provider image or a fail-closed reason."""

    game_slug = _game_slug(local.get("game"))
    language_code = _language_code(local.get("language") or local.get("catalogue_language"))
    if not game_slug:
        return {"resolved": False, "reason": "game is not supported by TCGGraph"}
    if not language_code:
        return {"resolved": False, "reason": "language is not supported by TCGGraph"}

    local_number = str(local.get("card_number") or "").strip()
    local_name = _compact(local.get("name"))
    local_variant = _norm(local.get("variant"))

    candidates: list[dict[str, Any]] = []
    for row in provider_rows:
        if _norm(row.get("game")) != game_slug:
            continue
        if _norm(row.get("language")) != language_code:
            continue
        if local_name and _compact(row.get("name")) != local_name:
            continue

        provider_number = str(row.get("collectorNumber") or "")
        provider_base, provider_suffix = _collector_parts(provider_number)
        if not _number_equivalent(provider_base, local_number):
            continue

        if game_slug in {"one-piece", "dragon-ball-super"}:
            if local_variant in BASE_VARIANTS and provider_suffix:
                continue
            if local_variant not in BASE_VARIANTS and not provider_suffix:
                continue

        candidates.append(row)

    if not candidates:
        return {"resolved": False, "reason": "no exact TCGGraph identity match"}

    matches: list[dict[str, Any]] = []
    failures: list[str] = []
    for card in candidates:
        image_url, finish_key, error = _printing_image(card, variant=local_variant)
        if error:
            failures.append(error)
            continue
        if not image_url:
            failures.append("TCGGraph record has no usable HTTPS image")
            continue
        provider_id = str(card.get("id") or card.get("cardId") or "").strip()
        if not provider_id:
            failures.append("TCGGraph record is missing a stable card ID")
            continue
        matches.append(
            {
                "provider_id": provider_id,
                "finish_key": finish_key,
                "image_url": image_url,
                "collector_number": card.get("collectorNumber"),
                "provider_set": (
                    card.get("set", {}).get("name")
                    if isinstance(card.get("set"), Mapping)
                    else None
                ),
                "provider_name": card.get("name"),
                "provider_language": card.get("language"),
            }
        )

    deduped: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for match in matches:
        key = (
            str(match["provider_id"]),
            match["finish_key"],
            str(match["image_url"]),
        )
        deduped[key] = match
    matches = list(deduped.values())

    if len(matches) == 1:
        return {"resolved": True, **matches[0]}
    if len(matches) > 1:
        return {
            "resolved": False,
            "reason": "multiple exact TCGGraph image candidates remain",
            "candidate_count": len(matches),
        }
    return {
        "resolved": False,
        "reason": failures[0] if failures else "TCGGraph candidate could not be resolved",
    }


async def _lookup_one(
    client: TcgGraphClient,
    row: Mapping[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    game_slug = _game_slug(row.get("game"))
    language_code = _language_code(row.get("language") or row.get("catalogue_language"))
    if not game_slug:
        return {**dict(row), "result": {"resolved": False, "reason": "unsupported game"}}
    if not language_code:
        return {**dict(row), "result": {"resolved": False, "reason": "unsupported language"}}

    # One Piece and Dragon Ball numbers encode the set and parallels use suffixes.
    # Pokémon numbers repeat between sets, so the set name remains mandatory.
    set_name = None if game_slug in {"one-piece", "dragon-ball-super"} else str(row.get("set_name") or "").strip()

    async with semaphore:
        try:
            cards = await client.list_cards(
                game=game_slug,
                collector_number=str(row.get("card_number") or ""),
                language=language_code,
                set_name=set_name,
                name=str(row.get("name") or ""),
                limit=100,
            )
        except TcgGraphApiError as exc:
            return {
                **dict(row),
                "result": {
                    "resolved": False,
                    "reason": exc.detail,
                    "retryable": exc.retryable,
                    "provider_status_code": exc.status_code,
                },
            }

    return {
        **dict(row),
        "result": resolve_exact_card(row, cards),
    }


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


@router.get("/status")
async def tcggraph_media_status(
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    return {
        "configured": bool(settings.tcggraph_api_key),
        "provider": "TCGGraph",
        "usage": "canonical product-listing images and deterministic identification",
        "supported_games": sorted(set(GAME_SLUGS.values())),
        "permission_evidence_url": TCGGRAPH_TERMS_URL,
    }


@router.post("/resolve")
async def resolve_tcggraph_media(
    payload: TcgGraphResolveRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.tcggraph_api_key:
        raise HTTPException(
            status_code=409,
            detail="TCGGraph is not configured. Add TCG_TCGGRAPH_API_KEY in Railway.",
        )

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
                    "name": item["name"],
                    "reason": "physical photos required",
                    "policy_reasons": policy["reasons"],
                }
            )
            continue
        eligible.append(item)

    client = TcgGraphClient(api_key=settings.tcggraph_api_key)
    semaphore = asyncio.Semaphore(settings.tcggraph_max_concurrency)
    looked_up = await asyncio.gather(
        *[_lookup_one(client, row, semaphore) for row in eligible]
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
                provider_id = str(result["provider_id"])
                finish_key = result.get("finish_key")
                provider_asset_id = (
                    f"{provider_id}:{finish_key}" if finish_key else provider_id
                )
                source_reference = f"tcggraph:{provider_asset_id}"
                language = clean_language(row.get("language") or row.get("catalogue_language"))
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

                asset = await connection.fetchrow(
                    """
                    insert into tcg.media_assets(
                      owner_id,catalogue_id,scope,side,source_type,rights_tier,
                      source_provider,provider_asset_id,source_reference,
                      public_source_url,permission_evidence_url,media_language,
                      media_variant,rights_status,rights_basis,approval_status,
                      alt_text,created_by_user_id,approved_by_user_id,approved_at,
                      rights_verified_at,source_status,source_status_note,
                      source_checked_at
                    ) values(
                      $1,$2,'CANONICAL_CARD','FRONT','LICENSED_PROVIDER',
                      'STOREFRONT_ALLOWED','TCGGraph',$3,$4,$5,$6,$7,$8,
                      'VERIFIED',$9,'APPROVED',$10,$11,$11,clock_timestamp(),
                      clock_timestamp(),'ACTIVE',$12,clock_timestamp()
                    )
                    on conflict do nothing
                    returning *
                    """,
                    owner["id"],
                    row["catalogue_id"],
                    provider_asset_id,
                    source_reference,
                    result["image_url"],
                    TCGGRAPH_TERMS_URL,
                    language,
                    variant,
                    RIGHTS_BASIS,
                    alt_text,
                    user.user_id,
                    (
                        "Exact deterministic TCGGraph match: "
                        f"{result.get('provider_name')} · "
                        f"{result.get('collector_number')} · "
                        f"{result.get('provider_language')}"
                    )[:1000],
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
            "result": result,
        }

    return jsonable_encoder(
        {
            "provider": "TCGGraph",
            "apply": payload.apply,
            "considered": len(rows),
            "eligible": len(eligible),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "skipped_physical_policy": len(skipped_policy),
            "inserted": len(inserted),
            "resolved_items": [public_row(row) for row in resolved],
            "unresolved_items": [public_row(row) for row in unresolved],
            "skipped_items": skipped_policy,
        }
    )


@router.post("/sync-shopify")
async def sync_tcggraph_media_to_shopify(
    payload: TcgGraphShopifySyncRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Bulk-stage approved TCGGraph images into Shopify Files.

    This never creates or publishes a Shopify product. It only advances the
    media registry toward READY so the existing product gate can use it.
    """

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
              and source_provider='TCGGraph'
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
                    source_status_note='TCGGraph image checked during Shopify file sync',
                    updated_at=clock_timestamp(),
                    version=version+1
                where id=$1
                  and owner_id=$2
                  and source_provider='TCGGraph'
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
            "provider": "TCGGraph",
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
