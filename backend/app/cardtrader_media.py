from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .cardtrader_client import CardTraderApiError, CardTraderClient
from .language import clean_language


CARDTRADER_TERMS_URL = "https://static.cardtrader.com/en/pages/terms-of-service"
CARDTRADER_API_DOCS_URL = "https://www.cardtrader.com/en/docs/api/full/reference"
UK_SALE_ADVERTISING_URL = "https://www.legislation.gov.uk/ukpga/1988/48/section/63"
RIGHTS_BASIS = (
    "CardTrader expressly permits API use for inventory management on CardTrader or "
    "other sales channels. Drop Rate restricts returned blueprint images to the exact "
    "physical-card Shopify product listing advertising that item for sale under UK CDPA "
    "1988 s63. Not approved for social media, generic SEO artwork, merchandise, AI "
    "training, or unrelated marketing. Provider terms: "
    + CARDTRADER_TERMS_URL
    + " ; statutory-use reference: "
    + UK_SALE_ADVERTISING_URL
)

SUPPORTED_GAMES = {
    "dragon ball super": "masters",
    "dragon ball super masters": "masters",
    "dragon ball super fusion world": "fusion-world",
}

LANGUAGE_CODES = {
    "english": "en",
    "japanese": "jp",
}

BASE_VARIANTS = {"", "normal", "base", "regular"}
FOIL_VARIANTS = {"holofoil", "holo", "foil"}
REVERSE_VARIANTS = {"reverse holofoil", "reverse holo", "reverse foil"}


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value))


def _canonical_number(value: object) -> str:
    text = str(value or "").strip().upper()
    chunks = re.split(r"([/-])", text)
    out: list[str] = []
    for chunk in chunks:
        if chunk.isdigit():
            out.append(str(int(chunk)))
        else:
            out.append(chunk)
    return "".join(out)


def _set_key(value: object) -> str:
    text = _norm(value).replace("&", " and ")
    text = text.replace("pre-release", "pre release")
    text = text.replace("prerelease", "pre release")
    text = text.replace("pre release cards", "pre release promos")
    text = text.replace("pre release card", "pre release promos")
    text = re.sub(r"\bfusion world\s*:\s*", "", text)
    return _compact(text)


def _is_foil(value: object) -> bool | None:
    variant = _norm(value)
    if variant in FOIL_VARIANTS or variant in REVERSE_VARIANTS:
        return True
    if variant in BASE_VARIANTS:
        return False
    return None


def _language_code(value: object) -> str | None:
    language = clean_language(value)
    if not language:
        return None
    return LANGUAGE_CODES.get(language.casefold())


def _game_line(value: object) -> str | None:
    return SUPPORTED_GAMES.get(_norm(value))


def _trusted_image_url(value: object) -> str | None:
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
    # Actual provider host is validated on the first production-token probe.
    # Until then, only CardTrader-owned or explicitly CardTrader-named hosts pass.
    if host != "cardtrader.com" and not host.endswith(".cardtrader.com"):
        return None
    return clean


def _property_value(row: Mapping[str, Any], *keys: str) -> object | None:
    normalized = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        if key.casefold() in normalized:
            return normalized[key.casefold()]
    fixed = row.get("fixed_properties")
    if isinstance(fixed, Mapping):
        normalized_fixed = {str(key).casefold(): value for key, value in fixed.items()}
        for key in keys:
            if key.casefold() in normalized_fixed:
                return normalized_fixed[key.casefold()]
    properties = row.get("properties_hash")
    if isinstance(properties, Mapping):
        normalized_props = {str(key).casefold(): value for key, value in properties.items()}
        for key in keys:
            if key.casefold() in normalized_props:
                return normalized_props[key.casefold()]
    return None


def _collector_number(row: Mapping[str, Any]) -> str | None:
    value = _property_value(
        row,
        "collector_number",
        "collectorNumber",
        "card_number",
        "cardNumber",
        "number",
    )
    if value is not None and str(value).strip():
        return str(value).strip()

    version = str(row.get("version") or "").strip()
    match = re.search(r"\b(?:BT|FB|FP|P)-?\d{2,3}-\d{2,3}\b", version, re.IGNORECASE)
    return match.group(0).upper() if match else None


