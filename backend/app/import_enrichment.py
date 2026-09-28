from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated, Any, Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .action_required import resolve_action_required, upsert_action_required
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .free_canonical_media import (
    LEGAL_BASIS_URL as FREE_MEDIA_LEGAL_BASIS_URL,
    RIGHTS_BASIS as FREE_MEDIA_RIGHTS_BASIS,
    _resolve_one as resolve_free_media_one,
    _supported_provider as supported_free_provider,
)
from .identity_review import (
    _catalogue_snapshot,
    _identity_text,
    _physical_snapshot,
    _source_record_dict,
    _variant_equivalent,
    import_exact_evidence,
)
from .imported_benchmark_pricing import (
    _apply_one as apply_imported_benchmark_one,
    extract_imported_benchmark,
)
from .fx import EcbHistoricalFxProvider, FxQuote
from .language import clean_language, parse_title_language
from .media_resolver import physical_photo_policy
from .ownership import current_owner as _owner
from .punk_records_client import PunkRecordsClient
from .settings import get_settings
from .tcgdex_client import TcgDexClient
from .tcggraph_client import TcgGraphClient
from .tcggraph_media import (
    RIGHTS_BASIS as TCGGRAPH_RIGHTS_BASIS,
    TCGGRAPH_TERMS_URL,
    _lookup_one as lookup_tcggraph_one,
)


router = APIRouter(prefix="/api/v1/imports", tags=["import-enrichment"])


class ImportEnrichmentProcessRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    default_language: str | None = Field(default=None, max_length=80)
    retry_action_required: bool = False

    @model_validator(mode="after")
    def normalise(self) -> "ImportEnrichmentProcessRequest":
        self.default_language = clean_language(self.default_language)
        return self


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _inventory_action_key(inventory_id: UUID, code: str) -> str:
    return f"inventory:{inventory_id}:{code.casefold()}"


def _catalogue_action_key(catalogue_id: UUID, code: str) -> str:
    return f"catalogue:{catalogue_id}:{code.casefold()}"


def _unmarked_import_identity_evidence(
    row: Mapping[str, Any],
    *,
    default_language: str | None,
) -> dict[str, Any] | None:
    language = clean_language(default_language)
    if not language:
        return None

    source = _source_record_dict(row.get("source_record"))
    source_name, name_language = parse_title_language(source.get("Product Name"))
    source_set, set_language = parse_title_language(source.get("Set"))
    explicit_languages = {
        clean_language(value)
        for value in (name_language, set_language)
        if clean_language(value)
    }
    if explicit_languages:
        return None

    if _identity_text(source_name) != _identity_text(row.get("name")):
        return None
    if _identity_text(source_set) != _identity_text(row.get("set_name")):
        return None
    if _identity_text(source.get("Card Number")) != _identity_text(row.get("card_number")):
        return None
    if not _variant_equivalent(source.get("Variance"), row.get("variant")):
        return None

    current_language = clean_language(row.get("language"))
    if current_language and current_language != language:
        return None

    return {
        "verification_method": "IMPORT_DEFAULT_LANGUAGE",
        "language": language,
        "source_name": source.get("Product Name"),
        "source_set": source.get("Set"),
        "source_card_number": source.get("Card Number"),
        "source_variant": source.get("Variance"),
        "default_language_selected_by_admin": True,
    }


