from __future__ import annotations

import json
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Mapping

from .language import clean_language
from .recognition_games import SYSTEM_BY_GAME, collector_key
from .recognition_vision import RecognitionObservation


def _text_key(value: object) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").split())


def _name_similarity(left: object, right: object) -> float:
    a = _text_key(left)
    b = _text_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _candidate_language(row: Mapping[str, Any]) -> str:
    for value in (
        row.get("language"),
        (row.get("sealed_attributes") or {}).get("language")
        if isinstance(row.get("sealed_attributes"), Mapping)
        else None,
        (row.get("profile_attributes") or {}).get("language")
        if isinstance(row.get("profile_attributes"), Mapping)
        else None,
    ):
        language = clean_language(value)
        if language:
            return language
    return ""


def _candidate_code_keys(row: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for value in (row.get("set_code"), row.get("manufacturer_sku")):
        key = collector_key(value)
        if key:
            keys.add(key)
    for attributes_key in ("sealed_attributes", "profile_attributes"):
        attributes = row.get(attributes_key)
        if not isinstance(attributes, Mapping):
            continue
        for field in ("set_code", "product_code", "manufacturer_sku"):
            key = collector_key(attributes.get(field))
            if key:
                keys.add(key)
    return keys


async def load_sealed_candidates(
    connection,
    observation: RecognitionObservation,
) -> list[dict[str, Any]]:
    system_code = SYSTEM_BY_GAME.get(observation.game)
    if not system_code:
        return []

    rows = await connection.fetch(
        """
        select
            p.id as catalogue_id,p.product_type,p.game,p.name,p.set_name,p.language,
            pr.system_code,pr.identity_status,pr.set_code,pr.release_region,
            pr.release_date,pr.attributes as profile_attributes,
            sd.manufacturer_sku,sd.identity_status as sealed_identity_status,
            sd.contents,sd.attributes as sealed_attributes,
            sealed_type.value_code as sealed_product_type,
            media.reference_image_url
        from tcg.catalogue_products p
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
        join tcg.sealed_product_details sd on sd.catalogue_id=p.id
        left join lateral (
            select a.value_code
            from tcg.catalogue_taxonomy_assignments a
            where a.catalogue_id=p.id
              and a.scope_kind='SEALED'
              and a.dimension_code='SEALED_TYPE'
            order by
                case when a.verification_status='VERIFIED' then 0 else 1 end,
                a.created_at desc
            limit 1
        ) sealed_type on true
        left join lateral (
            select coalesce(nullif(m.shopify_cdn_url,''),nullif(m.public_source_url,'')) as reference_image_url
            from tcg.media_assets m
            where m.catalogue_id=p.id
              and m.scope='CANONICAL_PRODUCT'
              and m.media_kind='IMAGE'
              and m.approval_status='APPROVED'
              and m.rights_status='VERIFIED'
              and m.rights_tier='STOREFRONT_ALLOWED'
              and m.source_status='ACTIVE'
              and m.revoked_at is null
            order by m.approved_at desc nulls last,m.created_at desc
            limit 1
        ) media on true
        where pr.system_code=$1
          and pr.collectible_type='SEALED'
          and p.product_type in ('SEALED','COLLECTION')
        order by p.name,p.id
        limit 250
        """,
        system_code,
    )
    return [dict(row) for row in rows]


def resolve_sealed_candidates(
    observation: RecognitionObservation,
    rows: list[Mapping[str, Any]],
    *,
    provider_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    observed_code = collector_key(observation.product_code)
    observed_language = clean_language(observation.language)
    observed_type = observation.sealed_product_type

    scored: list[dict[str, Any]] = []
    for row in rows:
        code_keys = _candidate_code_keys(row)
        candidate_language = _candidate_language(row)
        candidate_type = str(row.get("sealed_product_type") or "UNKNOWN").strip().upper()
        code_match = bool(observed_code and observed_code in code_keys)
        type_match = bool(
            observed_type != "UNKNOWN"
            and candidate_type != "UNKNOWN"
            and observed_type == candidate_type
        )
        language_match = bool(
            observed_language
            and candidate_language
            and observed_language == candidate_language
        )
        set_name_match = _name_similarity(observation.set_name_guess, row.get("set_name"))
        product_name_match = _name_similarity(observation.set_name_guess, row.get("name"))

        rejection_reasons: list[str] = []
        if (
            observed_code
            and observation.product_code_confidence >= 0.80
            and code_keys
            and not code_match
        ):
            rejection_reasons.append("sealed product code mismatch")
        if (
            observed_type != "UNKNOWN"
            and observation.sealed_product_type_confidence >= 0.80
            and candidate_type != "UNKNOWN"
            and not type_match
        ):
            rejection_reasons.append("sealed product type mismatch")
        if (
            observed_language
            and observation.language_confidence >= 0.85
            and candidate_language
            and not language_match
        ):
            rejection_reasons.append("sealed product language mismatch")

        identity_verified = (
            str(row.get("identity_status") or "") == "VERIFIED"
            and str(row.get("sealed_identity_status") or "") == "VERIFIED"
        )
        score = (
            (0.58 if code_match else 0.0)
            + (0.23 if type_match else 0.0)
            + (0.14 if language_match else 0.0)
            + 0.05 * max(set_name_match, product_name_match)
        )
        score = min(1.0, score)

        scored.append(
            {
                "candidate_key": f"catalogue:{row['catalogue_id']}",
                "source_kind": "CATALOGUE",
                "system_code": row["system_code"],
                "catalogue_id": row["catalogue_id"],
                "provider": None,
                "provider_id": None,
                "provider_language": candidate_language or None,
                "score": score,
                "hard_rejected": bool(rejection_reasons),
                "rejection_reasons": rejection_reasons,
                "signals": {
                    "object_type": {
                        "observed": observation.object_type,
                        "confidence": observation.object_type_confidence,
                        "candidate": "SEALED_PRODUCT",
                        "match": 1.0,
                    },
                    "product_code": {
                        "observed": observation.product_code,
                        "confidence": observation.product_code_confidence,
                        "candidate": sorted(code_keys),
                        "match": 1.0 if code_match else 0.0,
                    },
                    "sealed_product_type": {
                        "observed": observed_type,
                        "confidence": observation.sealed_product_type_confidence,
                        "candidate": candidate_type,
                        "match": 1.0 if type_match else 0.0,
                    },
                    "language": {
                        "observed": observed_language,
                        "confidence": observation.language_confidence,
                        "candidate": candidate_language,
                        "match": 1.0 if language_match else 0.0,
                    },
                    "identity_verified": identity_verified,
                },
                "candidate_snapshot": {
                    "game": row.get("game"),
                    "name": row.get("name"),
                    "set_name": row.get("set_name"),
                    "card_number": None,
                    "product_code": row.get("set_code") or row.get("manufacturer_sku"),
                    "product_type": row.get("product_type"),
                    "collectible_type": "SEALED",
                    "sealed_product_type": candidate_type,
                    "variant": None,
                    "rarity": None,
                    "language": candidate_language or row.get("language"),
                    "release_region": row.get("release_region"),
                    "release_date": row.get("release_date"),
                    "identity_status": row.get("identity_status"),
                    "reference_image_url": row.get("reference_image_url"),
                },
            }
        )

    local_signatures = {
        (
            collector_key(item.get("candidate_snapshot", {}).get("product_code")),
            str(
                item.get("candidate_snapshot", {}).get("sealed_product_type")
                or "UNKNOWN"
            ).strip().upper(),
        )
        for item in scored
        if item.get("source_kind") == "CATALOGUE"
        and not item.get("hard_rejected")
        and collector_key(item.get("candidate_snapshot", {}).get("product_code"))
    }

    for row in provider_rows or []:
        provider = str(row.get("provider") or "").strip()
        provider_id = str(row.get("provider_id") or "").strip()
        if not provider or not provider_id:
            continue

        candidate_type = str(
            row.get("sealed_product_type") or "UNKNOWN"
        ).strip().upper()
        provider_code = collector_key(row.get("product_code"))
        if provider_code and (provider_code, candidate_type) in local_signatures:
            # Retrieval-only provider evidence must not create a duplicate runner-up
            # that can demote an already verified local sealed identity.
            continue

        candidate_language = clean_language(row.get("language"))
        code_match = bool(observed_code and provider_code and observed_code == provider_code)
        type_match = bool(
            observed_type != "UNKNOWN"
            and candidate_type != "UNKNOWN"
            and observed_type == candidate_type
        )
        language_match = bool(
            observed_language
            and candidate_language
            and observed_language == candidate_language
        )
        name_match = max(
            _name_similarity(observation.set_name_guess, row.get("set_name")),
            _name_similarity(observation.set_name_guess, row.get("name")),
        )
        visual_raw = row.get("visual_similarity")
        visual_match = (
            max(0.0, min(1.0, float(visual_raw)))
            if visual_raw is not None
            else 0.0
        )

        rejection_reasons: list[str] = []
        if (
            observed_code
            and observation.product_code_confidence >= 0.80
            and provider_code
            and not code_match
        ):
            rejection_reasons.append("sealed product code mismatch")
        if (
            observed_type != "UNKNOWN"
            and observation.sealed_product_type_confidence >= 0.80
            and candidate_type != "UNKNOWN"
            and not type_match
        ):
            rejection_reasons.append("sealed product type mismatch")
        if (
            observed_language
            and observation.language_confidence >= 0.85
            and candidate_language
            and not language_match
        ):
            rejection_reasons.append("sealed product language mismatch")

        retrieval_score = max(
            0.0,
            min(1.0, float(row.get("retrieval_score") or 0.0)),
        )
        score = min(
            0.99,
            max(
                retrieval_score,
                (0.52 if code_match else 0.0)
                + (0.24 if type_match else 0.0)
                + (0.10 if language_match else 0.0)
                + 0.08 * name_match
                + 0.06 * visual_match,
            ),
        )
        scored.append(
            {
                "candidate_key": f"provider:{provider}:{provider_id}:sealed",
                "source_kind": "PROVIDER",
                "system_code": SYSTEM_BY_GAME.get(observation.game),
                "catalogue_id": None,
                "provider": provider,
                "provider_id": provider_id,
                "provider_language": candidate_language or None,
                "score": score,
                "hard_rejected": bool(rejection_reasons),
                "rejection_reasons": rejection_reasons,
                "signals": {
                    "object_type": {
                        "observed": observation.object_type,
                        "confidence": observation.object_type_confidence,
                        "candidate": "SEALED_PRODUCT",
                        "match": 1.0,
                    },
                    "product_code": {
                        "observed": observation.product_code,
                        "confidence": observation.product_code_confidence,
                        "candidate": [row.get("product_code")] if row.get("product_code") else [],
                        "match": 1.0 if code_match else 0.0,
                    },
                    "sealed_product_type": {
                        "observed": observed_type,
                        "confidence": observation.sealed_product_type_confidence,
                        "candidate": candidate_type,
                        "match": 1.0 if type_match else 0.0,
                    },
                    "language": {
                        "observed": observed_language,
                        "confidence": observation.language_confidence,
                        "candidate": candidate_language,
                        "match": 1.0 if language_match else 0.0,
                    },
                    "visual": {
                        "match": visual_match,
                        "available": visual_raw is not None,
                        "source": row.get("visual_similarity_source"),
                    },
                    "identity_verified": False,
                    "retrieval_only": True,
                },
                "candidate_snapshot": {
                    **dict(row),
                    "game": observation.game,
                    "card_number": None,
                    "product_type": "SEALED",
                    "collectible_type": "SEALED",
                    "sealed_product_type": candidate_type,
                    "language": candidate_language or observation.language,
                    "identity_status": "NEEDS_REVIEW",
                    "reference_image_url": row.get("image_url"),
                },
            }
        )

    scored.sort(
        key=lambda item: (
            bool(item["hard_rejected"]),
            -float(item["score"]),
            str(item["candidate_key"]),
        )
    )
    viable = [item for item in scored if not item["hard_rejected"]]
    top = viable[0] if viable else None
    runner = viable[1] if len(viable) > 1 else None
    margin = (
        max(0.0, float(top["score"]) - float(runner["score"]))
        if top and runner
        else (float(top["score"]) if top else 0.0)
    )

    if top is None:
        return {
            "decision": "NO_MATCH",
            "top": None,
            "runner_up": None,
            "margin": 0.0,
            "reasons": ["No sealed catalogue product matches the observed evidence."],
            "risk_flags": ["SEALED_REFERENCE_NOT_FOUND"],
            "candidates": scored,
        }

    signals = top["signals"]
    exact = (
        top.get("source_kind") == "CATALOGUE"
        and top.get("catalogue_id") is not None
        and observation.object_type == "SEALED_PRODUCT"
        and observation.object_type_confidence >= 0.90
        and observation.product_code_confidence >= 0.85
        and observation.sealed_product_type_confidence >= 0.80
        and observation.language_confidence >= 0.80
        and float(signals["product_code"]["match"]) == 1.0
        and float(signals["sealed_product_type"]["match"]) == 1.0
        and float(signals["language"]["match"]) == 1.0
        and bool(signals["identity_verified"])
        and (runner is None or margin >= 0.10)
    )

    if exact:
        return {
            "decision": "EXACT_CANDIDATE",
            "top": top,
            "runner_up": runner,
            "margin": margin,
            "reasons": [
                "Verified sealed identity matches the visible product code, sealed format and language."
            ],
            "risk_flags": [],
            "candidates": scored,
        }

    reasons: list[str] = []
    risks: list[str] = []
    if top.get("source_kind") == "PROVIDER":
        reasons.append(
            "A provider-backed sealed product is plausible but is not yet a verified Drop Rate catalogue identity."
        )
        risks.append("UNMAPPED_SEALED_PROVIDER_CANDIDATE")
    if observation.object_type_confidence < 0.90:
        reasons.append("Sealed-product classification confidence is below the exact-match gate.")
        risks.append("OBJECT_TYPE_UNCERTAIN")
    if not observation.product_code or observation.product_code_confidence < 0.85:
        reasons.append("A high-confidence sealed product/set code is required for exact matching.")
        risks.append("SEALED_PRODUCT_CODE_UNRESOLVED")
    elif float(signals["product_code"]["match"]) < 1.0:
        reasons.append("The observed product code does not exactly match the leading sealed product.")
        risks.append("SEALED_PRODUCT_CODE_CONFLICT")
    if observation.sealed_product_type_confidence < 0.80 or float(signals["sealed_product_type"]["match"]) < 1.0:
        reasons.append("Booster pack/box/deck format is not resolved strongly enough.")
        risks.append("SEALED_TYPE_UNRESOLVED")
    if observation.language_confidence < 0.80 or float(signals["language"]["match"]) < 1.0:
        reasons.append("Physical product language is not resolved strongly enough.")
        risks.append("SEALED_LANGUAGE_UNRESOLVED")
    if not bool(signals["identity_verified"]):
        reasons.append("The sealed catalogue identity is not yet verified.")
        risks.append("SEALED_IDENTITY_UNVERIFIED")
    if runner is not None and margin < 0.10:
        reasons.append("More than one sealed product remains plausible.")
        risks.append("AMBIGUOUS_SEALED_PRODUCT")

    return {
        "decision": "NEEDS_REVIEW",
        "top": top,
        "runner_up": runner,
        "margin": margin,
        "reasons": reasons or ["Sealed product evidence requires review."],
        "risk_flags": list(dict.fromkeys(risks)),
        "candidates": scored,
    }


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


async def persist_sealed_resolution(
    connection,
    *,
    run_id,
    owner_id,
    observation: RecognitionObservation,
    resolved: Mapping[str, Any],
    timings_ms: Mapping[str, float],
) -> None:
    candidates = list(resolved.get("candidates") or [])
    top = resolved.get("top")
    runner = resolved.get("runner_up")
    async with connection.transaction():
        for index, candidate in enumerate(candidates[:25], start=1):
            await connection.execute(
                """
                insert into tcg.recognition_candidates(
                    run_id,candidate_key,source_kind,system_code,catalogue_id,
                    provider,provider_id,provider_language,rank,score,
                    hard_rejected,rejection_reasons,signals,candidate_snapshot
                ) values(
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                    $12::jsonb,$13::jsonb,$14::jsonb
                )
                """,
                run_id,
                str(candidate["candidate_key"]),
                str(candidate["source_kind"]),
                str(candidate["system_code"]),
                candidate.get("catalogue_id"),
                candidate.get("provider"),
                candidate.get("provider_id"),
                candidate.get("provider_language"),
                index,
                _decimal(candidate.get("score")),
                bool(candidate.get("hard_rejected")),
                json.dumps(candidate.get("rejection_reasons") or []),
                json.dumps(candidate.get("signals") or {}),
                json.dumps(candidate.get("candidate_snapshot") or {}, default=str),
            )

        await connection.execute(
            """
            update tcg.recognition_runs
            set status=$1,decision=$1,ai_observation=$2::jsonb,
                provider_evidence=$3::jsonb,top_catalogue_id=$4,top_score=$5,
                runner_up_score=$6,score_margin=$7,decision_reasons=$8::jsonb,
                risk_flags=$9::jsonb,completed_at=clock_timestamp(),
                updated_at=clock_timestamp(),version=version+1
            where id=$10 and owner_id=$11
            """,
            resolved["decision"],
            json.dumps(observation.model_dump(mode="json")),
            json.dumps(
                {"route": "SEALED_PRODUCT", "timings_ms": dict(timings_ms)},
                default=str,
            ),
            top.get("catalogue_id") if top else None,
            _decimal(top.get("score")) if top else None,
            _decimal(runner.get("score")) if runner else None,
            _decimal(resolved.get("margin")),
            json.dumps(resolved.get("reasons") or []),
            json.dumps(resolved.get("risk_flags") or []),
            run_id,
            owner_id,
        )
