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
    # Prior human-verified scans are deliberately a small extra signal.
    # They may improve ranking but can never clear hard identity gates.
    "learning": 0.04,
}

PRINTING_WEIGHTS = {
    "promotion": 0.20,
    "art": 0.15,
    "finish": 0.10,
    "visual": 0.45,
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


def _name_aliases(value: object) -> list[str]:
    """Return base/full/parenthetical aliases so bilingual names compare safely."""
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return []
    aliases = [raw]
    base = re.sub(r"\([^()]*\)", " ", raw).strip()
    if base:
        aliases.append(base)
    aliases.extend(
        item.strip()
        for item in re.findall(r"\(([^()]*)\)", raw)
        if item.strip()
    )
    normalized = [_name_core(item) for item in aliases if _name_core(item)]
    return list(dict.fromkeys(normalized))


def _name_similarity(left: object, right: object) -> float:
    left_aliases = _name_aliases(left)
    right_aliases = _name_aliases(right)
    if not left_aliases or not right_aliases:
        return 0.0
    return max(
        _ratio(a, b)
        for a in left_aliases
        for b in right_aliases
    )


def _round1_marker_present(observation: RecognitionObservation) -> bool:
    evidence = " ".join(
        [
            observation.art_treatment_text,
            *observation.visible_markers,
            *observation.ocr_lines,
        ]
    )
    compact = re.sub(r"[^a-z0-9]", "", evidence.casefold())
    return "round1" in compact or "roundone" in compact


def _candidate_promotion(candidate: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    attributes = candidate.get("printing_attributes")
    if not isinstance(attributes, Mapping):
        attributes = {}
    key = str(attributes.get("promotion_key") or "").strip() or None
    aliases = [
        str(value).strip()
        for value in (attributes.get("promotion_aliases") or [])
        if str(value).strip()
    ]
    name = str(attributes.get("promotion_name") or "").strip()
    if name:
        aliases.append(name)
    if key:
        aliases.append(key)

    legacy_context = " ".join(
        str(candidate.get(field) or "")
        for field in ("name", "set_name", "variant")
    )
    legacy_compact = re.sub(r"[^a-z0-9]", "", legacy_context.casefold())
    if not key and ("round1" in legacy_compact or "roundone" in legacy_compact):
        key = "ROUND1_2026"
        aliases.extend(["ROUND1", "ROUND1 Promotion Pack"])

    return key, list(dict.fromkeys(aliases))


def _observed_promotion_marker(observation: RecognitionObservation) -> str | None:
    evidence = " ".join(
        [
            observation.art_treatment_text,
            *observation.visible_markers,
            *observation.ocr_lines,
        ]
    )
    compact = re.sub(r"[^a-z0-9]", "", evidence.casefold())
    if "round1" in compact or "roundone" in compact:
        return "ROUND1_2026"
    return None


def _promotion_match(
    observation: RecognitionObservation,
    candidate: Mapping[str, Any],
) -> tuple[float, bool, str | None]:
    observed = _observed_promotion_marker(observation)
    key, aliases = _candidate_promotion(candidate)
    if not observed:
        return 0.0, False, key
    if key == observed:
        return 1.0, True, key
    observed_compact = re.sub(r"[^a-z0-9]", "", observed.casefold())
    for alias in aliases:
        compact = re.sub(r"[^a-z0-9]", "", alias.casefold())
        if compact and (
            compact == observed_compact
            or ("round1" in compact and observed == "ROUND1_2026")
        ):
            return 1.0, True, key
    return 0.0, True, key


def _round1_candidate(candidate: Mapping[str, Any]) -> bool:
    promotion_key, aliases = _candidate_promotion(candidate)
    if promotion_key == "ROUND1_2026":
        return True
    context = " ".join(
        [
            *(str(candidate.get(key) or "") for key in ("name", "set_name", "variant")),
            *aliases,
        ]
    )
    compact = re.sub(r"[^a-z0-9]", "", context.casefold())
    return "round1" in compact or "roundone" in compact


def _promo_marker_recovery_item(
    observation: RecognitionObservation,
    candidate: Mapping[str, Any],
    provider_evidence: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Recover gameplay identity from a visible ROUND1 marker plus independent stats.

    This never grants exact-printing approval: a conflicting OCR number remains an
    explicit review gate. It only prevents a moderate-confidence tiny-number OCR
    mistake from deleting an otherwise strongly identified collaboration promo.
    """
    if (
        observation.card_number_confidence > 0.85
        or not _round1_marker_present(observation)
        or not _round1_candidate(candidate)
    ):
        return None

    candidate_number = _compact(candidate.get("card_number"))
    if not candidate_number:
        return None

    eligible: list[Mapping[str, Any]] = []
    for item in provider_evidence:
        if _compact(item.get("base_card_id")) != candidate_number:
            continue
        if _name_similarity(observation.name_guess, item.get("name")) < 0.95:
            continue
        if (
            observation.cost is None
            or item.get("cost") is None
            or observation.cost_confidence < 0.95
            or int(observation.cost) != int(item.get("cost"))
        ):
            continue
        if (
            observation.power is None
            or item.get("power") is None
            or observation.power_confidence < 0.95
            or int(observation.power) != int(item.get("power"))
        ):
            continue
        if (
            not observation.card_type_text
            or not item.get("card_type")
            or observation.card_type_confidence < 0.90
            or _best_alias_match(
                observation.card_type_text,
                [str(item.get("card_type") or "")],
            ) < 0.95
        ):
            continue
        eligible.append(item)

    if not eligible:
        return None

    eligible.sort(
        key=lambda item: (
            -float(item.get("retrieval_score") or 0.0),
            str(item.get("provider_id") or ""),
        )
    )
    return eligible[0]


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
            _name_similarity(observation.name_guess, item.get("name")),
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
    promo_recovery_item = _promo_marker_recovery_item(
        observation,
        candidate,
        provider_evidence,
    )
    metadata_item = identity_item or promo_recovery_item
    recovered_number = (
        str(metadata_item.get("base_card_id") or "")
        if metadata_item
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
    promo_marker_override = bool(
        promo_recovery_item
        and recovered_number
        and _round1_marker_present(observation)
        and _round1_candidate(candidate)
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
        elif promo_marker_override and _compact(recovered_number) == candidate_number:
            number_match = True
            number_source = "promo_marker_recovery"
            number_confidence = 0.92
            ocr_conflict = True
            add_identity("card_number", 0.92, 0.92)
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

    signals["promo_marker"] = {
        "match": 1.0 if promo_marker_override else 0.0,
        "available": _round1_marker_present(observation),
        "candidate": _round1_candidate(candidate),
        "source": "visible_marker",
        "provider_id": (
            promo_recovery_item.get("provider_id")
            if promo_recovery_item
            else None
        ),
    }

    observed_language = clean_language(observation.language)
    candidate_language = _candidate_language(candidate)
    if candidate_language is None and metadata_item is not None:
        candidate_language = clean_language(metadata_item.get("language"))
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

    provider_name = str(metadata_item.get("name") or "") if metadata_item else ""
    local_name_match = _name_similarity(
        observation.name_guess,
        candidate.get("name"),
    )
    provider_name_match = _name_similarity(
        observation.name_guess,
        provider_name,
    )
    name_match = max(local_name_match, provider_name_match)
    signals["name"] = {
        "match": round(name_match, 5),
        "confidence": observation.name_confidence,
        "source": (
            "provider"
            if provider_name_match > local_name_match
            else "catalogue"
        ),
        "candidate": candidate.get("name"),
        "provider_value": provider_name or None,
    }
    if observation.name_guess and (candidate.get("name") or provider_name):
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
    provider_rarity = str(metadata_item.get("rarity") or "") if metadata_item else ""
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
    provider_type = str(metadata_item.get("card_type") or "") if metadata_item else ""
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

    learning_similarity_raw = candidate.get("learning_visual_similarity")
    learning_count = int(candidate.get("learning_example_count") or 0)
    learning_similarity = (
        max(0.0, min(1.0, float(learning_similarity_raw)))
        if learning_similarity_raw is not None
        else 0.0
    )
    learning_identity_eligible = learning_count >= 1 and learning_similarity >= 0.90
    signals["learning"] = {
        "match": round(learning_similarity, 5),
        "available": learning_count > 0,
        "example_count": learning_count,
        "eligible_for_identity": learning_identity_eligible,
        "source": "human_verified_scans",
    }
    if learning_identity_eligible:
        # Confidence rises slowly with repeated verified examples and stays bounded.
        learning_confidence = min(1.0, 0.75 + 0.05 * min(learning_count, 5))
        add_identity("learning", learning_similarity, learning_confidence)

    promotion_match, promotion_observed, promotion_key = _promotion_match(
        observation,
        candidate,
    )
    signals["promotion"] = {
        "match": round(promotion_match, 5),
        "available": promotion_observed,
        "observed": _observed_promotion_marker(observation),
        "candidate": promotion_key,
        "source": "visible_marker",
    }
    if promotion_observed:
        add_printing(
            "promotion",
            promotion_match,
            max(observation.art_treatment_confidence, 0.90),
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
    # One prior verified scan can help identity ranking. Exact-printing visual
    # evidence is stricter: require repeated examples and very high similarity.
    learning_printing_visual = (
        learning_similarity
        if learning_count >= 2 and learning_similarity >= 0.94
        else None
    )
    effective_visual = max(
        value
        for value in (
            visual_similarity,
            provider_visual,
            learning_printing_visual,
            0.0,
        )
        if value is not None
    )
    visual = max(0.0, min(1.0, effective_visual))
    visual_available = (
        visual_similarity is not None
        or provider_visual is not None
        or learning_printing_visual is not None
    )
    visual_source = "reference_image"
    if (
        learning_printing_visual is not None
        and learning_printing_visual >= float(visual_similarity or 0.0)
        and learning_printing_visual >= float(provider_visual or 0.0)
    ):
        visual_source = "human_verified_scans"
    elif provider_visual is not None and provider_visual >= float(visual_similarity or 0.0):
        visual_source = "provider_image"
    signals["visual"] = {
        "match": round(visual, 5),
        "available": visual_available,
        "source": visual_source,
    }
    if visual_available:
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
    learning_catalogue_ids: list[Any] | None = None,
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
    if learning_catalogue_ids:
        params.append(list(dict.fromkeys(learning_catalogue_ids)))
        identity_filters.append(
            f"p.id = any(${len(params)}::uuid[])"
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
            coalesce(cp.attributes,'{{}}'::jsonb) as printing_attributes,
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


def _provider_visual_shortlist(
    provider_evidence: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
) -> list[dict[str, Any]]:
    """Keep remote image work focused on provider rows that can still affect identity.

    Strong provider fingerprints are enough to recover a card number. Medium rows are
    useful as nearby visual alternatives. Low-relevance same-character rows remain in
    textual evidence but do not spend network time on artwork downloads.
    """
    strong: list[dict[str, Any]] = []
    medium: list[dict[str, Any]] = []
    for item in provider_evidence:
        identity = float(item.get("identity_score") or 0.0)
        non_number = float(item.get("non_number_identity_score") or 0.0)
        if identity >= 0.80 or non_number >= 0.88:
            strong.append(item)
        elif identity >= 0.65 or non_number >= 0.78:
            medium.append(item)

    selected = [*strong, *medium][:max_candidates]
    if selected:
        return selected

    # If provider text evidence is weak across the board, retain a small visual
    # fallback rather than removing image evidence entirely.
    return provider_evidence[: min(max_candidates, 4)]


async def attach_provider_visual_evidence(
    source_hashes: tuple[int, ...],
    provider_evidence: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
) -> None:
    semaphore = asyncio.Semaphore(4)
    selected = _provider_visual_shortlist(
        provider_evidence,
        max_candidates=max_candidates,
    )
    selected_ids = {id(item) for item in selected}

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

    await asyncio.gather(*[one(item) for item in selected])
    for item in provider_evidence:
        if id(item) not in selected_ids:
            item["visual_similarity"] = None



def visual_work_short_circuit_reason(
    observation: RecognitionObservation,
    inventory_context: Mapping[str, Any] | None = None,
) -> str | None:
    """Return only gates that make EXACT_CANDIDATE impossible regardless of image comparison.

    This is intentionally conservative: it never clears or replaces an identity gate.
    It only avoids remote reference-image work after an irreversible human-review gate
    is already present. Candidate/provider text evidence and verified-learning evidence
    still run so reviewers receive a useful shortlist.
    """
    if observation.game_confidence < 0.90:
        return "LOW_GAME_CONFIDENCE"
    if observation.language == "Unknown" or observation.language_confidence < 0.85:
        return "LANGUAGE_UNCERTAIN"
    if observation.image_quality == "POOR":
        return "POOR_IMAGE_QUALITY"
    if observation.counterfeit_concerns:
        return "POTENTIAL_COUNTERFEIT_REVIEW"
    if inventory_context and (
        inventory_context.get("grading_company") or inventory_context.get("grade")
    ):
        return "GRADED_ITEM_REVIEW"
    return None

def _provider_only_candidates(
    observation: RecognitionObservation,
    provider_evidence: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rank provider-only alternatives by their own evidence, never by global OCR confidence."""
    output: list[dict[str, Any]] = []
    observed_number = _compact(observation.card_number)
    observed_language = clean_language(observation.language)

    for item in provider_evidence:
        provider = str(item.get("provider") or "").strip()
        provider_id = str(item.get("provider_id") or "").strip()
        if not provider or not provider_id:
            continue

        identity_score = max(0.0, min(1.0, float(item.get("identity_score") or 0.0)))
        retrieval_score = max(0.0, min(1.0, float(item.get("retrieval_score") or 0.0)))
        visual_raw = item.get("visual_similarity")
        visual_score = (
            max(0.0, min(1.0, float(visual_raw)))
            if visual_raw is not None
            else 0.0
        )
        score = (
            0.85 * identity_score
            + 0.10 * retrieval_score
            + 0.05 * visual_score
        )

        base_card_id = _compact(item.get("base_card_id"))
        item_language = clean_language(item.get("language"))
        number_match = bool(
            observed_number and base_card_id and observed_number == base_card_id
        )
        language_match = bool(
            observed_language and item_language and observed_language == item_language
        )

        output.append(
            {
                "candidate_key": f"provider:{provider}:{provider_id}",
                "source_kind": "PROVIDER",
                "system_code": SYSTEM_BY_GAME.get(observation.game),
                "catalogue_id": None,
                "provider": provider,
                "provider_id": provider_id,
                "provider_language": item_language,
                "score": round(score, 5),
                "hard_rejected": False,
                "rejection_reasons": [],
                "signals": {
                    "provider": {
                        "match": round(identity_score, 5),
                        "source": "provider",
                    },
                    "card_number": {
                        "match": 1.0 if number_match else 0.0,
                        "confidence": observation.card_number_confidence,
                        "observed": observation.card_number,
                        "candidate": item.get("base_card_id"),
                        "source": "provider",
                    },
                    "language": {
                        "match": 1.0 if language_match else 0.0,
                        "confidence": observation.language_confidence,
                        "observed": observed_language,
                        "candidate": item_language,
                        "source": "provider",
                    },
                    "visual": {
                        "match": round(visual_score, 5),
                        "available": visual_raw is not None,
                        "source": "provider_image",
                    },
                },
                "candidate_snapshot": dict(item),
            }
        )

    output.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item.get("provider_id") or ""),
        )
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
                    "printing_attributes": candidate.get("printing_attributes") or {},
                    "taxonomy": candidate.get("taxonomy") or [],
                    # Catalogue artwork must represent this exact printing.
                    # Provider identity images are evidence only and must never be
                    # promoted into a catalogue candidate snapshot by fallback.
                    "reference_image_url": candidate.get("reference_image_url"),
                    "max_known_value_minor": candidate.get("max_known_value_minor"),
                },
            }
        )

    ranked.sort(
        key=lambda item: (
            item["hard_rejected"],
            -float(item["score"]),
            -float(item.get("printing_score") or 0.0),
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
            or (
                number_source == "promo_marker_recovery"
                and number_confidence >= 0.90
                and float(top["signals"].get("promo_marker", {}).get("match") or 0.0) >= 1.0
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
    elif number_source == "promo_marker_recovery":
        reasons.append(
            f"Collector/card number {number_signal.get('recovered')} was recovered from the visible collaboration marker plus matching independent card stats."
        )

    if bool(top.get("ocr_card_number_conflict")):
        exact = False
        risks.append("OCR_CARD_NUMBER_CONFLICT")
        reasons.append(
            f"OCR read {number_signal.get('observed') or 'an uncertain number'}, but stronger independent evidence resolves this identity as {number_signal.get('recovered') or number_signal.get('candidate')}. Human review is required before exact-printing approval."
        )

    observed_promotion = _observed_promotion_marker(observation)
    if observed_promotion:
        promotion_signal = top["signals"].get("promotion", {})
        if float(promotion_signal.get("match") or 0.0) < 1.0:
            exact = False
            risks.append("PROMOTION_PRINTING_MISMATCH")
            reasons.append(
                "A promotion/collaboration mark is visible, but the top catalogue printing is not tagged as that promotion."
            )
        elif not top["candidate_snapshot"].get("reference_image_url"):
            exact = False
            risks.append("PROMOTION_MEDIA_UNVERIFIED")
            reasons.append(
                "The promotion family is identified, but exact canonical artwork has not yet been verified for this printing."
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
        promotion_unique = (
            float(top["signals"].get("promotion", {}).get("match") or 0.0) >= 1.0
            and sum(
                1
                for item in viable
                if float(item["signals"].get("promotion", {}).get("match") or 0.0) >= 1.0
            ) == 1
        )
        if not (art_unique or visual_unique or provider_unique or promotion_unique):
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