async def _confirm_identity(
    connection,
    *,
    owner_id: UUID,
    user_id: UUID,
    row: Mapping[str, Any],
    default_language: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if row.get("identity_confirmed"):
        return dict(row), {"verification_method": "EXISTING"}

    evidence = import_exact_evidence(row)
    if evidence is None:
        evidence = _unmarked_import_identity_evidence(
            row,
            default_language=default_language,
        )
    if evidence is None:
        return None, None

    updated = await connection.fetchrow(
        """
        update tcg.inventory_items
        set identity_confirmed=true,
            language=$1,
            version=version+1,
            updated_at=clock_timestamp()
        where id=$2
          and owner_id=$3
          and version=$4
          and not identity_confirmed
        returning *
        """,
        evidence["language"],
        row["id"],
        owner_id,
        row["version"],
    )
    if updated is None:
        refreshed = await connection.fetchrow(
            "select * from tcg.inventory_items where id=$1 and owner_id=$2",
            row["id"],
            owner_id,
        )
        if refreshed is not None and refreshed["identity_confirmed"]:
            return dict(refreshed), {"verification_method": "EXISTING"}
        raise HTTPException(
            status_code=409,
            detail="Inventory changed during enrichment identity confirmation",
        )

    physical_snapshot = _physical_snapshot(updated)
    physical_snapshot["verification_evidence"] = evidence
    await connection.execute(
        """
        insert into tcg.identity_verification_events(
            owner_id,inventory_id,catalogue_id,event_type,actor_user_id,
            verification_method,inventory_version,catalogue_snapshot,
            physical_snapshot,notes
        ) values(
            $1,$2,$3,'CONFIRMED',$4,$5,$6,$7::jsonb,$8::jsonb,$9
        )
        """,
        owner_id,
        updated["id"],
        row["catalogue_id"],
        user_id,
        evidence["verification_method"],
        updated["version"],
        json.dumps(_catalogue_snapshot(row)),
        json.dumps(physical_snapshot),
        (
            "Import enrichment exact identity confirmation using "
            + (
                "an explicit source language marker."
                if evidence["verification_method"] == "IMPORT_EXACT"
                else "the admin-selected default language for unmarked rows."
            )
        ),
    )
    return dict(updated), evidence


async def _existing_media(connection, catalogue_id: UUID) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        select *
        from tcg.media_assets
        where catalogue_id=$1
          and scope='CANONICAL_CARD'
          and side='FRONT'
          and source_status='ACTIVE'
          and revoked_at is null
        order by
          case approval_status when 'APPROVED' then 0 else 1 end,
          created_at desc,
          id
        """,
        catalogue_id,
    )
    return [dict(row) for row in rows]


def _media_status_from_assets(assets: list[dict[str, Any]]) -> str | None:
    if not assets:
        return None
    for asset in assets:
        if (
            asset.get("rights_tier") == "STOREFRONT_ALLOWED"
            and asset.get("rights_status") == "VERIFIED"
            and asset.get("approval_status") == "APPROVED"
        ):
            return "REFERENCE_READY"
    return "PENDING_REVIEW"


async def _insert_free_media(
    connection,
    *,
    owner_id: UUID,
    user_id: UUID,
    row: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    provider = str(result.get("provider") or "").strip()
    provider_id = str(result.get("provider_id") or "").strip()
    image_url = str(result.get("image_url") or "").strip()
    source_reference = str(result.get("source_reference") or "").strip()
    if not provider or not provider_id or not image_url.startswith("https://"):
        return None

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
        owner_id,
        row["catalogue_id"],
        provider,
        provider_id,
        source_reference,
        image_url,
        FREE_MEDIA_LEGAL_BASIS_URL,
        language,
        variant,
        FREE_MEDIA_RIGHTS_BASIS,
        alt_text,
        user_id,
        (
            "Exact deterministic provider match created by import enrichment: "
            f"{provider_id}"
        )[:1000],
    )
    return dict(asset) if asset is not None else None


async def _insert_tcggraph_media(
    connection,
    *,
    owner_id: UUID,
    user_id: UUID,
    row: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    provider_id = str(result.get("provider_id") or "").strip()
    image_url = str(result.get("image_url") or "").strip()
    if not provider_id or not image_url.startswith("https://"):
        return None

    finish_key = result.get("finish_key")
    provider_asset_id = f"{provider_id}:{finish_key}" if finish_key else provider_id
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
          alt_text,created_by_user_id,rights_verified_at,
          source_status,source_status_note,source_checked_at
        ) values(
          $1,$2,'CANONICAL_CARD','FRONT','LICENSED_PROVIDER',
          'INTERNAL_REFERENCE_ONLY','TCGGraph',$3,$4,$5,$6,$7,$8,
          'VERIFIED',$9,'PENDING',$10,$11,clock_timestamp(),
          'ACTIVE',$12,clock_timestamp()
        )
        on conflict do nothing
        returning *
        """,
        owner_id,
        row["catalogue_id"],
        provider_asset_id,
        source_reference,
        image_url,
        TCGGRAPH_TERMS_URL,
        language,
        variant,
        TCGGRAPH_RIGHTS_BASIS,
        alt_text,
        user_id,
        (
            "Exact TCGGraph reference candidate created by import enrichment; "
            "storefront rights remain unapproved."
        ),
    )
    return dict(asset) if asset is not None else None


