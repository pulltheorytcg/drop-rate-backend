from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import unquote, urlparse

from .fx import FxQuote, FxRateProvider
from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .parse_client import ParseHttpClient


CARDMARKET_PARSE_SCRAPER_ID = "6e8ae7ea-a15a-4125-aada-1e116c8060b5"
CARDMARKET_PARSE_SNAPSHOT_VERSION = 32
_CARDMARKET_HOSTS = {"cardmarket.com", "www.cardmarket.com"}
_KNOWN_LANGUAGES = {
    "English",
    "French",
    "German",
    "Spanish",
    "Italian",
    "Japanese",
    "Korean",
    "Portuguese",
    "Russian",
    "Chinese",
}


def _parse_cardmarket_url(value: str) -> tuple[str, str, str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc.casefold() not in _CARDMARKET_HOSTS:
        raise ValueError("Cardmarket source_product_id must be a canonical HTTPS Cardmarket URL")

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 6 or parts[2] != "Products" or parts[3] != "Singles":
        raise ValueError("Cardmarket source_product_id must point to one exact Singles product")

    _, game, _, _, expansion, card = parts
    if not game or not expansion or not card:
        raise ValueError("Cardmarket product URL is missing required slugs")

    canonical = f"https://www.cardmarket.com/{'/'.join(parts)}"
    return game, expansion, card, canonical


def _money_minor(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Provider returned an invalid money value")

    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    elif isinstance(value, str):
        raw = (
            value.replace("€", "")
            .replace("\u00a0", "")
            .replace(" ", "")
            .strip()
        )
        if not raw:
            return None
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
    else:
        raise ValueError("Provider returned an invalid money value")

    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Provider returned an invalid money value") from exc
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _history_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Cardmarket history point is missing a date")
    try:
        day = datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError("Cardmarket history point has an invalid date") from exc
    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)


def _to_gbp_minor(eur_minor: int, quote: FxQuote) -> int:
    return int((Decimal(eur_minor) * quote.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _listing_language(attributes: object) -> str | None:
    if not isinstance(attributes, list):
        return None
    for attribute in attributes:
        if isinstance(attribute, str) and attribute.strip() in _KNOWN_LANGUAGES:
            return attribute.strip()
    return None


def _pokemon_variant_mode(source_variant_id: str | None) -> str:
    value = (source_variant_id or "").strip().casefold()
    if not value:
        raise ValueError("Cardmarket Pokemon mapping requires source_variant_id")
    if value in {"reverse holo", "reverse holofoil", "reverse"}:
        return "REVERSE_HOLO"
    return "BASE_PRINTING"


def _is_reverse_holo_listing(attributes: list[str]) -> bool:
    return any("reverse holo" in attribute.casefold() for attribute in attributes)


def _pokemon_listing_matches_variant(attributes: list[str], source_variant_id: str | None) -> bool:
    mode = _pokemon_variant_mode(source_variant_id)
    is_reverse = _is_reverse_holo_listing(attributes)
    return is_reverse if mode == "REVERSE_HOLO" else not is_reverse


def _assert_identity(payload: dict, *, game: str, expansion: str, card: str) -> None:
    returned_game = payload.get("game")
    returned_expansion = payload.get("expansion")
    returned_card = payload.get("card")
    if returned_game is not None and str(returned_game) != game:
        raise ValueError("Cardmarket returned the wrong game")
    if returned_expansion is not None and str(returned_expansion) != expansion:
        raise ValueError("Cardmarket returned the wrong expansion")
    if returned_card is not None and str(returned_card) != card:
        raise ValueError("Cardmarket returned the wrong card printing")


class CardmarketParseAdapter:
    """Cardmarket market adapter using the user-approved Parse API.

    A mapping's source_product_id must be the canonical Cardmarket Singles URL.
    This keeps game, expansion and versioned card slugs explicit and prevents an
    ambiguous printing from being silently substituted.

    Cardmarket price-history chart points are daily product-wide average sell
    prices, not individual transactions, so they are normalised strictly as
    MARKET_AGGREGATE. Current seller offers are normalised as ACTIVE.
    """

    source = "CARDMARKET"

    def __init__(self, *, client: ParseHttpClient, fx_provider: FxRateProvider) -> None:
        self._client = client
        self._fx_provider = fx_provider

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        game, expansion, card, canonical_url = _parse_cardmarket_url(source_product_id)

        pokemon_variant_mode = None
        if game.casefold() == "pokemon":
            pokemon_variant_mode = _pokemon_variant_mode(source_variant_id)

        # Cardmarket's Pokemon price history is product-wide and does not expose
        # the Reverse Holo listing attribute. It is therefore unsafe for
        # variant-specific pricing and is deliberately skipped for Pokemon.
        history = None
        if pokemon_variant_mode is None:
            history = await self._client.get(
                scraper_id=CARDMARKET_PARSE_SCRAPER_ID,
                endpoint="get_price_history",
                snapshot_version=CARDMARKET_PARSE_SNAPSHOT_VERSION,
                params={"game": game, "expansion": expansion, "card": card},
            )
        listings = await self._client.get(
            scraper_id=CARDMARKET_PARSE_SCRAPER_ID,
            endpoint="get_card_listings",
            snapshot_version=CARDMARKET_PARSE_SNAPSHOT_VERSION,
            params={
                "game": game,
                "expansion": expansion,
                "card": card,
                "page": 1,
                "sort": "price_asc",
            },
        )
        if history is not None:
            _assert_identity(history, game=game, expansion=expansion, card=card)
        _assert_identity(listings, game=game, expansion=expansion, card=card)

        fx_cache: dict[str, FxQuote] = {}

        async def fx_for(observed_at: datetime) -> FxQuote:
            key = observed_at.date().isoformat()
            if key not in fx_cache:
                quote = await self._fx_provider.quote(
                    base_currency="EUR",
                    quote_currency="GBP",
                    at=observed_at,
                )
                quote.validate()
                if quote.base_currency.upper() != "EUR" or quote.quote_currency.upper() != "GBP":
                    raise ValueError("Cardmarket adapter requires an EUR to GBP FX quote")
                fx_cache[key] = quote
            return fx_cache[key]

        observations: dict[str, NormalizedMarketObservation] = {}

        charts = history.get("price_history", []) if history is not None else []
        if not isinstance(charts, list):
            raise ValueError("Cardmarket price_history must be an array")

        for chart in charts:
            if not isinstance(chart, dict):
                continue
            label = chart.get("label") if isinstance(chart.get("label"), str) else None
            period = chart.get("period") if isinstance(chart.get("period"), str) else None
            points = chart.get("data_points", [])
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                price_minor = _money_minor(point.get("price"))
                if price_minor is None:
                    continue
                observed_at = _history_timestamp(point.get("date"))
                fx = await fx_for(observed_at)
                key = stable_source_record_key(
                    "CARDMARKET",
                    canonical_url,
                    "MARKET_AGGREGATE",
                    observed_at.date().isoformat(),
                    price_minor,
                )
                observations.setdefault(
                    key,
                    NormalizedMarketObservation(
                        source="CARDMARKET",
                        source_record_key=key,
                        observation_type="MARKET_AGGREGATE",
                        observed_at=observed_at,
                        price_minor=price_minor,
                        currency="EUR",
                        price_gbp_minor=_to_gbp_minor(price_minor, fx),
                        fx_rate_to_gbp=float(fx.rate),
                        catalogue_id=catalogue_id,
                        condition=None,
                        language=None,
                        source_country="EU",
                        sample_size=1,
                        evidence_quality=0.90,
                        metadata={
                            "access_method": "PARSE_BOT",
                            "provider": "CARDMARKET",
                            "scraper_id": CARDMARKET_PARSE_SCRAPER_ID,
                            "snapshot_version": CARDMARKET_PARSE_SNAPSHOT_VERSION,
                            "endpoint": "get_price_history",
                            "source_product_id": canonical_url,
                            "source_variant_id": source_variant_id,
                            "game": game,
                            "expansion_slug": expansion,
                            "card_slug": card,
                            "chart_label": label,
                            "chart_period": period,
                            "statistic": "DAILY_AVERAGE_SELL_PRICE",
                            "card_wide_statistic": True,
                            "language_condition_breakdown_available": False,
                            "fx_source": fx.source,
                            "fx_effective_at": fx.effective_at.isoformat(),
                            "fx_retrieved_at": fx.retrieved_at.isoformat(),
                        },
                    ).validate(),
                )

        rows = listings.get("listings", [])
        if not isinstance(rows, list):
            raise ValueError("Cardmarket listings must be an array")
        retrieved_at = datetime.now(timezone.utc)
        active_fx = await fx_for(retrieved_at) if rows else None

        for row in rows:
            if not isinstance(row, dict):
                continue
            price_minor = _money_minor(row.get("price_eur", row.get("price")))
            if price_minor is None:
                continue
            if active_fx is None:
                raise RuntimeError("Cardmarket active listing FX quote is unavailable")

            condition = row.get("condition") if isinstance(row.get("condition"), str) else None
            attributes = [
                value.strip()
                for value in row.get("attributes", [])
                if isinstance(value, str) and value.strip()
            ] if isinstance(row.get("attributes"), list) else []
            if pokemon_variant_mode is not None and not _pokemon_listing_matches_variant(
                attributes,
                source_variant_id,
            ):
                continue
            language = _listing_language(attributes)
            listing_id = str(row.get("listing_id") or "").strip() or None
            try:
                quantity = max(1, int(row.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1

            seller_country = None
            seller = row.get("seller")
            if isinstance(seller, dict) and isinstance(seller.get("country"), str):
                seller_country = seller["country"].strip() or None
            elif isinstance(row.get("seller_country"), str):
                seller_country = row["seller_country"].strip() or None

            key = stable_source_record_key(
                "CARDMARKET",
                canonical_url,
                "ACTIVE",
                listing_id or seller_country or "unknown-listing",
                price_minor,
                condition,
                language,
                attributes,
                quantity,
            )
            observations[key] = NormalizedMarketObservation(
                source="CARDMARKET",
                source_record_key=key,
                observation_type="ACTIVE",
                observed_at=retrieved_at,
                price_minor=price_minor,
                currency="EUR",
                price_gbp_minor=_to_gbp_minor(price_minor, active_fx),
                fx_rate_to_gbp=float(active_fx.rate),
                catalogue_id=catalogue_id,
                condition=condition,
                language=language,
                source_country="EU",
                sample_size=1,
                evidence_quality=0.80,
                metadata={
                    "access_method": "PARSE_BOT",
                    "provider": "CARDMARKET",
                    "scraper_id": CARDMARKET_PARSE_SCRAPER_ID,
                    "snapshot_version": CARDMARKET_PARSE_SNAPSHOT_VERSION,
                    "endpoint": "get_card_listings",
                    "source_product_id": canonical_url,
                    "source_variant_id": source_variant_id,
                    "pokemon_variant_mode": pokemon_variant_mode,
                    "game": game,
                    "expansion_slug": expansion,
                    "card_slug": card,
                    "listing_id": listing_id,
                    "listing_quantity": quantity,
                    "attributes": attributes,
                    "seller_country": seller_country,
                    "page": listings.get("page", 1),
                    "retrievable_limit": listings.get("retrievable_limit"),
                    "fx_source": active_fx.source,
                    "fx_effective_at": active_fx.effective_at.isoformat(),
                    "fx_retrieved_at": active_fx.retrieved_at.isoformat(),
                },
            ).validate()

        return list(observations.values())
