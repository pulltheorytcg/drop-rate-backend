from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from typing import Any, Mapping
from urllib.parse import urlparse

from .cardtrader_client import CardTraderClient
from .recognition_games import collector_key
from .recognition_vision import RecognitionObservation


CARDTRADER_API_DOCS_URL = "https://www.cardtrader.com/en/docs/api/full/reference"
_ONE_PIECE_CODE_RE = re.compile(
    r"\b(?:(?:OP|ST|EB|PRB)\d{1,2}-\d{3}|P-\d{3})\b",
    re.IGNORECASE,
)
_SET_CODE_RE = re.compile(r"\b(?:OP|ST|EB|PRB)[- ]?0?\d{1,2}\b", re.IGNORECASE)


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value))


def _ratio(left: object, right: object) -> float:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _cardtrader_image_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    try:
        parsed = urlparse(clean)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return None
    if host != "cardtrader.com" and not host.endswith(".cardtrader.com"):
        return None

    directory, separator, filename = parsed.path.rpartition("/")
    if (
        host == "cardtrader.com"
        and separator
        and re.fullmatch(r"/uploads/blueprints/image/\d+", directory, re.IGNORECASE)
        and filename.startswith("preview_")
        and len(filename) > len("preview_")
    ):
        parsed = parsed._replace(
            path=f"{directory}/{filename.removeprefix('preview_')}"
        )
    return parsed.geturl()


def _property_value(row: Mapping[str, Any], *keys: str) -> object | None:
    containers: list[Mapping[str, Any]] = [row]
    for field in ("fixed_properties", "properties_hash"):
        value = row.get(field)
        if isinstance(value, Mapping):
            containers.append(value)
    wanted = {key.casefold() for key in keys}
    for container in containers:
        for key, value in container.items():
            if str(key).casefold() in wanted:
                return value
    return None


def _collector_number(row: Mapping[str, Any]) -> str | None:
    direct = _property_value(
        row,
        "collector_number",
        "card_number",
        "one_piece_number",
        "onepiece_number",
        "number",
    )
    if direct is not None:
        text = str(direct).strip().upper()
        match = _ONE_PIECE_CODE_RE.search(text)
        if match:
            return match.group(0).upper()

    for value in (row.get("version"), row.get("name")):
        match = _ONE_PIECE_CODE_RE.search(str(value or "").upper())
        if match:
            return match.group(0).upper()
    return None


def _game_id(games: list[dict[str, Any]]) -> int | None:
    matches = []
    for row in games:
        text = f"{row.get('name') or ''} {row.get('display_name') or ''}"
        if "one piece" not in _norm(text):
            continue
        raw = row.get("id")
        if str(raw or "").isdigit():
            matches.append(int(raw))
    return matches[0] if len(matches) == 1 else None


def _single_category_ids(
    categories: list[dict[str, Any]],
    *,
    game_id: int,
) -> set[int]:
    output: set[int] = set()
    for row in categories:
        if str(row.get("game_id") or "") != str(game_id):
            continue
        name = _norm(row.get("name"))
        if "single" not in name:
            continue
        raw = row.get("id")
        if str(raw or "").isdigit():
            output.add(int(raw))
    return output


def _set_code_keys(value: object) -> set[str]:
    return {
        _compact(match.group(0))
        for match in _SET_CODE_RE.finditer(str(value or ""))
        if _compact(match.group(0))
    }


def _observed_set_codes(observation: RecognitionObservation) -> set[str]:
    codes = _set_code_keys(observation.set_name_guess)
    codes.update(_set_code_keys(observation.product_code))
    number = str(observation.card_number or "").strip().upper()
    match = re.match(r"^((?:OP|ST|EB|PRB)\d{1,2})-", number, re.IGNORECASE)
    if match:
        codes.add(_compact(match.group(1)))
    return codes


def _expansion_score(
    observation: RecognitionObservation,
    expansion: Mapping[str, Any],
) -> float:
    observed_codes = _observed_set_codes(observation)
    provider_codes = _set_code_keys(expansion.get("code")) | _set_code_keys(
        expansion.get("name")
    )
    code_match = 1.0 if observed_codes and observed_codes & provider_codes else 0.0

    set_similarity = _ratio(observation.set_name_guess, expansion.get("name"))
    compact_set = _compact(observation.set_name_guess)
    compact_expansion = _compact(expansion.get("name"))
    contains = 1.0 if compact_set and (
        compact_set in compact_expansion or compact_expansion in compact_set
    ) else 0.0

    return max(
        code_match,
        0.72 * set_similarity + 0.28 * contains,
    )


