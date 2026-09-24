from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .cardmarket_parse_adapter import CARDMARKET_PARSE_SCRAPER_ID, _parse_cardmarket_url
from .collectr_parse_adapter import COLLECTR_PARSE_SCRAPER_ID
from .db import user_connection
from .market_ingestion import _owner
from .parse_client import ParseApiError, ParseHttpClient
from .settings import get_settings
from .tcgplayer_parse_adapter import TCGPLAYER_PARSE_SCRAPER_ID


router = APIRouter(prefix="/api/v1/market/discovery", tags=["market-data"])

DISCOVERY_SOURCES = {"CARDMARKET", "TCGPLAYER", "COLLECTR"}
CARDMARKET_GAME_SLUGS = {
    "pokemon": "Pokemon",
    "one piece": "OnePiece",
}


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _same(left: object, right: object) -> bool:
    a, b = _clean(left), _clean(right)
    return bool(a and b and a.casefold() == b.casefold())


def _signals(candidate: dict[str, Any], catalogue: dict[str, Any]) -> tuple[list[str], float]:
    signals: list[str] = []
    score = 0.0
    if _same(candidate.get("name"), catalogue.get("name")):
        signals.append("name")
        score += 0.35
    if _same(candidate.get("set_name"), catalogue.get("set_name")):
        signals.append("set")
        score += 0.35
    if _same(candidate.get("card_number"), catalogue.get("card_number")):
        signals.append("card_number")
        score += 0.30
    return signals, round(min(score, 1.0), 2)


def _candidate(
    *,
    source: str,
    source_product_id: object,
    source_variant_id: object = None,
    name: object = None,
    set_name: object = None,
    card_number: object = None,
    rarity: object = None,
    market_price: object = None,
    catalogue: dict[str, Any],
) -> dict[str, Any] | None:
    product_id = _clean(source_product_id)
    if not product_id:
        return None
    item = {
        "source": source,
        "source_product_id": product_id,
        "source_variant_id": _clean(source_variant_id),
        "name": _clean(name),
        "set_name": _clean(set_name),
        "card_number": _clean(card_number),
        "rarity": _clean(rarity),
        "market_price": market_price if isinstance(market_price, (int, float, str)) else None,
    }
    signals, confidence = _signals(item, catalogue)
    item["match_signals"] = signals
    item["suggested_confidence"] = confidence
    return item


async def _catalogue_snapshot(
    request: Request,
    user: AuthenticatedUser,
    catalogue_id: UUID,
) -> dict[str, Any]:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)
        row = await connection.fetchrow(
            """
            select id, product_type, game, name, set_name, card_number,
                   variant, rarity, language
            from tcg.catalogue_products
            where id = $1
            """,
            catalogue_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Catalogue product not found")
        return dict(row)


async def _discover_cardmarket(
    client: ParseHttpClient,
    catalogue: dict[str, Any],
) -> list[dict[str, Any]]:
    game = CARDMARKET_GAME_SLUGS.get(str(catalogue["game"]).strip().casefold())
    if not game:
        raise HTTPException(
            status_code=422,
            detail="Cardmarket discovery is not configured for this game",
        )
    payload = await client.get(
        scraper_id=CARDMARKET_PARSE_SCRAPER_ID,
        endpoint="search_singles",
        snapshot_version=None,
        params={"game": game, "query": str(catalogue["name"]), "page": 1},
    )
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Cardmarket response is missing results")

    candidates: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        url = _clean(row.get("url") or row.get("product_url"))
        if not url:
            continue
        try:
            _parse_cardmarket_url(url)
        except ValueError:
            continue
        item = _candidate(
            source="CARDMARKET",
            source_product_id=url,
            source_variant_id=catalogue.get("variant"),
            name=row.get("name"),
            set_name=row.get("expansion") or row.get("set_name"),
            card_number=row.get("card_number") or row.get("number"),
            rarity=row.get("rarity"),
            market_price=row.get("lowest_price"),
            catalogue=catalogue,
        )
        if item:
            candidates.append(item)
    return candidates


async def _discover_tcgplayer(
    client: ParseHttpClient,
    catalogue: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = await client.get(
        scraper_id=TCGPLAYER_PARSE_SCRAPER_ID,
        endpoint="search_cards",
        snapshot_version=None,
        params={"query": str(catalogue["name"]), "limit": 20, "offset": 0},
    )
    rows = payload.get("cards")
    if not isinstance(rows, list):
        raise ValueError("TCGPlayer response is missing cards")

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = _clean(row.get("product_id"))
        if not product_id or not product_id.isdigit():
            continue
        item = _candidate(
            source="TCGPLAYER",
            source_product_id=product_id,
            name=row.get("name"),
            set_name=row.get("set_name"),
            card_number=row.get("card_number") or row.get("number"),
            rarity=row.get("rarity"),
            market_price=row.get("market_price"),
            catalogue=catalogue,
        )
        if item:
            candidates.append(item)
    return candidates


async def _discover_collectr(
    client: ParseHttpClient,
    catalogue: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = await client.get(
        scraper_id=COLLECTR_PARSE_SCRAPER_ID,
        endpoint="search_cards",
        snapshot_version=None,
        params={"query": str(catalogue["name"]), "page": 1},
    )
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("Collectr response is missing items")

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = _clean(row.get("product_id"))
        if not product_id or not product_id.isdigit():
            continue
        item = _candidate(
            source="COLLECTR",
            source_product_id=product_id,
            source_variant_id=row.get("sub_type"),
            name=row.get("name") or row.get("product_name"),
            set_name=row.get("set_name") or row.get("catalog_group"),
            card_number=row.get("card_number"),
            rarity=row.get("rarity"),
            market_price=row.get("market_price"),
            catalogue=catalogue,
        )
        if item:
            candidates.append(item)
    return candidates


@router.get("/{source}")
async def discover_market_candidates(
    source: str,
    catalogue_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Return non-persistent provider candidates for one canonical catalogue item."""

    source = source.upper().strip()
    if source not in DISCOVERY_SOURCES:
        raise HTTPException(
            status_code=404,
            detail="Provider discovery is not available for this source",
        )

    settings = get_settings()
    if not settings.parse_api_key:
        raise HTTPException(status_code=409, detail="Provider discovery access is not configured")

    # Snapshot catalogue identity in a short DB transaction, then release the DB
    # before any external provider request.
    catalogue = await _catalogue_snapshot(request, user, catalogue_id)
    client = ParseHttpClient(api_key=settings.parse_api_key, timeout_seconds=20.0)

    try:
        if source == "CARDMARKET":
            candidates = await _discover_cardmarket(client, catalogue)
        elif source == "TCGPLAYER":
            candidates = await _discover_tcgplayer(client, catalogue)
        else:
            candidates = await _discover_collectr(client, catalogue)
    except HTTPException:
        raise
    except ParseApiError as exc:
        raise HTTPException(
            status_code=502 if exc.retryable else 422,
            detail={
                "message": exc.detail,
                "provider_status_code": exc.status_code,
                "retryable": exc.retryable,
            },
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Provider discovery response failed validation") from exc

    candidates.sort(
        key=lambda item: (
            float(item["suggested_confidence"]),
            bool(item.get("card_number")),
            bool(item.get("set_name")),
        ),
        reverse=True,
    )
    return jsonable_encoder(
        {
            "persisted": False,
            "source": source,
            "catalogue": catalogue,
            "candidates": candidates,
        }
    )
