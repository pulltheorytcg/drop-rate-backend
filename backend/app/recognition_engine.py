from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from typing import Any, Mapping

from .language import clean_language
from .punk_records_client import PunkRecordsClient, PunkRecordsError
from .recognition_images import hash_similarity, reference_image_hashes
from .recognition_vision import RecognitionObservation
from .tcgdex_client import TcgDexApiError, TcgDexClient


SYSTEM_BY_GAME = {
    "Pokemon": "POKEMON_TCG",
    "One Piece": "ONE_PIECE_CARD_GAME",
}

WEIGHTS = {
    "game": 0.08,
    "card_number": 0.32,
    "language": 0.14,
    "name": 0.12,
    "set": 0.08,
    "rarity": 0.05,
    "card_type": 0.03,
    "art": 0.06,
    "finish": 0.02,
    "provider": 0.04,
    "visual": 0.06,
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _ratio(left: object, right: object) -> float:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _name_core(value: object) -> str:
    text = _norm(value)
    text = re.sub(
        r"\((?:parallel|alternate art|alt art|manga|sp|reprint|\d+)\)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:parallel|alternate art|alt art|manga|reprint)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text


def _alias(value: object) -> str:
    text = _norm(value)
    aliases = {
        "holo": "holofoil",
        "foil": "holofoil",
        "reverse holo": "reverse holofoil",
        "reverse foil": "reverse holofoil",
        "regular": "normal",
        "base": "normal",
        "alt art": "alternate art",
        "alt-art": "alternate art",
        "super parallel": "manga",
        "secret rare": "sec",
        "super rare": "sr",
        "uncommon": "uc",
        "common": "c",
        "rare": "r",
        "leader": "leader",
        "don": "don!!",
    }
    return aliases.get(text, text)


def _taxonomy(candidate: Mapping[str, Any], dimension: str) -> list[str]:
    values: list[str] = []
    raw = candidate.get("taxonomy")
    if not isinstance(raw, list):
        return values
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("dimension_code") or "") != dimension:
            continue
        for key in ("value_code", "display_name"):
            value = str(item.get(key) or "").strip()
            if value and value != "UNKNOWN":
                values.append(value)
    return list(dict.fromkeys(values))


def _candidate_art(candidate: Mapping[str, Any]) -> list[str]:
    values = _taxonomy(candidate, "ART_TREATMENT")
    name = _norm(candidate.get("name"))
    provider_id = _norm(candidate.get("provider_asset_id"))
    if "manga" in name or "super parallel" in name:
        values.extend(["Manga", "Super Parallel"])
    if "alternate art" in name or "alt art" in name:
        values.append("Alternate Art")
    if "parallel" in name:
        values.append("Parallel")
    if provider_id and re.search(r"_p\d+$", provider_id):
        values.append("Parallel")
    if not values and not any(
        marker in name for marker in ("parallel", "alternate art", "alt art", "manga")
    ):
        values.append("Base")
    return list(dict.fromkeys(values))


def _candidate_finish(candidate: Mapping[str, Any]) -> list[str]:
    values = _taxonomy(candidate, "FINISH")
    variant = str(candidate.get("variant") or "").strip()
    if variant:
        values.append(variant)
    return list(dict.fromkeys(values))


def _candidate_rarity(candidate: Mapping[str, Any]) -> list[str]:
    values = _taxonomy(candidate, "RARITY")
    rarity = str(candidate.get("rarity") or "").strip()
    if rarity:
        values.append(rarity)
    return list(dict.fromkeys(values))


def _candidate_type(candidate: Mapping[str, Any]) -> list[str]:
    return _taxonomy(candidate, "CARD_TYPE")


def _best_alias_match(observed: object, values: list[str]) -> float:
    wanted = _alias(observed)
    if not wanted or not values:
        return 0.0
    scores = []
    for value in values:
        candidate = _alias(value)
        if candidate == wanted:
            scores.append(1.0)
        else:
            scores.append(_ratio(wanted, candidate))
    return max(scores, default=0.0)


def _candidate_language(candidate: Mapping[str, Any]) -> str | None:
    direct = clean_language(candidate.get("language"))
    if direct:
        return direct
    languages = candidate.get("inventory_languages")
    if isinstance(languages, list):
        cleaned = {
            clean_language(value)
            for value in languages
            if clean_language(value)
        }
        if len(cleaned) == 1:
            return next(iter(cleaned))
    return clean_language(candidate.get("media_language"))


def _provider_keys(provider_evidence: list[Mapping[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for item in provider_evidence:
        provider = str(item.get("provider") or "").strip()
        provider_id = str(item.get("provider_id") or "").strip()
        if provider and provider_id:
            keys.add((provider.casefold(), provider_id.casefold()))
    return keys


def _candidate_provider_keys(candidate: Mapping[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    provider = str(candidate.get("source_provider") or "").strip()
    provider_id = str(candidate.get("provider_asset_id") or "").strip()
    if provider and provider_id:
        keys.add((provider.casefold(), provider_id.casefold()))
    mappings = candidate.get("provider_mappings")
    if isinstance(mappings, list):
        for item in mappings:
            if not isinstance(item, Mapping):
                continue
            p = str(item.get("source_provider") or "").strip()
            pid = str(item.get("provider_id") or "").strip()
            if p and pid and str(item.get("match_status") or "") != "REJECTED":
                keys.add((p.casefold(), pid.casefold()))
    return keys


def score_candidate(
    observation: RecognitionObservation,
    candidate: Mapping[str, Any],
    *,
    provider_evidence: list[Mapping[str, Any]] | None = None,
    visual_similarity: float | None = None,
) -> dict[str, Any]:
    provider_evidence = provider_evidence or []
    signals: dict[str, Any] = {}
    hard_rejections: list[str] = []
    contribution = 0.0

    expected_system = SYSTEM_BY_GAME.get(observation.game)
    game_match = expected_system is not None and candidate.get("system_code") == expected_system
    signals["game"] = {
        "match": 1.0 if game_match else 0.0,
        "confidence": observation.game_confidence,
    }
    if game_match:
        contribution += WEIGHTS["game"] * observation.game_confidence
    elif observation.game != "Unknown":
        hard_rejections.append("game mismatch")

    observed_number = _compact(observation.card_number)
    candidate_number = _compact(candidate.get("card_number"))
    number_match = bool(observed_number and candidate_number and observed_number == candidate_number)
    signals["card_number"] = {
        "match": 1.0 if number_match else 0.0,
        "confidence": observation.card_number_confidence,
        "observed": observation.card_number,
        "candidate": candidate.get("card_number"),
    }
    if number_match:
        contribution += WEIGHTS["card_number"] * observation.card_number_confidence
    elif observed_number:
        hard_rejections.append("collector number mismatch")

    observed_language = clean_language(observation.language)
    candidate_language = _candidate_language(candidate)
    language_match = bool(
        observed_language
        and candidate_language
        and observed_language == candidate_language
    )
    signals["language"] = {
        "match": 1.0 if language_match else 0.0,
        "confidence": observation.language_confidence,
        "observed": observed_language,
        "candidate": candidate_language,
    }
    if language_match:
        contribution += WEIGHTS["language"] * observation.language_confidence
    elif observed_language and candidate_language:
        hard_rejections.append("language mismatch")

    name_match = _ratio(_name_core(observation.name_guess), _name_core(candidate.get("name")))
    signals["name"] = {
        "match": round(name_match, 5),
        "confidence": observation.name_confidence,
    }
    contribution += WEIGHTS["name"] * name_match * observation.name_confidence

    set_match = _ratio(observation.set_name_guess, candidate.get("set_name"))
    signals["set"] = {
        "match": round(set_match, 5),
        "confidence": observation.set_name_confidence,
    }
    contribution += WEIGHTS["set"] * set_match * observation.set_name_confidence

    rarity_match = _best_alias_match(
        observation.rarity_text,
        _candidate_rarity(candidate),
    )
    signals["rarity"] = {
        "match": round(rarity_match, 5),
        "confidence": observation.rarity_confidence,
    }
    contribution += WEIGHTS["rarity"] * rarity_match * observation.rarity_confidence

    type_match = _best_alias_match(
        observation.card_type_text,
        _candidate_type(candidate),
    )
    signals["card_type"] = {
        "match": round(type_match, 5),
        "confidence": observation.card_type_confidence,
    }
    contribution += WEIGHTS["card_type"] * type_match * observation.card_type_confidence

    art_values = _candidate_art(candidate)
    art_match = _best_alias_match(observation.art_treatment_text, art_values)
    signals["art"] = {
        "match": round(art_match, 5),
        "confidence": observation.art_treatment_confidence,
        "candidate_values": art_values,
    }
    contribution += WEIGHTS["art"] * art_match * observation.art_treatment_confidence

    finish_match = _best_alias_match(
        observation.finish_text,
        _candidate_finish(candidate),
    )
    signals["finish"] = {
        "match": round(finish_match, 5),
        "confidence": observation.finish_confidence,
    }
    contribution += WEIGHTS["finish"] * finish_match * observation.finish_confidence

    provider_match = bool(
        _provider_keys(provider_evidence) & _candidate_provider_keys(candidate)
    )
    signals["provider"] = {
        "match": 1.0 if provider_match else 0.0,
    }
    if provider_match:
        contribution += WEIGHTS["provider"]

    visual = max(0.0, min(1.0, visual_similarity or 0.0))
    signals["visual"] = {
        "match": round(visual, 5),
        "available": visual_similarity is not None,
    }
    if visual_similarity is not None:
        contribution += WEIGHTS["visual"] * visual

    return {
        "score": round(max(0.0, min(1.0, contribution)), 5),
        "hard_rejected": bool(hard_rejections),
        "rejection_reasons": hard_rejections,
        "signals": signals,
    }


async def load_catalogue_candidates(
    connection,
    observation: RecognitionObservation,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    system_code = SYSTEM_BY_GAME.get(observation.game)
    if not system_code:
        return []

    number = _compact(observation.card_number)
    params: list[Any] = [system_code]
    filters = ["pr.system_code=$1", "p.product_type='CARD'"]
    if number:
        params.append(number)
        filters.append(
            "upper(regexp_replace(coalesce(p.card_number,''), '[^A-Za-z0-9]', '', 'g'))"
            f"=${len(params)}"
        )
    elif observation.name_guess.strip():
        params.append(f"%{observation.name_guess.strip()}%")
        filters.append(f"p.name ilike ${len(params)}")
    else:
        return []
    params.append(limit)

    rows = await connection.fetch(
        f"""
        select
            p.id as catalogue_id,p.game,p.name,p.set_name,p.card_number,
            p.variant,p.rarity,p.language,pr.system_code,pr.identity_status,
            cp.printing_key,cp.identity_status as printing_identity_status,
            coalesce(t.taxonomy,'[]'::jsonb) as taxonomy,
            coalesce(pm.provider_mappings,'[]'::jsonb) as provider_mappings,
            m.public_source_url as reference_image_url,
            m.source_provider,m.provider_asset_id,m.media_language,
            coalesce(inv.languages,'[]'::jsonb) as inventory_languages,
            inv.max_known_value_minor,inv.has_graded_copy
        from tcg.catalogue_products p
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
        left join tcg.card_printings cp on cp.catalogue_id=p.id
        left join lateral (
            select jsonb_agg(
                jsonb_build_object(
                    'dimension_code',a.dimension_code,
                    'value_code',a.value_code,
                    'display_name',v.display_name,
                    'verification_status',a.verification_status,
                    'source_kind',a.source_kind
                )
                order by a.dimension_code,a.is_primary desc,a.value_code
            ) as taxonomy
            from tcg.catalogue_taxonomy_assignments a
            join tcg.taxonomy_values v
              on v.system_code=a.system_code
             and v.scope_kind=a.scope_kind
             and v.dimension_code=a.dimension_code
             and v.value_code=a.value_code
            where a.catalogue_id=p.id
        ) t on true
        left join lateral (
            select jsonb_agg(
                jsonb_build_object(
                    'source_provider',x.source_provider,
                    'provider_id',x.provider_id,
                    'provider_variant_key',x.provider_variant_key,
                    'provider_language',x.provider_language,
                    'match_status',x.match_status,
                    'verification_basis',x.verification_basis,
                    'confidence',x.confidence
                )
                order by
                  case x.match_status when 'VERIFIED' then 0 when 'REVIEW' then 1 else 2 end,
                  x.source_provider,x.provider_id
            ) as provider_mappings
            from tcg.provider_catalogue_mappings x
            where x.catalogue_id=p.id
              and x.match_status <> 'REJECTED'
        ) pm on true
        left join lateral (
            select
                ma.public_source_url,ma.source_provider,ma.provider_asset_id,
                ma.media_language
            from tcg.media_assets ma
            where ma.catalogue_id=p.id
              and ma.scope='CANONICAL_CARD'
              and ma.side='FRONT'
              and ma.source_status='ACTIVE'
              and ma.rights_status='VERIFIED'
              and ma.public_source_url is not null
            order by
                case ma.approval_status when 'APPROVED' then 0 else 1 end,
                ma.created_at desc
            limit 1
        ) m on true
        left join lateral (
            select
                to_jsonb(array_agg(distinct i.language)
                    filter (where i.language is not null)) as languages,
                max(greatest(
                    coalesce(i.market_value_minor,0),
                    coalesce(i.recommended_retail_minor,0),
                    coalesce(i.store_price_minor,0)
                )) as max_known_value_minor,
                bool_or(i.grading_company is not null and i.grade is not null)
                    as has_graded_copy
            from tcg.inventory_items i
            where i.catalogue_id=p.id
              and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
        ) inv on true
        where {" and ".join(filters)}
        order by p.name,p.set_name,p.variant,p.id
        limit ${len(params)}
        """,
        *params,
    )
    return [dict(row) for row in rows]


def _pokemon_variant_from_observation(observation: RecognitionObservation) -> list[str]:
    finish = _alias(observation.finish_text)
    if finish == "reverse holofoil":
        return ["Reverse Holofoil"]
    if finish == "holofoil":
        return ["Holofoil"]
    if finish == "normal":
        return ["Normal"]
    return ["Normal", "Holofoil", "Reverse Holofoil"]


async def discover_provider_evidence(
    observation: RecognitionObservation,
    *,
    tcgdex: TcgDexClient | None = None,
    punk: PunkRecordsClient | None = None,
) -> dict[str, Any]:
    if observation.language != "Japanese" or not observation.card_number:
        return {"items": [], "errors": []}

    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if observation.game == "Pokemon" and observation.set_name_guess:
        client = tcgdex or TcgDexClient()
        seen: set[tuple[str, str]] = set()
        for variant in _pokemon_variant_from_observation(observation):
            try:
                result = await client.resolve_japanese_card(
                    set_name=observation.set_name_guess,
                    card_number=observation.card_number,
                    variant=variant,
                )
            except TcgDexApiError as exc:
                errors.append(
                    {
                        "provider": "TCGdex",
                        "reason": exc.detail,
                        "retryable": exc.retryable,
                    }
                )
                continue
            if not result.get("resolved"):
                continue
            key = (
                str(result.get("provider_id") or ""),
                str(result.get("finish_key") or variant),
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(dict(result))

    elif observation.game == "One Piece":
        client = punk or PunkRecordsClient()
        try:
            items.extend(
                await client.find_japanese_candidates(
                    card_number=observation.card_number,
                    name=observation.name_guess or None,
                    limit=12,
                )
            )
        except PunkRecordsError as exc:
            errors.append(
                {
                    "provider": "Punk Records",
                    "reason": exc.detail,
                    "retryable": exc.retryable,
                }
            )

    return {"items": items, "errors": errors}


async def attach_visual_evidence(
    source_hashes: tuple[int, ...],
    candidates: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
) -> None:
    semaphore = asyncio.Semaphore(4)

    async def one(candidate: dict[str, Any]) -> None:
        url = str(candidate.get("reference_image_url") or "").strip()
        if not url:
            candidate["visual_similarity"] = None
            return
        async with semaphore:
            reference = await reference_image_hashes(url)
        candidate["visual_similarity"] = (
            hash_similarity(source_hashes, reference) if reference else None
        )

    await asyncio.gather(*[one(candidate) for candidate in candidates[:max_candidates]])
    for candidate in candidates[max_candidates:]:
        candidate["visual_similarity"] = None


def _provider_only_candidates(
    observation: RecognitionObservation,
    provider_evidence: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in provider_evidence:
        provider = str(item.get("provider") or "").strip()
        provider_id = str(item.get("provider_id") or "").strip()
        if not provider or not provider_id:
            continue
        name = item.get("provider_name") or item.get("name") or observation.name_guess
        rarity = item.get("provider_rarity") or item.get("rarity")
        card_type = item.get("provider_category") or item.get("card_type")
        art = item.get("art_treatment") or ""
        score = (
            0.32 * observation.card_number_confidence
            + 0.14 * observation.language_confidence
            + 0.12 * _ratio(_name_core(observation.name_guess), _name_core(name))
              * observation.name_confidence
            + 0.05 * _best_alias_match(observation.rarity_text, [str(rarity or "")])
              * observation.rarity_confidence
            + 0.03 * _best_alias_match(observation.card_type_text, [str(card_type or "")])
              * observation.card_type_confidence
            + 0.06 * _best_alias_match(observation.art_treatment_text, [str(art)])
              * observation.art_treatment_confidence
            + 0.04
        )
        output.append(
            {
                "candidate_key": f"provider:{provider}:{provider_id}",
                "source_kind": "PROVIDER",
                "system_code": SYSTEM_BY_GAME.get(observation.game),
                "catalogue_id": None,
                "provider": provider,
                "provider_id": provider_id,
                "provider_language": observation.language,
                "score": round(min(1.0, score), 5),
                "hard_rejected": False,
                "rejection_reasons": [],
                "signals": {
                    "provider": {"match": 1.0},
                    "card_number": {
                        "match": 1.0,
                        "confidence": observation.card_number_confidence,
                    },
                    "language": {
                        "match": 1.0,
                        "confidence": observation.language_confidence,
                    },
                },
                "candidate_snapshot": dict(item),
            }
        )
    return output


def resolve_candidates(
    observation: RecognitionObservation,
    catalogue_candidates: list[dict[str, Any]],
    *,
    provider_evidence: list[Mapping[str, Any]] | None = None,
    exact_threshold: float,
    min_margin: float,
    high_value_review_minor: int,
    inventory_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = list(provider_evidence or [])
    ranked: list[dict[str, Any]] = []
    for candidate in catalogue_candidates:
        scored = score_candidate(
            observation,
            candidate,
            provider_evidence=evidence,
            visual_similarity=candidate.get("visual_similarity"),
        )
        ranked.append(
            {
                "candidate_key": f"catalogue:{candidate['catalogue_id']}",
                "source_kind": "CATALOGUE",
                "system_code": candidate["system_code"],
                "catalogue_id": candidate["catalogue_id"],
                "provider": candidate.get("source_provider"),
                "provider_id": candidate.get("provider_asset_id"),
                "provider_language": candidate.get("media_language"),
                **scored,
                "candidate_snapshot": {
                    "game": candidate.get("game"),
                    "name": candidate.get("name"),
                    "set_name": candidate.get("set_name"),
                    "card_number": candidate.get("card_number"),
                    "variant": candidate.get("variant"),
                    "rarity": candidate.get("rarity"),
                    "language": _candidate_language(candidate),
                    "printing_key": candidate.get("printing_key"),
                    "identity_status": candidate.get("identity_status"),
                    "printing_identity_status": candidate.get("printing_identity_status"),
                    "taxonomy": candidate.get("taxonomy") or [],
                    "reference_image_url": candidate.get("reference_image_url"),
                    "max_known_value_minor": candidate.get("max_known_value_minor"),
                },
            }
        )

    ranked.sort(
        key=lambda item: (
            item["hard_rejected"],
            -float(item["score"]),
            str(item.get("candidate_key") or ""),
        )
    )
    viable = [item for item in ranked if not item["hard_rejected"]]
    provider_only = _provider_only_candidates(observation, evidence)

    if not viable:
        decision = "NO_MATCH" if not provider_only else "NEEDS_REVIEW"
        reasons = [
            "No local catalogue printing passed the hard identity gates."
        ]
        if provider_only:
            reasons.append(
                "A provider candidate exists but is not linked to a local catalogue printing."
            )
        return {
            "decision": decision,
            "top": None,
            "runner_up": None,
            "margin": None,
            "reasons": reasons,
            "risk_flags": [],
            "candidates": ranked + provider_only,
        }

    top = viable[0]
    runner = viable[1] if len(viable) > 1 else None
    margin = round(
        float(top["score"]) - float(runner["score"] if runner else 0.0),
        5,
    )

    reasons: list[str] = []
    risks: list[str] = []
    exact = True

    if observation.game_confidence < 0.90:
        exact = False
        reasons.append("Game confidence is below the exact-match gate.")
    if not observation.card_number or observation.card_number_confidence < 0.90:
        exact = False
        reasons.append("Collector/card number is not confidently readable.")
    if observation.language == "Unknown" or observation.language_confidence < 0.85:
        exact = False
        reasons.append("Language is not confidently established.")
    if top["signals"]["language"]["match"] < 1:
        exact = False
        reasons.append("Top catalogue candidate does not have an exact language match.")
    if float(top["score"]) < exact_threshold:
        exact = False
        reasons.append("Composite evidence score is below the exact-match threshold.")
    if runner is not None and margin < min_margin:
        exact = False
        reasons.append("Top candidate does not lead the runner-up by enough margin.")
    if observation.image_quality == "POOR":
        exact = False
        risks.append("POOR_IMAGE_QUALITY")
        reasons.append("Image quality is too poor for exact-printing resolution.")
    if observation.counterfeit_concerns:
        exact = False
        risks.append("POTENTIAL_COUNTERFEIT_REVIEW")
        reasons.append(
            "Vision reported a possible print/layout inconsistency; human review is required."
        )

    top_value = int(top["candidate_snapshot"].get("max_known_value_minor") or 0)
    if top_value >= high_value_review_minor:
        exact = False
        risks.append("HIGH_VALUE_REVIEW")
        reasons.append("High-value catalogue match requires human review.")

    if inventory_context:
        if inventory_context.get("grading_company") or inventory_context.get("grade"):
            exact = False
            risks.append("GRADED_ITEM_REVIEW")
            reasons.append("Graded inventory requires physical slab verification.")
        current_catalogue_id = str(inventory_context.get("catalogue_id") or "")
        top_catalogue_id = str(top.get("catalogue_id") or "")
        if (
            current_catalogue_id
            and top_catalogue_id
            and current_catalogue_id != top_catalogue_id
        ):
            exact = False
            risks.append("CURRENT_IDENTITY_CONFLICT")
            reasons.append(
                "Recognition disagrees with the inventory item's current catalogue identity."
            )

    same_number_count = sum(
        1
        for item in viable
        if _compact(item["candidate_snapshot"].get("card_number"))
        == _compact(top["candidate_snapshot"].get("card_number"))
    )
    if same_number_count > 1:
        art_unique = (
            observation.art_treatment_confidence >= 0.85
            and float(top["signals"]["art"]["match"]) >= 0.95
            and sum(
                1
                for item in viable
                if float(item["signals"]["art"]["match"]) >= 0.95
            ) == 1
        )
        top_visual = float(top["signals"]["visual"]["match"])
        runner_visual = (
            float(runner["signals"]["visual"]["match"]) if runner is not None else 0.0
        )
        visual_unique = (
            top["signals"]["visual"]["available"]
            and top_visual >= 0.90
            and top_visual - runner_visual >= 0.05
        )
        provider_unique = (
            float(top["signals"]["provider"]["match"]) == 1.0
            and sum(
                1
                for item in viable
                if float(item["signals"]["provider"]["match"]) == 1.0
            ) == 1
        )
        if not (art_unique or visual_unique or provider_unique):
            exact = False
            risks.append("AMBIGUOUS_PRINTING")
            reasons.append(
                "Multiple printings share the same card number without a unique art/provider/visual discriminator."
            )

    provider_matched = [
        item for item in viable if float(item["signals"]["provider"]["match"]) == 1.0
    ]
    if provider_matched and top not in provider_matched:
        exact = False
        risks.append("PROVIDER_CONFLICT")
        reasons.append("Provider evidence points to a different catalogue candidate.")

    decision = "EXACT_CANDIDATE" if exact else "NEEDS_REVIEW"
    if exact:
        reasons.append(
            "All exact-printing gates passed; no inventory record has been changed automatically."
        )

    return {
        "decision": decision,
        "top": top,
        "runner_up": runner,
        "margin": margin,
        "reasons": list(dict.fromkeys(reasons)),
        "risk_flags": list(dict.fromkeys(risks)),
        "candidates": ranked + provider_only,
    }