async def _resolve_media_candidate(
    *,
    row: Mapping[str, Any],
    settings,
) -> tuple[str, dict[str, Any] | None, str | None]:
    language = clean_language(row.get("language") or row.get("catalogue_language"))
    if not language:
        return "NONE", None, "Card language is required before exact media resolution"

    free_provider = supported_free_provider(row.get("game"), language)
    if free_provider is not None:
        tcgdex = TcgDexClient()
        punk = PunkRecordsClient()
        resolved = await resolve_free_media_one(
            row,
            tcgdex=tcgdex,
            punk=punk,
            semaphore=asyncio.Semaphore(1),
        )
        result = _json_dict(resolved.get("result"))
        if result.get("resolved"):
            return "FREE", result, None

    if settings.tcggraph_api_key:
        client = TcgGraphClient(api_key=settings.tcggraph_api_key)
        resolved = await lookup_tcggraph_one(
            client,
            row,
            asyncio.Semaphore(1),
        )
        result = _json_dict(resolved.get("result"))
        if result.get("resolved"):
            return "TCGGRAPH", result, None
        return "NONE", None, str(result.get("reason") or "No exact TCGGraph match")

    if free_provider is not None:
        return "NONE", None, "No exact permitted provider image match"
    return (
        "NONE",
        None,
        "No permitted exact-image fallback is configured for this game/language",
    )


async def _refresh_item_row(connection, inventory_id: UUID, owner_id: UUID):
    return await connection.fetchrow(
        """
        select
            i.*,
            p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
            p.rarity,p.language as catalogue_language
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        where i.id=$1 and i.owner_id=$2
        """,
        inventory_id,
        owner_id,
    )


