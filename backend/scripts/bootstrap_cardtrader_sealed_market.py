from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.cardtrader_client import CardTraderClient
from app.cardtrader_market_adapter import CardTraderMarketAdapter
from app.cardtrader_recognition import discover_one_piece_cardtrader_sealed_candidates
from app.db import create_pool, user_connection
from app.fx import EcbHistoricalFxProvider
from app.market_ingestion import persist_source_evidence
from app.pricing import _recalculate_one
from app.recognition_vision import RecognitionObservation
from app.settings import get_settings


DEFAULT_IDENTITY_KEY = "sealed:v1:one_piece_card_game:op17:booster_pack:jp"
DEFAULT_VARIANT = "BOOSTER_PACK:JP:SINGLE_UNIT"


def _uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be a UUID") from exc


def _observation(*, product_code: str, set_name: str, language: str) -> RecognitionObservation:
    return RecognitionObservation(
        object_type="SEALED_PRODUCT",
        object_type_confidence=1.0,
        sealed_product_type="BOOSTER_PACK",
        sealed_product_type_confidence=1.0,
        product_code=product_code,
        product_code_confidence=1.0,
        game="One Piece",
        game_confidence=1.0,
        language=language,
        language_confidence=1.0,
        name_guess="",
        name_confidence=0.0,
        set_name_guess=set_name,
        set_name_confidence=1.0,
        card_number="",
        card_number_confidence=0.0,
        cost=None,
        cost_confidence=0.0,
        power=None,
        power_confidence=0.0,
        colors=[],
        colors_confidence=0.0,
        attributes=[],
        attributes_confidence=0.0,
        traits=[],
        traits_confidence=0.0,
        effect_text="",
        effect_confidence=0.0,
        rarity_text="",
        rarity_confidence=0.0,
        card_type_text="",
        card_type_confidence=0.0,
        art_treatment_text="",
        art_treatment_confidence=0.0,
        finish_text="",
        finish_confidence=0.0,
        visible_markers=[product_code],
        ocr_lines=[product_code],
        image_quality="GOOD",
        counterfeit_concerns=[],
        notes=[],
    )


def _eligible_marketplace_rows(rows: list[dict]) -> list[dict]:
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("on_vacation") is True:
            continue
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        if user.get("on_vacation") is True:
            continue
        try:
            quantity = int(row.get("quantity") or 0)
            bundle_size = int(row.get("bundle_size"))
        except (TypeError, ValueError):
            continue
        price = row.get("price")
        if not isinstance(price, dict):
            continue
        try:
            cents = int(price.get("cents") or 0)
        except (TypeError, ValueError):
            continue
        if quantity < 1 or bundle_size != 1 or cents <= 0:
            continue
        eligible.append(row)
    return eligible


async def _verified_catalogue(connection, identity_key: str) -> dict:
    row = await connection.fetchrow(
        """
        select p.id,p.name,p.set_name,p.language,pr.set_code,
               pr.identity_status,pr.collectible_type,
               sd.identity_status as sealed_identity_status,
               sealed_type.value_code as sealed_product_type
        from tcg.catalogue_products p
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
        join tcg.sealed_product_details sd on sd.catalogue_id=p.id
        left join lateral (
          select a.value_code
          from tcg.catalogue_taxonomy_assignments a
          where a.catalogue_id=p.id
            and a.scope_kind='SEALED'
            and a.dimension_code='SEALED_TYPE'
          order by (a.verification_status='VERIFIED') desc,a.created_at desc
          limit 1
        ) sealed_type on true
        where p.identity_key=$1
        """,
        identity_key,
    )
    if row is None:
        raise RuntimeError("Canonical sealed product was not found")
    data = dict(row)
    if (
        data["collectible_type"] != "SEALED"
        or data["sealed_product_type"] != "BOOSTER_PACK"
        or data["identity_status"] != "VERIFIED"
        or data["sealed_identity_status"] != "VERIFIED"
        or data["language"] != "Japanese"
    ):
        raise RuntimeError("Canonical sealed identity does not satisfy the verified JP booster-pack gate")
    return data


