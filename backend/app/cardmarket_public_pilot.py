"""Read-only Cardmarket daily-export feasibility for exact MTGJSON printings.

No API requests, scraping, database access, R2 writes, owner data or publication.
Callers provide previously downloaded official public datasets and the original
MTGJSON UUID/identifier facts; only an exact Cardmarket product ID plus matching
name, release and finish can produce a *candidate guide*, never a sold value.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from .fx import ECB_SOURCE, FxQuote
from .market_guide_fields import choose_bulk_price_field

SOURCE = "CARDMARKET_PUBLIC_DAILY_EXPORT"
SCHEMA = "drop-rate-cardmarket-mtg-readonly-pilot-v1"
MAX_SOURCE_ROWS = 300_000
VALID_FINISHES = {"nonfoil": "trend", "foil": "trend-foil"}
MAX_AGE = timedelta(days=3)


class PilotError(ValueError):
    """Unsafe, incomplete or incompatible source evidence."""


def _time(value) -> datetime:
    if not isinstance(value, str):
        raise PilotError("Missing source timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotError("Invalid source timestamp") from exc
    if dt.utcoffset() is None:
        raise PilotError("Source timestamp is not timezone-aware")
    return dt.astimezone(timezone.utc)


def _name(value) -> str:
    # Strict readable text, not a lossy name-to-ID matcher.
    return " ".join(str(value or "").strip().casefold().split())


def _id(value) -> int | None:
    if type(value) is int:
        return value if 0 < value <= 2**31 - 1 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal() and value[0] != "0":
        result = int(value)
        return result if 0 < result <= 2**31 - 1 else None
    return None


def _rows(payload, field: str, *, now: datetime) -> tuple[list[dict], datetime]:
    if not isinstance(payload, dict):
        raise PilotError("Source file must be an object")
    ts = _time(payload.get("createdAt"))
    if ts > now or ts < now - MAX_AGE:
        raise PilotError("Source export is future-dated or stale")
    values = payload.get(field)
    if not isinstance(values, list) or not 0 < len(values) <= MAX_SOURCE_ROWS:
        raise PilotError("Source export has unsupported row count")
    if any(not isinstance(row, dict) for row in values):
        raise PilotError("Source export has malformed rows")
    return values, ts


def _mtg_identity_cards(cards: list[dict]) -> tuple[dict, set]:
    """Return an exact MCM-ID crosswalk; quarantine any product-ID conflict."""
    if not isinstance(cards, list) or len(cards) > MAX_SOURCE_ROWS:
        raise PilotError("MTGJSON reference subset is unbounded")
    by_id: dict[int, dict] = {}
    collisions: set[int] = set()
    for card in cards:
        if not isinstance(card, dict) or card.get("language") != "English" or card.get("paper") is not True:
            continue
        identifiers = card.get("identifiers")
        source_id = _id(identifiers.get("mcmId")) if isinstance(identifiers, dict) else None
        if source_id is None:
            continue
        try:
            uid = str(UUID(str(card["uuid"])))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        name, set_name = _name(card.get("name")), _name(card.get("set_name"))
        if not name or not set_name or not isinstance(card.get("finishes"), list):
            continue
        finishes = card["finishes"]
        if len(finishes) != len(set(finishes)) or not all(isinstance(finish, str) for finish in finishes):
            continue
        valid = {finish for finish in finishes if finish in VALID_FINISHES}
        if not valid:
            continue
        identity = {"uuid": uid, "name": name, "set_name": set_name, "finishes": valid}
        if source_id in by_id and by_id[source_id] != identity:
            collisions.add(source_id)
        else:
            by_id[source_id] = identity
    for blocked in collisions:
        by_id.pop(blocked, None)
    return by_id, collisions


def read_only_mtg_pilot(*, mtg_cards: list[dict], products_export: dict,
                        price_export: dict, fx: FxQuote, now: datetime) -> dict:
    """Exact source-ID feasibility. Never returns market_value_minor or prices for physical items."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise PilotError("Pilot clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if (fx.base_currency != "EUR" or fx.quote_currency != "GBP" or
            fx.source != ECB_SOURCE or fx.rate <= 0 or not fx.rate.is_finite() or
            fx.effective_at.utcoffset() is None or fx.retrieved_at.utcoffset() is None or
            fx.effective_at > now or fx.retrieved_at > now):
        raise PilotError("Validated ECB EUR/GBP evidence is required")
    products, product_checked = _rows(products_export, "products", now=now)
    guides, price_checked = _rows(price_export, "priceGuides", now=now)
    if abs(product_checked - price_checked) > timedelta(days=2) or (
            price_checked - fx.effective_at > timedelta(days=7)):
        raise PilotError("Source snapshots and FX evidence are not aligned")

    products_by_id: dict[int, dict] = {}
    for product in products:
        product_id = _id(product.get("idProduct"))
        if product_id is None or product_id in products_by_id:
            raise PilotError("Invalid or duplicate Cardmarket catalogue ID")
        products_by_id[product_id] = product
    guide_by_id: dict[int, dict] = {}
    for guide in guides:
        product_id = _id(guide.get("idProduct"))
        if product_id is None or product_id in guide_by_id:
            raise PilotError("Invalid or duplicate Cardmarket guide ID")
        guide_by_id[product_id] = guide

    identities, collisions = _mtg_identity_cards(mtg_cards)
    candidates = []
    rejected = defaultdict(int)
    for mcm_id, identity in sorted(identities.items()):
        product, guide = products_by_id.get(mcm_id), guide_by_id.get(mcm_id)
        if not product or not guide:
            rejected["MISSING_EXACT_ID"] += 1
            continue
        if (product.get("categoryName") != "Magic Single" or
                _name(product.get("name")) != identity["name"] or
                _name(product.get("expansionName")) != identity["set_name"]):
            rejected["IDENTITY_MISMATCH"] += 1
            continue
        for finish in sorted(identity["finishes"]):
            selected = choose_bulk_price_field(guide, VALID_FINISHES[finish])
            if selected is None:
                rejected["NO_EXACT_FINISH_GUIDE"] += 1
                continue
            eur_minor, guide_field = selected
            gbp_minor = int((Decimal(eur_minor) * fx.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if gbp_minor <= 0:
                rejected["INVALID_GBP"] += 1
                continue
            candidates.append({
                "status": "PILOT_ONLY", "source": SOURCE,
                "provider": "MTGJSON", "system_code": "MAGIC_THE_GATHERING",
                "language": "English", "provider_id": f"mtgjson:{identity['uuid']}:{finish}",
                "cardmarket_product_id": mcm_id, "finish": finish,
                "price_eur_minor": eur_minor, "guide_gbp_minor": gbp_minor,
                "source_field": guide_field, "source_checked_at": price_checked.isoformat(),
                "fx_rate_to_gbp": str(fx.rate), "fx_source": fx.source,
                "fx_effective_at": fx.effective_at.isoformat(),
                "match_basis": "EXACT_MTGINDEX_MCM_ID_AND_CATALOGUE_NAME_SET_FINISH_V1",
                "sold_observation_count": 0, "physical_valuation_eligible": False,
                "publishable": False,
            })
    return {
        "schema": SCHEMA, "status": "PILOT_ONLY_NO_PUBLICATION",
        "products_examined": len(products), "guides_examined": len(guides),
        "crosswalk_unique_ids": len(identities), "crosswalk_collision_ids": len(collisions),
        "candidate_count": len(candidates), "rejected": dict(rejected),
        "source_checked_at": price_checked.isoformat(), "candidates": candidates,
        "database_writes": 0, "object_storage_writes": 0, "store_price_changes": 0,
        "verified_sold_value_count": 0,
    }