def _select_expansions(
    observation: RecognitionObservation,
    expansions: list[dict[str, Any]],
    *,
    game_id: int,
    max_expansions: int,
) -> list[tuple[dict[str, Any], float]]:
    ranked: list[tuple[dict[str, Any], float]] = []
    for row in expansions:
        if str(row.get("game_id") or "") != str(game_id):
            continue
        score = _expansion_score(observation, row)
        if score >= 0.52:
            ranked.append((row, score))

    ranked.sort(
        key=lambda item: (
            -item[1],
            str(item[0].get("name") or ""),
            int(item[0].get("id") or 0),
        )
    )
    return ranked[:max_expansions]


def _name_similarity(observation: RecognitionObservation, blueprint: Mapping[str, Any]) -> float:
    if not observation.name_guess:
        return 0.0
    return _ratio(observation.name_guess, blueprint.get("name"))


async def discover_one_piece_cardtrader_candidates(
    observation: RecognitionObservation,
    client: CardTraderClient,
    *,
    max_expansions: int = 4,
    max_candidates: int = 16,
) -> list[dict[str, Any]]:
    """Retrieve One Piece single-card candidates from CardTrader's official API.

    These rows are retrieval-only evidence. They can challenge a wrong local match
    and provide a transient reference image, but they are never treated as a
    verified Drop Rate catalogue mapping by themselves.
    """

    if (
        observation.game != "One Piece"
        or observation.object_type not in {"CARD", "GRADED_CARD"}
        or observation.language not in {"English", "Japanese"}
        or not (observation.card_number or observation.name_guess)
    ):
        return []

    games, expansions = await asyncio.gather(
        client.list_games(),
        client.list_expansions(),
    )
    game_id = _game_id(games)
    if game_id is None:
        return []

    categories = await client.list_categories(game_id=game_id)
    single_category_ids = _single_category_ids(categories, game_id=game_id)
    if not single_category_ids:
        return []

    selected = _select_expansions(
        observation,
        expansions,
        game_id=game_id,
        max_expansions=max_expansions,
    )
    if not selected:
        return []

    async def fetch_one(expansion: Mapping[str, Any], score: float):
        raw_id = expansion.get("id")
        if not str(raw_id or "").isdigit():
            return expansion, score, []
        rows = await client.list_blueprints(expansion_id=int(raw_id))
        return expansion, score, rows

    expansion_rows = await asyncio.gather(
        *(fetch_one(expansion, score) for expansion, score in selected)
    )

    observed_number = collector_key(observation.card_number)
    candidates: list[dict[str, Any]] = []
    for expansion, expansion_score, blueprints in expansion_rows:
        for blueprint in blueprints:
            raw_category = blueprint.get("category_id")
            if not str(raw_category or "").isdigit():
                continue
            if int(raw_category) not in single_category_ids:
                continue

            image_url = _cardtrader_image_url(blueprint.get("image_url"))
            if not image_url:
                continue

            number = _collector_number(blueprint)
            candidate_number = collector_key(number)
            number_match = bool(
                observed_number and candidate_number and observed_number == candidate_number
            )
            if (
                observed_number
                and observation.card_number_confidence >= 0.70
                and candidate_number
                and not number_match
            ):
                continue

            name_similarity = _name_similarity(observation, blueprint)
            if not number_match and name_similarity < 0.62:
                continue

            retrieval_score = min(
                1.0,
                (0.62 if number_match else 0.0)
                + 0.25 * name_similarity
                + 0.13 * expansion_score,
            )
            version = str(blueprint.get("version") or "").strip()
            candidates.append(
                {
                    "provider": "CardTrader",
                    "provider_id": str(blueprint.get("id")),
                    "name": blueprint.get("name"),
                    "base_card_id": number,
                    "set_name": expansion.get("name"),
                    "language": observation.language,
                    "image_url": image_url,
                    "source_reference": CARDTRADER_API_DOCS_URL,
                    "finish": version or None,
                    "art_treatment": version or None,
                    "retrieval_score": round(retrieval_score, 5),
                    "library_reference": True,
                    "retrieval_only": True,
                    "exact_printing_verified": False,
                    "cardtrader_expansion_id": expansion.get("id"),
                    "cardtrader_category_id": blueprint.get("category_id"),
                    "provider_version": blueprint.get("version"),
                }
            )

    candidates.sort(
        key=lambda item: (
            -float(item.get("retrieval_score") or 0.0),
            str(item.get("provider_id") or ""),
        )
    )
    return candidates[:max_candidates]


def _sealed_category_types(
    categories: list[dict[str, Any]],
    *,
    game_id: int,
) -> dict[int, str]:
    output: dict[int, str] = {}
    for row in categories:
        if str(row.get("game_id") or "") != str(game_id):
            continue
        raw_id = row.get("id")
        if not str(raw_id or "").isdigit():
            continue
        name = _norm(row.get("name"))
        if "single" in name:
            continue

        sealed_type: str | None = None
        if "booster box" in name or ("display" in name and "booster" in name):
            sealed_type = "BOOSTER_BOX"
        elif "booster" in name or name == "boosters":
            sealed_type = "BOOSTER_PACK"
        elif "starter" in name and "deck" in name:
            sealed_type = "STARTER_DECK"
        elif "tin" in name:
            sealed_type = "TIN"
        elif "case" in name:
            sealed_type = "CASE"
        elif any(token in name for token in ("collection", "bundle", "gift", "pack set")):
            sealed_type = "COLLECTION"

        if sealed_type:
            output[int(raw_id)] = sealed_type
    return output