async def _authorised_owner(connection, *, owner_id: UUID, actor_user_id: UUID) -> None:
    allowed = await connection.fetchval(
        """
        select exists(
          select 1
          from tcg.owner_memberships
          where owner_id=$1
            and user_id=$2
            and active=true
            and role in ('PLATFORM_ADMIN','OWNER')
        )
        """,
        owner_id,
        actor_user_id,
    )
    if not allowed:
        raise RuntimeError("Actor is not authorised for the target owner")


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically bootstrap CardTrader single-pack market evidence."
    )
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--identity-key", default=DEFAULT_IDENTITY_KEY)
    args = parser.parse_args()

    owner_id = _uuid(args.owner_id, "--owner-id")
    actor_user_id = _uuid(args.actor_user_id, "--actor-user-id")
    settings = get_settings()
    if not settings.cardtrader_api_token:
        raise SystemExit("TCG_CARDTRADER_API_TOKEN is required")

    pool = await create_pool(settings)
    request_id = f"cardtrader-sealed-market-bootstrap:{uuid4()}"
    try:
        async with user_connection(pool, actor_user_id, request_id) as connection:
            await _authorised_owner(
                connection,
                owner_id=owner_id,
                actor_user_id=actor_user_id,
            )
            catalogue = await _verified_catalogue(connection, args.identity_key)
            started_at = await connection.fetchval("select clock_timestamp()")

        client = CardTraderClient(api_token=settings.cardtrader_api_token)
        observed = _observation(
            product_code=str(catalogue["set_code"]),
            set_name=str(catalogue["set_name"]),
            language=str(catalogue["language"]),
        )
        candidates = await discover_one_piece_cardtrader_sealed_candidates(
            observed,
            client,
            max_expansions=2,
            max_candidates=12,
        )

        viable: list[tuple[dict, list[dict]]] = []
        for candidate in candidates:
            if candidate.get("sealed_product_type") != "BOOSTER_PACK":
                continue
            provider_id = str(candidate.get("provider_id") or "")
            if not provider_id.isdigit():
                continue
            marketplace = await client.list_marketplace_products(
                blueprint_id=int(provider_id),
                language="jp",
            )
            eligible = _eligible_marketplace_rows(marketplace)
            if eligible:
                viable.append((candidate, eligible))

        if len(viable) != 1:
            summary = [
                {
                    "provider_id": item.get("provider_id"),
                    "name": item.get("name"),
                    "product_code": item.get("product_code"),
                    "single_unit_jp_listing_count": len(rows),
                }
                for item, rows in viable
            ]
            raise RuntimeError(
                "CardTrader sealed bootstrap requires exactly one JP single-pack blueprint; "
                + json.dumps(summary, ensure_ascii=False)
            )

        candidate, _preview_rows = viable[0]
        blueprint_id = str(candidate["provider_id"])
        adapter = CardTraderMarketAdapter(
            client=client,
            fx_provider=EcbHistoricalFxProvider(),
        )
        observations = await adapter.fetch_observations(
            catalogue_id=str(catalogue["id"]),
            source_product_id=blueprint_id,
            source_variant_id=DEFAULT_VARIANT,
        )
        if not observations:
            raise RuntimeError("CardTrader returned no acceptable JP single-pack market observations")

        async with user_connection(pool, actor_user_id, request_id) as connection:
            existing = await connection.fetchrow(
                """
                select id,catalogue_id,source,source_product_id,source_variant_id,
                       match_status,version
                from tcg.market_source_mappings
                where catalogue_id=$1 and source='CARDTRADER'
                """,
                catalogue["id"],
            )
            if existing is None:
                mapping = await connection.fetchrow(
                    """
                    insert into tcg.market_source_mappings(
                        catalogue_id,source,source_product_id,source_variant_id,
                        match_status,match_confidence,metadata
                    ) values(
                        $1,'CARDTRADER',$2,$3,'VERIFIED',1.0000,$4::jsonb
                    )
                    returning id,catalogue_id,source,source_product_id,
                              source_variant_id,match_status,version
                    """,
                    catalogue["id"],
                    blueprint_id,
                    DEFAULT_VARIANT,
                    json.dumps(
                        {
                            "verification_basis": "DETERMINISTIC_EXACT_SEALED_BOOTSTRAP",
                            "provider": "CardTrader",
                            "product_code": catalogue["set_code"],
                            "sealed_product_type": "BOOSTER_PACK",
                            "physical_language": "Japanese",
                            "single_unit_marketplace_required": True,
                            "candidate_name": candidate.get("name"),
                            "candidate_set_name": candidate.get("set_name"),
                        },
                        ensure_ascii=False,
                    ),
                )
            else:
                mapping = existing
                if (
                    str(mapping["source_product_id"]) != blueprint_id
                    or str(mapping["source_variant_id"] or "") != DEFAULT_VARIANT
                    or mapping["match_status"] != "VERIFIED"
                ):
                    raise RuntimeError("Existing CardTrader mapping conflicts with deterministic bootstrap")

            mapping_snapshot = dict(mapping)
            result = await persist_source_evidence(
                connection,
                owner_id=owner_id,
                source="CARDTRADER",
                trigger_type="MANUAL",
                mapping_results=[
                    {
                        "mapping": mapping_snapshot,
                        "observations": observations,
                        "error": None,
                    }
                ],
                fetched_count=len(observations),
                started_at=started_at,
            )

            inventory_rows = await connection.fetch(
                """
                select id
                from tcg.inventory_items
                where owner_id=$1
                  and catalogue_id=$2
                  and identity_confirmed=true
                  and status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                order by created_at,id
                """,
                owner_id,
                catalogue["id"],
            )
            priced = []
            for row in inventory_rows:
                priced.append(
                    await _recalculate_one(
                        connection,
                        owner_id,
                        row["id"],
                    )
                )

        print(
            "CARDTRADER_SEALED_MARKET_BOOTSTRAP="
            + json.dumps(
                {
                    "status": "OK",
                    "catalogue": {
                        "name": catalogue["name"],
                        "language": catalogue["language"],
                        "set_code": catalogue["set_code"],
                    },
                    "provider": {
                        "source": "CARDTRADER",
                        "blueprint_id": blueprint_id,
                        "candidate_name": candidate.get("name"),
                    },
                    "ingestion": {
                        "status": result.get("status"),
                        "fetched_count": result.get("fetched_count"),
                        "inserted_count": result.get("inserted_count"),
                        "duplicate_count": result.get("duplicate_count"),
                        "failed_mapping_count": result.get("failed_mapping_count"),
                    },
                    "priced_inventory_count": len(priced),
                },
                default=str,
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    finally:
        await pool.close()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