def resolve_blueprint(
    local: Mapping[str, Any],
    *,
    games: list[dict[str, Any]],
    expansions: list[dict[str, Any]],
    blueprints: list[dict[str, Any]],
    marketplace_rows: Mapping[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Resolve one exact CardTrader blueprint or fail closed."""

    line = _game_line(local.get("game"))
    language_code = _language_code(local.get("language") or local.get("catalogue_language"))
    if not line:
        return {"resolved": False, "reason": "game is not supported by CardTrader adapter"}
    if not language_code:
        return {"resolved": False, "reason": "physical card language is not confirmed"}

    dragon_games = [
        row for row in games
        if "dragon ball" in _norm(row.get("name"))
    ]
    if not dragon_games:
        return {"resolved": False, "reason": "CardTrader Dragon Ball game was not found"}

    game_ids = {int(row["id"]) for row in dragon_games if str(row.get("id") or "").isdigit()}
    set_key = _set_key(local.get("set_name"))
    expansion_matches = [
        row
        for row in expansions
        if str(row.get("game_id") or "").isdigit()
        and int(row["game_id"]) in game_ids
        and _set_key(row.get("name")) == set_key
    ]

    if line == "fusion-world":
        fusion = [row for row in expansion_matches if "fusionworld" in _compact(row.get("name"))]
        if fusion:
            expansion_matches = fusion
    else:
        expansion_matches = [
            row for row in expansion_matches
            if "fusionworld" not in _compact(row.get("name"))
        ]

    if len(expansion_matches) != 1:
        return {
            "resolved": False,
            "reason": "CardTrader expansion is missing or ambiguous",
            "expansion_candidate_count": len(expansion_matches),
        }

    expansion = expansion_matches[0]
    expansion_id = int(expansion["id"])
    local_name = _compact(local.get("name"))
    local_number = _canonical_number(local.get("card_number"))
    foil = _is_foil(local.get("variant"))
    if foil is None:
        return {"resolved": False, "reason": "local card variant is not supported"}

    candidates: list[dict[str, Any]] = []
    for blueprint in blueprints:
        if int(blueprint.get("expansion_id") or 0) != expansion_id:
            continue
        if _compact(blueprint.get("name")) != local_name:
            continue

        number = _collector_number(blueprint)
        supporting_rows = (marketplace_rows or {}).get(int(blueprint.get("id") or 0), [])
        if number is None:
            row_numbers = {
                _canonical_number(_collector_number(row))
                for row in supporting_rows
                if _collector_number(row)
            }
            if len(row_numbers) == 1:
                number = next(iter(row_numbers))

        if not number or _canonical_number(number) != local_number:
            continue

        if supporting_rows:
            language_matches = [
                row for row in supporting_rows
                if _norm(_property_value(row, "language", "dbs_language", "dbscg_language"))
                in {language_code, "english" if language_code == "en" else "japanese"}
            ]
            # The API request itself is language-filtered. If a response still exposes
            # a language property, require that it agrees.
            if any(
                _property_value(row, "language", "dbs_language", "dbscg_language") is not None
                for row in supporting_rows
            ) and not language_matches:
                continue

        image_url = _trusted_image_url(blueprint.get("image_url"))
        if not image_url:
            continue

        candidates.append(
            {
                "provider_id": str(blueprint.get("id")),
                "image_url": image_url,
                "collector_number": number,
                "provider_name": blueprint.get("name"),
                "provider_set": expansion.get("name"),
                "provider_language": language_code,
                "finish_key": "foil" if foil else "normal",
                "expansion_id": expansion_id,
                "game_line": line,
            }
        )

    deduped = {
        (row["provider_id"], row["image_url"]): row
        for row in candidates
    }
    matches = list(deduped.values())
    if len(matches) == 1:
        return {"resolved": True, **matches[0]}
    if len(matches) > 1:
        return {
            "resolved": False,
            "reason": "multiple exact CardTrader blueprint candidates remain",
            "candidate_count": len(matches),
        }
    return {
        "resolved": False,
        "reason": "no exact CardTrader blueprint with card-number evidence and trusted image",
    }


async def lookup_one(
    client: CardTraderClient,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    line = _game_line(row.get("game"))
    language_code = _language_code(row.get("language") or row.get("catalogue_language"))
    if not line:
        return {"resolved": False, "reason": "unsupported CardTrader game"}
    if not language_code:
        return {"resolved": False, "reason": "physical card language is not confirmed"}

    try:
        games = await client.list_games()
        expansions = await client.list_expansions()
    except CardTraderApiError as exc:
        return {
            "resolved": False,
            "reason": exc.detail,
            "retryable": exc.retryable,
            "provider_status_code": exc.status_code,
        }

    game_ids = {
        int(game["id"])
        for game in games
        if str(game.get("id") or "").isdigit()
        and "dragon ball" in _norm(game.get("name"))
    }
    expansion_matches = [
        expansion
        for expansion in expansions
        if str(expansion.get("game_id") or "").isdigit()
        and int(expansion["game_id"]) in game_ids
        and _set_key(expansion.get("name")) == _set_key(row.get("set_name"))
    ]
    if len(expansion_matches) != 1:
        return {
            "resolved": False,
            "reason": "CardTrader expansion is missing or ambiguous",
            "expansion_candidate_count": len(expansion_matches),
        }

    expansion_id = int(expansion_matches[0]["id"])
    try:
        blueprints = await client.list_blueprints(expansion_id=expansion_id)
    except CardTraderApiError as exc:
        return {
            "resolved": False,
            "reason": exc.detail,
            "retryable": exc.retryable,
            "provider_status_code": exc.status_code,
        }

    local_name = _compact(row.get("name"))
    candidate_blueprints = [
        blueprint
        for blueprint in blueprints
        if _compact(blueprint.get("name")) == local_name
    ]

    marketplace_rows: dict[int, list[dict[str, Any]]] = {}
    foil = _is_foil(row.get("variant"))
    for blueprint in candidate_blueprints:
        blueprint_id = int(blueprint.get("id") or 0)
        if blueprint_id <= 0 or _collector_number(blueprint):
            continue
        try:
            marketplace_rows[blueprint_id] = await client.list_marketplace_products(
                blueprint_id=blueprint_id,
                language=language_code,
                foil=foil,
            )
        except CardTraderApiError as exc:
            return {
                "resolved": False,
                "reason": exc.detail,
                "retryable": exc.retryable,
                "provider_status_code": exc.status_code,
            }

    return resolve_blueprint(
        row,
        games=games,
        expansions=expansions,
        blueprints=blueprints,
        marketplace_rows=marketplace_rows,
    )