def _display_set_code(*values: object) -> str | None:
    for value in values:
        match = re.search(
            r"\b(OP|ST|EB|PRB)[- ]?0?(\d{1,2})\b",
            str(value or ""),
            re.IGNORECASE,
        )
        if match:
            prefix = match.group(1).upper()
            number = int(match.group(2))
            return f"{prefix}-{number:02d}"
    return None


async def discover_one_piece_cardtrader_sealed_candidates(
    observation: RecognitionObservation,
    client: CardTraderClient,
    *,
    max_expansions: int = 4,
    max_candidates: int = 16,
) -> list[dict[str, Any]]:
    """Retrieve One Piece sealed-product candidates from CardTrader.

    The result is retrieval-only. CardTrader can identify a likely pack/box/deck and
    provide a transient reference image, but it cannot create or verify canonical
    Drop Rate sealed identity by itself.
    """

    if (
        observation.game != "One Piece"
        or observation.object_type != "SEALED_PRODUCT"
        or not (observation.product_code or observation.set_name_guess)
    ):
        return []

    games, expansions = await asyncio.gather(
        client.list_games(),
        client.list_expansions(),
    )
    game_id = _game_id(games)
    if game_id is None:
        return []

    categories = await client.list_categories(game_id=game_id)
    sealed_categories = _sealed_category_types(categories, game_id=game_id)
    if not sealed_categories:
        return []

    selected = _select_expansions(
        observation,
        expansions,
        game_id=game_id,
        max_expansions=max_expansions,
    )
    if not selected:
        return []

    async def fetch_one(expansion: Mapping[str, Any], score: float):
        raw_id = expansion.get("id")
        if not str(raw_id or "").isdigit():
            return expansion, score, []
        rows = await client.list_blueprints(expansion_id=int(raw_id))
        return expansion, score, rows

    expansion_rows = await asyncio.gather(
        *(fetch_one(expansion, score) for expansion, score in selected)
    )

    observed_code = _compact(observation.product_code)
    observed_type = str(observation.sealed_product_type or "UNKNOWN").upper()
    candidates: list[dict[str, Any]] = []

    for expansion, expansion_score, blueprints in expansion_rows:
        provider_code = _display_set_code(
            expansion.get("code"),
            expansion.get("name"),
            observation.product_code,
        )
        provider_code_key = _compact(provider_code)
        code_match = bool(
            observed_code
            and provider_code_key
            and observed_code == provider_code_key
        )

        if (
            observed_code
            and observation.product_code_confidence >= 0.80
            and provider_code_key
            and not code_match
        ):
            continue

        for blueprint in blueprints:
            raw_category = blueprint.get("category_id")
            if not str(raw_category or "").isdigit():
                continue
            candidate_type = sealed_categories.get(int(raw_category))
            if not candidate_type:
                continue
            if (
                observed_type != "UNKNOWN"
                and observation.sealed_product_type_confidence >= 0.80
                and candidate_type != observed_type
            ):
                continue

            image_url = _cardtrader_image_url(blueprint.get("image_url"))
            if not image_url:
                continue

            name_similarity = max(
                _ratio(observation.set_name_guess, blueprint.get("name")),
                _ratio(observation.set_name_guess, expansion.get("name")),
            )
            type_match = observed_type != "UNKNOWN" and candidate_type == observed_type
            if not code_match and not type_match and name_similarity < 0.60:
                continue

            retrieval_score = min(
                0.99,
                (0.55 if code_match else 0.0)
                + (0.30 if type_match else 0.0)
                + 0.15 * max(name_similarity, expansion_score),
            )
            candidates.append(
                {
                    "provider": "CardTrader",
                    "provider_id": str(blueprint.get("id")),
                    "name": blueprint.get("name") or expansion.get("name"),
                    "set_name": expansion.get("name"),
                    "product_code": provider_code,
                    "sealed_product_type": candidate_type,
                    "language": None,
                    "image_url": image_url,
                    "source_reference": CARDTRADER_API_DOCS_URL,
                    "retrieval_score": round(retrieval_score, 5),
                    "library_reference": True,
                    "retrieval_only": True,
                    "exact_printing_verified": False,
                    "cardtrader_expansion_id": expansion.get("id"),
                    "cardtrader_category_id": blueprint.get("category_id"),
                    "provider_version": blueprint.get("version"),
                }
            )

    candidates.sort(
        key=lambda item: (
            -float(item.get("retrieval_score") or 0.0),
            str(item.get("provider_id") or ""),
        )
    )
    return candidates[:max_candidates]