async def _process_one(
    request: Request,
    *,
    owner_id: UUID,
    user_id: UUID,
    enrichment_id: UUID,
    inventory_id: UUID,
    default_language: str | None,
    fx_cache: dict[str, FxQuote],
) -> dict[str, Any]:
    settings = get_settings()
    action_codes: list[str] = []
    metadata: dict[str, Any] = {}

    async with user_connection(
        request.app.state.db_pool,
        user_id,
        request.state.request_id,
    ) as connection:
        row = await _refresh_item_row(connection, inventory_id, owner_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Imported inventory item no longer exists")

        identity_row, identity_evidence = await _confirm_identity(
            connection,
            owner_id=owner_id,
            user_id=user_id,
            row=row,
            default_language=default_language,
        )
        if identity_row is None:
            identity_status = "ACTION_REQUIRED"
            code = "IDENTITY_REVIEW_REQUIRED"
            action_codes.append(code)
            await upsert_action_required(
                connection,
                owner_id=owner_id,
                category="IDENTITY",
                code=code,
                entity_type="INVENTORY_ITEM",
                entity_id=inventory_id,
                dedupe_key=_inventory_action_key(inventory_id, code),
                title="Confirm imported card identity",
                detail=(
                    "The import matches a canonical card, but Drop Rate does not "
                    "have enough explicit language/identity evidence to confirm the "
                    "physical copy automatically."
                ),
                recommended_action=(
                    "Confirm the card/language in Identity Review, or rerun import "
                    "enrichment with the correct default language for unmarked rows."
                ),
                metadata={
                    "catalogue_id": str(row["catalogue_id"]),
                    "game": row["game"],
                    "name": row["name"],
                    "set_name": row["set_name"],
                    "card_number": row["card_number"],
                    "variant": row["variant"],
                },
            )
        else:
            identity_status = "CONFIRMED"
            row = await _refresh_item_row(connection, inventory_id, owner_id)
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_inventory_action_key(inventory_id, "IDENTITY_REVIEW_REQUIRED"),
                actor_user_id=user_id,
            )
            metadata["identity_evidence"] = identity_evidence or {}

        current = dict(row)
        benchmark = extract_imported_benchmark(current.get("source_record"))
        if current.get("market_value_minor") is not None:
            pricing_status = "READY"
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_inventory_action_key(inventory_id, "PRICING_DATA_INSUFFICIENT"),
                actor_user_id=user_id,
            )
        elif current.get("identity_confirmed") and benchmark is not None:
            key = benchmark["observed_at"].date().isoformat()
            quote = fx_cache.get(key)
            if quote is None:
                provider = EcbHistoricalFxProvider()
                quote = await provider.quote(
                    base_currency="USD",
                    quote_currency="GBP",
                    at=benchmark["observed_at"],
                )
                fx_cache[key] = quote

            pricing_item = dict(current)
            pricing_item["benchmark"] = benchmark
            async with connection.transaction():
                priced = await apply_imported_benchmark_one(
                    connection,
                    owner_id=owner_id,
                    item=pricing_item,
                    fx_quote=quote,
                )
            pricing_status = "PROVISIONAL"
            metadata["pricing"] = priced
            current = dict(await _refresh_item_row(connection, inventory_id, owner_id))
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_inventory_action_key(inventory_id, "PRICING_DATA_INSUFFICIENT"),
                actor_user_id=user_id,
            )
        else:
            pricing_status = "ACTION_REQUIRED"
            code = "PRICING_DATA_INSUFFICIENT"
            action_codes.append(code)
            await upsert_action_required(
                connection,
                owner_id=owner_id,
                category="PRICING",
                code=code,
                entity_type="INVENTORY_ITEM",
                entity_id=inventory_id,
                dedupe_key=_inventory_action_key(inventory_id, code),
                title="Pricing evidence is incomplete",
                detail=(
                    "No usable current market value is available yet for this "
                    "physical item."
                ),
                recommended_action=(
                    "Confirm identity first, then run market-data/pricing enrichment."
                ),
                metadata={"catalogue_id": str(current["catalogue_id"])},
            )

        assets = await _existing_media(connection, current["catalogue_id"])
        existing_status = _media_status_from_assets(assets)
        media_status = existing_status or "PENDING"
        media_reason: str | None = None

    if existing_status is None:
        provider_type, provider_result, media_reason = await _resolve_media_candidate(
            row=current,
            settings=settings,
        )
        if provider_result is not None:
            async with user_connection(
                request.app.state.db_pool,
                user_id,
                request.state.request_id,
            ) as connection:
                if provider_type == "FREE":
                    await _insert_free_media(
                        connection,
                        owner_id=owner_id,
                        user_id=user_id,
                        row=current,
                        result=provider_result,
                    )
                else:
                    await _insert_tcggraph_media(
                        connection,
                        owner_id=owner_id,
                        user_id=user_id,
                        row=current,
                        result=provider_result,
                    )
                assets = await _existing_media(connection, current["catalogue_id"])
                media_status = _media_status_from_assets(assets) or "PENDING_REVIEW"
                metadata["media_provider"] = provider_result.get("provider") or provider_type
                metadata["media_provider_id"] = provider_result.get("provider_id")

    async with user_connection(
        request.app.state.db_pool,
        user_id,
        request.state.request_id,
    ) as connection:
        current = dict(await _refresh_item_row(connection, inventory_id, owner_id))
        policy = physical_photo_policy(
            current,
            threshold_minor=settings.media_physical_photo_threshold_minor,
        )
        physical_reasons = [
            reason
            for reason in policy["reasons"]
            if reason != "identity not confirmed"
        ]

        if physical_reasons and current.get("identity_confirmed"):
            media_status = "PHYSICAL_REQUIRED"
            code = "PHYSICAL_PHOTOS_REQUIRED"
            action_codes.append(code)
            await upsert_action_required(
                connection,
                owner_id=owner_id,
                category="MEDIA",
                code=code,
                severity="HIGH" if "graded card" in physical_reasons else "MEDIUM",
                entity_type="INVENTORY_ITEM",
                entity_id=inventory_id,
                dedupe_key=_inventory_action_key(inventory_id, code),
                title="Physical card photos required",
                detail="; ".join(physical_reasons),
                recommended_action=(
                    "Capture and approve front/back photos of this exact physical card."
                ),
                metadata={
                    "catalogue_id": str(current["catalogue_id"]),
                    "policy_reasons": physical_reasons,
                },
            )
        else:
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_inventory_action_key(inventory_id, "PHYSICAL_PHOTOS_REQUIRED"),
                actor_user_id=user_id,
            )

        if media_status == "PENDING_REVIEW":
            code = "MEDIA_REVIEW_REQUIRED"
            action_codes.append(code)
            await upsert_action_required(
                connection,
                owner_id=owner_id,
                category="MEDIA",
                code=code,
                entity_type="CATALOGUE_CARD",
                entity_id=current["catalogue_id"],
                dedupe_key=_catalogue_action_key(current["catalogue_id"], code),
                title="Review exact card image",
                detail=(
                    "An exact provider/reference image candidate was found but has "
                    "not yet been visually approved for this canonical printing."
                ),
                recommended_action=(
                    "Compare the image against card number, set, language and variant, "
                    "then approve or reject it in Media Review."
                ),
                metadata={
                    "game": current["game"],
                    "name": current["name"],
                    "set_name": current["set_name"],
                    "card_number": current["card_number"],
                    "variant": current["variant"],
                    "language": current.get("language") or current.get("catalogue_language"),
                },
            )
        elif media_status == "REFERENCE_READY":
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_catalogue_action_key(
                    current["catalogue_id"], "MEDIA_REVIEW_REQUIRED"
                ),
                actor_user_id=user_id,
            )
        elif media_status == "PENDING":
            media_status = "ACTION_REQUIRED"
            code = "MEDIA_UNRESOLVED"
            action_codes.append(code)
            await upsert_action_required(
                connection,
                owner_id=owner_id,
                category="MEDIA",
                code=code,
                entity_type="CATALOGUE_CARD",
                entity_id=current["catalogue_id"],
                dedupe_key=_catalogue_action_key(current["catalogue_id"], code),
                title="Exact card image unresolved",
                detail=media_reason or "No exact media candidate is currently available.",
                recommended_action=(
                    "Resolve the card through a permitted provider or capture the "
                    "physical card. Do not use a visually similar printing."
                ),
                metadata={
                    "game": current["game"],
                    "name": current["name"],
                    "set_name": current["set_name"],
                    "card_number": current["card_number"],
                    "variant": current["variant"],
                    "language": current.get("language") or current.get("catalogue_language"),
                    "tcggraph_configured": bool(settings.tcggraph_api_key),
                },
            )
        else:
            await resolve_action_required(
                connection,
                owner_id=owner_id,
                dedupe_key=_catalogue_action_key(current["catalogue_id"], "MEDIA_UNRESOLVED"),
                actor_user_id=user_id,
            )

        overall_status = "ACTION_REQUIRED" if action_codes else "COMPLETE"
        updated = await connection.fetchrow(
            """
            update tcg.import_enrichment_items
            set identity_status=$2,
                media_status=$3,
                pricing_status=$4,
                overall_status=$5,
                attempts=attempts+1,
                last_error=null,
                metadata=$6::jsonb,
                updated_at=clock_timestamp(),
                version=version+1
            where id=$1
            returning *
            """,
            enrichment_id,
            identity_status,
            media_status,
            pricing_status,
            overall_status,
            json.dumps(metadata),
        )
    return dict(updated)


