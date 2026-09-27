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
    "game": 0.05,
    "card_number": 0.30,
    "language": 0.10,
    "name": 0.13,
    "set": 0.05,
    "rarity": 0.04,
    "card_type": 0.08,
    "provider": 0.25,
}

PRINTING_WEIGHTS = {
    "art": 0.25,
    "finish": 0.10,
    "visual": 0.55,
    "provider_print": 0.10,
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
    text = "".join(
        character if character.isalnum() else " "
        for character in text
    )
    return " ".join(text.split())


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
        "secretrare": "sec",
        "super rare": "sr",
        "superrare": "sr",
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


def _text_similarity(left: object, right: object) -> float:
    def normalize(value: object) -> str:
        text = str(value or "").casefold()
        text = re.sub(r"<br\s*/?>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = "".join(
            character if character.isalnum() else " "
            for character in text
        )
        return " ".join(text.split())

    a = normalize(left)
    b = normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    union = a_tokens | b_tokens
    jaccard = (len(a_tokens & b_tokens) / len(union)) if union else 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    return round(max(sequence, (0.65 * jaccard) + (0.35 * sequence)), 5)


def _set_match(observed: list[str], provider: list[str]) -> float:
    left = {_name_core(value) for value in observed if _name_core(value)}
    right = {_name_core(value) for value in provider if _name_core(value)}
    if not left or not right:
        return 0.0
    if left <= right or right <= left:
        return 1.0
    return len(left & right) / len(left | right)


def _provider_identity_fingerprint(
    observation: RecognitionObservation,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    weighted = 0.0
    available = 0.0
    non_number_weighted = 0.0
    non_number_available = 0.0
    matches: dict[str, float] = {}

    def add(
        name: str,
        score: float,
        confidence: float,
        weight: float,
        *,
        non_number: bool = True,
    ) -> None:
        nonlocal weighted, available, non_number_weighted, non_number_available
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= 0:
            return
        bounded = max(0.0, min(1.0, score))
        effective = weight * confidence
        available += effective
        weighted += effective * bounded
        if non_number:
            non_number_available += effective
            non_number_weighted += effective * bounded
        matches[name] = round(bounded, 5)

    if observation.name_guess:
        add(
            "name",
            _ratio(_name_core(observation.name_guess), _name_core(item.get("name"))),
            observation.name_confidence,
            0.16,
        )
    if observation.card_number:
        add(
            "card_number",
            1.0
            if _compact(observation.card_number) == _compact(item.get("base_card_id"))
            else 0.0,
            observation.card_number_confidence,
            0.28,
            non_number=False,
        )
    if observation.cost is not None and item.get("cost") is not None:
        add(
            "cost",
            1.0 if int(observation.cost) == int(item["cost"]) else 0.0,
            observation.cost_confidence,
            0.08,
        )
    if observation.power is not None and item.get("power") is not None:
        add(
            "power",
            1.0 if int(observation.power) == int(item["power"]) else 0.0,
            observation.power_confidence,
            0.13,
        )
    if observation.card_type_text and item.get("card_type"):
        add(
            "card_type",
            _best_alias_match(observation.card_type_text, [str(item.get("card_type") or "")]),
            observation.card_type_confidence,
            0.09,
        )
    if observation.colors and item.get("colors"):
        add(
            "colors",
            _set_match(observation.colors, list(item.get("colors") or [])),
            observation.colors_confidence,
            0.10,
        )
    if observation.attributes and item.get("attributes"):
        add(
            "attributes",
            _set_match(observation.attributes, list(item.get("attributes") or [])),
            observation.attributes_confidence,
            0.07,
        )
    if observation.traits and item.get("types"):
        add(
            "traits",
            _set_match(observation.traits, list(item.get("types") or [])),
            observation.traits_confidence,
            0.09,
        )
    if observation.effect_text and item.get("effect"):
        add(
            "effect",
            _text_similarity(observation.effect_text, item.get("effect")),
            observation.effect_confidence,
            0.23,
        )
    if observation.rarity_text and item.get("rarity"):
        add(
            "rarity",
            _best_alias_match(observation.rarity_text, [str(item.get("rarity") or "")]),
            observation.rarity_confidence,
            0.05,
        )

    score = weighted / available if available > 0 else 0.0
    non_number_score = (
        non_number_weighted / non_number_available
        if non_number_available > 0
        else 0.0
    )
    return {
        "identity_score": round(score, 5),
        "identity_evidence_weight": round(available, 5),
        "non_number_identity_score": round(non_number_score, 5),
        "non_number_evidence_weight": round(non_number_available, 5),
        "identity_matches": matches,
    }


def _provider_identity_for_candidate(
    candidate: Mapping[str, Any],
    provider_evidence: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    candidate_number = _compact(candidate.get("card_number"))
    if not candidate_number:
        return None

    eligible = []
    for item in provider_evidence:
        if _compact(item.get("base_card_id")) != candidate_number:
            continue
        score = float(item.get("identity_score") or 0.0)
        weight = float(item.get("identity_evidence_weight") or 0.0)
        non_number_score = float(item.get("non_number_identity_score") or 0.0)
        non_number_weight = float(item.get("non_number_evidence_weight") or 0.0)
        if not (
            (score >= 0.88 and weight >= 0.42)
            or (non_number_score >= 0.90 and non_number_weight >= 0.45)
        ):
            continue
        eligible.append(item)
    if not eligible:
        return None

    eligible.sort(
        key=lambda item: (
            -max(
                float(item.get("identity_score") or 0.0),
                float(item.get("non_number_identity_score") or 0.0),
            ),
            -float(item.get("non_number_evidence_weight") or 0.0),
            -float(item.get("visual_similarity") or 0.0),
            str(item.get("provider_id") or ""),
        )
    )
    return eligible[0]


def _provider_support(
    candidate: Mapping[str, Any],
    provider_evidence: list[Mapping[str, Any]],
) -> tuple[float, Mapping[str, Any] | None]:
    exact = _provider_keys(provider_evidence) & _candidate_provider_keys(candidate)
    if exact:
        for item in provider_evidence:
            key = (
                str(item.get("provider") or "").casefold(),
                str(item.get("provider_id") or "").casefold(),
            )
            if key in exact:
                return 1.0, item
        return 1.0, None

    identity_item = _provider_identity_for_candidate(candidate, provider_evidence)
    candidate_art = _candidate_art(candidate)
    best = 0.0
    best_item: Mapping[str, Any] | None = None

    for item in provider_evidence:
        if _compact(item.get("base_card_id")) != _compact(candidate.get("card_number")):
            continue
        identity_score = float(item.get("identity_score") or 0.0)
        identity_weight = float(item.get("identity_evidence_weight") or 0.0)
        non_number_score = float(item.get("non_number_identity_score") or 0.0)
        non_number_weight = float(item.get("non_number_evidence_weight") or 0.0)
        identity_strength = max(identity_score, non_number_score)
        if not (
            (identity_score >= 0.88 and identity_weight >= 0.42)
            or (non_number_score >= 0.90 and non_number_weight >= 0.45)
        ):
            continue

        provider_art = str(item.get("art_treatment") or "")
        art = _best_alias_match(provider_art, candidate_art)
        visual = item.get("visual_similarity")
        if provider_art and art < 0.90:
            continue

        if visual is not None:
            support = (
                0.58 * float(visual)
                + 0.27 * identity_strength
                + 0.15 * art
            )
        else:
            support = 0.78 * identity_strength + 0.22 * art

        if support > best:
            best = support
            best_item = item

    if best_item is not None:
        return round(best, 5), best_item

    if identity_item is not None:
        return round(
            max(
                float(identity_item.get("identity_score") or 0.0),
                float(identity_item.get("non_number_identity_score") or 0.0),
            ) * 0.80,
            5,
        ), identity_item

    return 0.0, None


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

    identity_contribution = 0.0
    identity_available = 0.0
    printing_contribution = 0.0
    printing_available = 0.0

    def add_identity(weight_key: str, match: float, confidence: float = 1.0) -> None:
        nonlocal identity_contribution, identity_available
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= 0:
            return
        bounded = max(0.0, min(1.0, match))
        weight = WEIGHTS[weight_key]
        effective = weight * confidence
        identity_available += effective
        identity_contribution += effective * bounded

    def add_printing(weight_key: str, match: float, confidence: float = 1.0) -> None:
        nonlocal printing_contribution, printing_available
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= 0:
            return
        bounded = max(0.0, min(1.0, match))
        weight = PRINTING_WEIGHTS[weight_key]
        effective = weight * confidence
        printing_available += effective
        printing_contribution += effective * bounded

    expected_system = SYSTEM_BY_GAME.get(observation.game)
    game_match = (
        expected_system is not None
        and candidate.get("system_code") == expected_system
    )
    signals["game"] = {
        "match": 1.0 if game_match else 0.0,
        "confidence": observation.game_confidence,
        "source": "vision",
    }
    if observation.game != "Unknown":
        add_identity("game", 1.0 if game_match else 0.0, observation.game_confidence)
        if not game_match:
            hard_rejections.append("game mismatch")

    identity_item = _provider_identity_for_candidate(candidate, provider_evidence)
    recovered_number = (
        str(identity_item.get("base_card_id") or "")
        if identity_item
        else ""
    )
    overall_provider_identity = (
        float(identity_item.get("identity_score") or 0.0)
        if identity_item
        else 0.0
    )
    non_number_provider_identity = (
        float(identity_item.get("non_number_identity_score") or 0.0)
        if identity_item
        else 0.0
    )
    non_number_provider_weight = (
        float(identity_item.get("non_number_evidence_weight") or 0.0)
        if identity_item
        else 0.0
    )
    provider_override = bool(
        identity_item
        and recovered_number
        and non_number_provider_identity >= 0.90
        and non_number_provider_weight >= 0.45
    )

    observed_number = _compact(observation.card_number)
    candidate_number = _compact(candidate.get("card_number"))
    number_match = bool(
        observed_number
        and candidate_number
        and observed_number == candidate_number
    )
    number_source: str | None = None
    number_confidence = observation.card_number_confidence
    ocr_conflict = False

    if number_match:
        number_source = "vision"
        add_identity("card_number", 1.0, observation.card_number_confidence)
    elif observed_number:
        if provider_override and _compact(recovered_number) == candidate_number:
            number_match = True
            number_source = "provider_override"
            number_confidence = non_number_provider_identity
            ocr_conflict = True
            add_identity(
                "card_number",
                non_number_provider_identity,
                max(0.90, non_number_provider_identity),
            )
        else:
            add_identity("card_number", 0.0, observation.card_number_confidence)
            hard_rejections.append("collector number mismatch")
    elif provider_override and _compact(recovered_number) == candidate_number:
        number_match = True
        number_source = "provider_fingerprint"
        number_confidence = non_number_provider_identity
        add_identity(
            "card_number",
            non_number_provider_identity,
            max(0.90, non_number_provider_identity),
        )
    elif provider_evidence:
        strongest_provider_identity = max(
            (
                max(
                    float(item.get("identity_score") or 0.0),
                    float(item.get("non_number_identity_score") or 0.0),
                )
                for item in provider_evidence
            ),
            default=0.0,
        )
        if strongest_provider_identity >= 0.90:
            add_identity("card_number", 0.0, strongest_provider_identity)

    signals["card_number"] = {
        "match": 1.0 if number_match else 0.0,
        "confidence": round(number_confidence, 5),
        "observed": observation.card_number,
        "candidate": candidate.get("card_number"),
        "recovered": recovered_number or None,
        "source": number_source,
        "ocr_conflict": ocr_conflict,
    }

    observed_language = clean_language(observation.language)
    candidate_language = _candidate_language(candidate)
    if candidate_language is None and identity_item is not None:
        candidate_language = clean_language(identity_item.get("language"))
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
        "source": (
            "provider"
            if _candidate_language(candidate) is None and candidate_language
            else "catalogue"
        ),
    }
    if observed_language and candidate_language:
        add_identity(
            "language",
            1.0 if language_match else 0.0,
            observation.language_confidence,
        )
        if not language_match:
            hard_rejections.append("language mismatch")

    name_match = _ratio(
        _name_core(observation.name_guess),
        _name_core(candidate.get("name")),
    )
    signals["name"] = {
        "match": round(name_match, 5),
        "confidence": observation.name_confidence,
        "source": "vision",
    }
    if observation.name_guess and candidate.get("name"):
        add_identity("name", name_match, observation.name_confidence)

    set_match = _ratio(observation.set_name_guess, candidate.get("set_name"))
    set_source = "vision"
    if not observation.set_name_guess and identity_item and candidate.get("set_name"):
        set_match = 1.0
        set_source = "catalogue_after_identity"
    signals["set"] = {
        "match": round(set_match, 5),
        "confidence": (
            observation.set_name_confidence
            if observation.set_name_guess
            else (non_number_provider_identity if identity_item else 0.0)
        ),
        "source": set_source,
        "candidate": candidate.get("set_name"),
    }
    if observation.set_name_guess and candidate.get("set_name"):
        add_identity("set", set_match, observation.set_name_confidence)

    rarity_values = _candidate_rarity(candidate)
    provider_rarity = str(identity_item.get("rarity") or "") if identity_item else ""
    rarity_match = _best_alias_match(observation.rarity_text, rarity_values)
    rarity_source = "vision"
    if not observation.rarity_text and provider_rarity and rarity_values:
        rarity_match = _best_alias_match(provider_rarity, rarity_values)
        rarity_source = "provider_after_identity"
    signals["rarity"] = {
        "match": round(rarity_match, 5),
        "confidence": (
            observation.rarity_confidence
            if observation.rarity_text
            else (non_number_provider_identity if identity_item else 0.0)
        ),
        "source": rarity_source,
        "candidate_values": rarity_values,
        "provider_value": provider_rarity or None,
    }
    if observation.rarity_text and rarity_values:
        add_identity("rarity", rarity_match, observation.rarity_confidence)

    type_values = _candidate_type(candidate)
    provider_type = str(identity_item.get("card_type") or "") if identity_item else ""
    if not type_values and provider_type:
        type_values = [provider_type]
    type_match = _best_alias_match(observation.card_type_text, type_values)
    type_source = "vision"
    if not observation.card_type_text and provider_type:
        type_match = 1.0
        type_source = "provider_after_identity"
    signals["card_type"] = {
        "match": round(type_match, 5),
        "confidence": (
            observation.card_type_confidence
            if observation.card_type_text
            else (non_number_provider_identity if identity_item else 0.0)
        ),
        "source": type_source,
        "candidate_values": type_values,
    }
    if observation.card_type_text and type_values:
        add_identity("card_type", type_match, observation.card_type_confidence)

    provider_support, provider_item = _provider_support(candidate, provider_evidence)
    provider_identity_strength = 0.0
    if provider_item is not None:
        provider_identity_strength = max(
            float(provider_item.get("identity_score") or 0.0),
            float(provider_item.get("non_number_identity_score") or 0.0),
        )

    signals["provider"] = {
        "match": round(provider_support, 5),
        "provider": provider_item.get("provider") if provider_item else None,
        "provider_id": provider_item.get("provider_id") if provider_item else None,
        "base_card_id": provider_item.get("base_card_id") if provider_item else None,
        "art_treatment": provider_item.get("art_treatment") if provider_item else None,
        "image_url": provider_item.get("image_url") if provider_item else None,
        "identity_score": (
            provider_item.get("identity_score") if provider_item else None
        ),
        "non_number_identity_score": (
            provider_item.get("non_number_identity_score") if provider_item else None
        ),
        "identity_evidence_weight": (
            provider_item.get("identity_evidence_weight") if provider_item else None
        ),
        "non_number_evidence_weight": (
            provider_item.get("non_number_evidence_weight") if provider_item else None
        ),
        "source": "provider",
    }
    if provider_evidence:
        add_identity(
            "provider",
            provider_identity_strength if provider_item else 0.0,
            1.0,
        )

    art_values = _candidate_art(candidate)
    provider_art = str(provider_item.get("art_treatment") or "") if provider_item else ""
    art_match = _best_alias_match(observation.art_treatment_text, art_values)
    art_source = "vision"
    if not observation.art_treatment_text and provider_art and art_values:
        art_match = _best_alias_match(provider_art, art_values)
        art_source = "provider"
    signals["art"] = {
        "match": round(art_match, 5),
        "confidence": (
            observation.art_treatment_confidence
            if observation.art_treatment_text
            else (provider_identity_strength if provider_art else 0.0)
        ),
        "candidate_values": art_values,
        "source": art_source,
    }
    if observation.art_treatment_text and art_values:
        add_printing("art", art_match, observation.art_treatment_confidence)

    finish_values = _candidate_finish(candidate)
    finish_match = _best_alias_match(observation.finish_text, finish_values)
    signals["finish"] = {
        "match": round(finish_match, 5),
        "confidence": observation.finish_confidence,
        "candidate_values": finish_values,
        "source": "vision",
    }
    if observation.finish_text and finish_values:
        add_printing("finish", finish_match, observation.finish_confidence)

    provider_visual = (
        float(provider_item.get("visual_similarity"))
        if provider_item and provider_item.get("visual_similarity") is not None
        else None
    )
    effective_visual = max(
        value
        for value in (visual_similarity, provider_visual, 0.0)
        if value is not None
    )
    visual = max(0.0, min(1.0, effective_visual))
    signals["visual"] = {
        "match": round(visual, 5),
        "available": visual_similarity is not None or provider_visual is not None,
        "source": "reference_image",
    }
    if visual_similarity is not None or provider_visual is not None:
        add_printing("visual", visual)

    exact_provider_print = False
    if provider_item is not None:
        provider_key = (
            str(provider_item.get("provider") or "").casefold(),
            str(provider_item.get("provider_id") or "").casefold(),
        )
        exact_provider_print = provider_key in _candidate_provider_keys(candidate)
        if exact_provider_print:
            add_printing("provider_print", 1.0)

    signals["provider_print"] = {
        "match": 1.0 if exact_provider_print else 0.0,
        "available": provider_item is not None,
        "source": "provider_mapping",
    }

    identity_score = (
        identity_contribution / identity_available
        if identity_available > 0
        else 0.0
    )
    printing_score = (
        printing_contribution / printing_available
        if printing_available > 0
        else 0.0
    )

    signals["identity_confidence"] = {
        "match": round(identity_score, 5),
        "evidence_weight": round(identity_available, 5),
    }
    signals["printing_confidence"] = {
        "match": round(printing_score, 5),
        "evidence_weight": round(printing_available, 5),
    }

    return {
        "score": round(max(0.0, min(1.0, identity_score)), 5),
        "printing_score": round(max(0.0, min(1.0, printing_score)), 5),
        "evidence_weight": round(identity_available, 5),
        "printing_evidence_weight": round(printing_available, 5),
        "ocr_card_number_conflict": ocr_conflict,
        "hard_rejected": bool(hard_rejections),
        "rejection_reasons": hard_rejections,
        "signals": signals,
    }


async def load_catalogue_candidates(
    connection,
    observation: RecognitionObservation,
    *,
    provider_evidence: list[Mapping[str, Any]] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    system_code = SYSTEM_BY_GAME.get(observation.game)
    if not system_code:
        return []

    number = _compact(observation.card_number)
    normalized_name = _compact(_name_core(observation.name_guess))
    provider_numbers = sorted(
        {
            _compact(item.get("base_card_id"))
            for item in (provider_evidence or [])
            if _compact(item.get("base_card_id"))
            and (
                float(item.get("identity_score") or 0.0) >= 0.82
                or float(item.get("non_number_identity_score") or 0.0) >= 0.88
            )
        }
    )

    params: list[Any] = [system_code]
    filters = ["pr.system_code=$1", "p.product_type='CARD'"]
    identity_filters: list[str] = []

    if number:
        params.append(number)
        identity_filters.append(
            "upper(regexp_replace(coalesce(p.card_number,''), '[^A-Za-z0-9]', '', 'g'))"
            f"=${len(params)}"
        )
    if normalized_name:
        params.append(normalized_name)
        identity_filters.append(
            "upper(regexp_replace(coalesce(p.name,''), '[^A-Za-z0-9]', '', 'g')) "
            f"like '%' || ${len(params)} || '%'"
        )
    if provider_numbers:
        params.append(provider_numbers)
        identity_filters.append(
            "upper(regexp_replace(coalesce(p.card_number,''), '[^A-Za-z0-9]', '', 'g')) "
            f"= any(${len(params)}::text[])"
        )
    if not identity_filters:
        return []

    filters.append("(" + " or ".join(identity_filters) + ")")
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
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if (
        observation.game == "Pokemon"
        and observation.language == "Japanese"
        and observation.card_number
        and observation.set_name_guess
    ):
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

    elif (
        observation.game == "One Piece"
        and observation.language in {"English", "Japanese"}
        and (observation.card_number or observation.name_guess)
    ):
        client = punk or PunkRecordsClient()
        try:
            items.extend(
                await client.find_candidates(
                    language=observation.language,
                    card_number=observation.card_number or None,
                    name=observation.name_guess or None,
                    cost=observation.cost,
                    power=observation.power,
                    card_type=observation.card_type_text or None,
                    colors=observation.colors,
                    limit=24,
                )
            )
            enriched: list[dict[str, Any]] = []
            for item in items:
                identity = _provider_identity_fingerprint(observation, item)
                item.update(identity)
                enriched.append(item)
            enriched.sort(
                key=lambda item: (
                    -max(
                        float(item.get("identity_score") or 0.0),
                        float(item.get("non_number_identity_score") or 0.0),
                    ),
                    -float(item.get("non_number_evidence_weight") or 0.0),
                    str(item.get("provider_id") or ""),
                )
            )
            items = enriched[:16]
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


async def attach_provider_visual_evidence(
    source_hashes: tuple[int, ...],
    provider_evidence: list[dict[str, Any]],
    *,
    max_candidates: int = 12,
) -> None:
    semaphore = asyncio.Semaphore(4)

    async def one(item: dict[str, Any]) -> None:
        url = str(item.get("image_url") or "").strip()
        if not url:
            item["visual_similarity"] = None
            return
        async with semaphore:
            reference = await reference_image_hashes(url)
        item["visual_similarity"] = (
            hash_similarity(source_hashes, reference) if reference else None
        )

    await asyncio.gather(*[one(item) for item in provider_evidence[:max_candidates]])
    for item in provider_evidence[max_candidates:]:
        item["visual_similarity"] = None


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
                    "language": (
                        scored["signals"]["language"].get("candidate")
                        or _candidate_language(candidate)
                    ),
                    "printing_key": candidate.get("printing_key"),
                    "identity_status": candidate.get("identity_status"),
                    "printing_identity_status": candidate.get("printing_identity_status"),
                    "taxonomy": candidate.get("taxonomy") or [],
                    "reference_image_url": (
                        candidate.get("reference_image_url")
                        or scored["signals"]["provider"].get("image_url")
                    ),
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

    number_signal = top["signals"]["card_number"]
    provider_signal = top["signals"]["provider"]
    number_source = number_signal.get("source")
    number_confidence = float(number_signal.get("confidence") or 0.0)
    provider_identity_weight = float(
        provider_signal.get("identity_evidence_weight") or 0.0
    )
    number_resolved = (
        float(number_signal.get("match") or 0.0) >= 1.0
        and (
            (number_source == "vision" and number_confidence >= 0.90)
            or (
                number_source in {"provider_fingerprint", "provider_override"}
                and number_confidence >= 0.90
                and provider_identity_weight >= 0.55
            )
        )
    )
    if not number_resolved:
        exact = False
        reasons.append(
            "Collector/card number is neither confidently readable nor independently recovered from a strong provider fingerprint."
        )
    elif number_source in {"provider_fingerprint", "provider_override"}:
        reasons.append(
            f"Collector/card number {number_signal.get('recovered')} was recovered from independent gameplay/provider evidence."
        )

    if bool(top.get("ocr_card_number_conflict")):
        exact = False
        risks.append("OCR_CARD_NUMBER_CONFLICT")
        reasons.append(
            f"OCR read {number_signal.get('observed') or 'an uncertain number'}, but stronger independent evidence resolves this identity as {number_signal.get('recovered') or number_signal.get('candidate')}. Human review is required before exact-printing approval."
        )

    if observation.language == "Unknown" or observation.language_confidence < 0.85:
        exact = False
        reasons.append("Language is not confidently established.")
    if top["signals"]["language"]["match"] < 1:
        exact = False
        reasons.append("Top catalogue candidate does not have an exact language match.")

    if float(top.get("evidence_weight") or 0.0) < 0.65:
        exact = False
        risks.append("INSUFFICIENT_INDEPENDENT_EVIDENCE")
        reasons.append("Too little independent evidence is available for an exact-printing decision.")
    if float(top["score"]) < exact_threshold:
        exact = False
        reasons.append("Identity confidence is below the exact-match threshold.")
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
            float(top["signals"]["provider"]["match"]) >= 0.90
            and sum(
                1
                for item in viable
                if float(item["signals"]["provider"]["match"]) >= 0.90
            ) == 1
        )
        if not (art_unique or visual_unique or provider_unique):
            exact = False
            risks.append("AMBIGUOUS_PRINTING")
            reasons.append(
                "Multiple printings share the same card number without a unique art/provider/visual discriminator."
            )

    top_card_number = _compact(top["candidate_snapshot"].get("card_number"))
    same_provider_printings = [
        item
        for item in evidence
        if _compact(item.get("base_card_id")) == top_card_number
        and (
            (
                float(item.get("identity_score") or 0.0) >= 0.88
                and float(item.get("identity_evidence_weight") or 0.0) >= 0.42
            )
            or (
                float(item.get("non_number_identity_score") or 0.0) >= 0.90
                and float(item.get("non_number_evidence_weight") or 0.0) >= 0.45
            )
        )
    ]
    if len(same_provider_printings) > 1:
        visual_ranked = sorted(
            [
                item for item in same_provider_printings
                if item.get("visual_similarity") is not None
            ],
            key=lambda item: -float(item.get("visual_similarity") or 0.0),
        )
        unique_visual_print = False
        if visual_ranked:
            best_visual = float(visual_ranked[0].get("visual_similarity") or 0.0)
            second_visual = (
                float(visual_ranked[1].get("visual_similarity") or 0.0)
                if len(visual_ranked) > 1
                else 0.0
            )
            best_art = str(visual_ranked[0].get("art_treatment") or "")
            candidate_art = _candidate_art(top["candidate_snapshot"])
            art_compatible = (
                not best_art
                or _best_alias_match(best_art, candidate_art) >= 0.90
            )
            unique_visual_print = (
                best_visual >= 0.90
                and best_visual - second_visual >= 0.05
                and art_compatible
            )

        if not unique_visual_print:
            exact = False
            risks.append("PROVIDER_PRINTING_AMBIGUITY")
            reasons.append(
                "The card identity is recovered, but multiple provider printings share it and the artwork evidence is not strong enough to certify the exact printing."
            )

    provider_matched = [
        item for item in viable if float(item["signals"]["provider"]["match"]) >= 0.90
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