async def _seed_batch(connection, *, batch_id: UUID, owner_id: UUID) -> int:
    result = await connection.execute(
        """
        insert into tcg.import_enrichment_items(
            batch_id,owner_id,inventory_id,catalogue_id
        )
        select
            i.import_batch_id,i.owner_id,i.id,i.catalogue_id
        from tcg.inventory_items i
        where i.import_batch_id=$1
          and i.owner_id=$2
        on conflict(batch_id,inventory_id) do nothing
        """,
        batch_id,
        owner_id,
    )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def _batch_row(connection, *, batch_id: UUID, owner_id: UUID):
    return await connection.fetchrow(
        """
        select id,status,adapter,filename,source_rows,physical_units,committed_at
        from tcg.import_batches
        where id=$1 and owner_id=$2
        """,
        batch_id,
        owner_id,
    )


async def _summary(connection, *, batch_id: UUID, owner_id: UUID) -> dict[str, Any]:
    rows = await connection.fetch(
        """
        select overall_status,count(*)::int as count
        from tcg.import_enrichment_items
        where batch_id=$1 and owner_id=$2
        group by overall_status
        order by overall_status
        """,
        batch_id,
        owner_id,
    )
    stage = await connection.fetchrow(
        """
        select
          count(*) filter(where identity_status='CONFIRMED')::int as identity_confirmed,
          count(*) filter(where identity_status='ACTION_REQUIRED')::int as identity_action,
          count(*) filter(where media_status='REFERENCE_READY')::int as media_ready,
          count(*) filter(where media_status='PENDING_REVIEW')::int as media_review,
          count(*) filter(where media_status='PHYSICAL_REQUIRED')::int as media_physical,
          count(*) filter(where media_status='ACTION_REQUIRED')::int as media_action,
          count(*) filter(where pricing_status in ('READY','PROVISIONAL'))::int as pricing_ready,
          count(*) filter(where pricing_status='ACTION_REQUIRED')::int as pricing_action,
          count(*)::int as total
        from tcg.import_enrichment_items
        where batch_id=$1 and owner_id=$2
        """,
        batch_id,
        owner_id,
    )
    return {
        "states": [dict(row) for row in rows],
        "stages": dict(stage) if stage is not None else {},
    }


@router.get("/{batch_id}/enrichment")
async def import_enrichment_status(
    batch_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        batch = await _batch_row(connection, batch_id=batch_id, owner_id=owner["id"])
        if batch is None:
            raise HTTPException(status_code=404, detail="Import batch not found")
        if batch["status"] != "COMMITTED":
            raise HTTPException(
                status_code=409,
                detail="Import enrichment requires a committed batch",
            )
        seeded = await _seed_batch(connection, batch_id=batch_id, owner_id=owner["id"])
        summary = await _summary(connection, batch_id=batch_id, owner_id=owner["id"])
    return jsonable_encoder(
        {
            "batch": dict(batch),
            "seeded": seeded,
            **summary,
        }
    )


@router.post("/{batch_id}/enrichment/process")
async def process_import_enrichment(
    batch_id: UUID,
    payload: ImportEnrichmentProcessRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]
        batch = await _batch_row(connection, batch_id=batch_id, owner_id=owner_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Import batch not found")
        if batch["status"] != "COMMITTED":
            raise HTTPException(
                status_code=409,
                detail="Import enrichment requires a committed batch",
            )
        await _seed_batch(connection, batch_id=batch_id, owner_id=owner_id)
        statuses = ["PENDING"]
        if payload.retry_action_required:
            statuses.append("ACTION_REQUIRED")
        rows = await connection.fetch(
            """
            select id,inventory_id
            from tcg.import_enrichment_items
            where batch_id=$1
              and owner_id=$2
              and overall_status=any($3::text[])
            order by updated_at,id
            limit $4
            """,
            batch_id,
            owner_id,
            statuses,
            payload.limit,
        )

    fx_cache: dict[str, FxQuote] = {}
    processed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in rows:
        try:
            result = await _process_one(
                request,
                owner_id=owner_id,
                user_id=user.user_id,
                enrichment_id=item["id"],
                inventory_id=item["inventory_id"],
                default_language=payload.default_language,
                fx_cache=fx_cache,
            )
            processed.append(result)
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            failures.append(
                {
                    "enrichment_id": str(item["id"]),
                    "inventory_id": str(item["inventory_id"]),
                    "detail": detail,
                }
            )
            async with user_connection(
                request.app.state.db_pool,
                user.user_id,
                request.state.request_id,
            ) as connection:
                await connection.execute(
                    """
                    update tcg.import_enrichment_items
                    set attempts=attempts+1,
                        last_error=$2,
                        updated_at=clock_timestamp(),
                        version=version+1
                    where id=$1
                    """,
                    item["id"],
                    str(detail)[:2000],
                )

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        summary = await _summary(connection, batch_id=batch_id, owner_id=owner_id)
        remaining = await connection.fetchval(
            """
            select count(*)::int
            from tcg.import_enrichment_items
            where batch_id=$1 and owner_id=$2 and overall_status='PENDING'
            """,
            batch_id,
            owner_id,
        )
    return jsonable_encoder(
        {
            "batch_id": batch_id,
            "processed_count": len(processed),
            "failed_count": len(failures),
            "remaining_pending": int(remaining or 0),
            "processed": processed,
            "failures": failures,
            **summary,
        }
    )
