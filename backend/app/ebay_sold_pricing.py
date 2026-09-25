from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_official_adapter import _looks_like_multi_item_listing, _variant_matches
from .ebay_uk_parse_adapter import _contains_term, _normalise_text
from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .ownership import current_owner as _owner
from .settings import get_settings


router = APIRouter(prefix="/api/v1/pricing/ebay-five-sold", tags=["pricing"])

_RAW_GRADED_TERMS = ("psa", "cgc", "bgs", "beckett", "graded", "slab")
_NON_ENGLISH_TERMS = (
    "japanese", "jpn", "jp", "korean", "kr", "chinese", "cn",
    "german", "french", "italian", "spanish", "portuguese",
)
_REPRINT_TERMS = ("reprint", "the best", "prb01", "prb02")
_TRAILING_DISAMBIGUATOR_RE = re.compile(r"\s*[\[(](?:\d{2,4}|\d{2,4}/\d{2,4})[\])]\s*$")


class TrawlApiError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


class TrawlEbaySoldClient:
    """Small server-side client for Trawl's eBay sold-data API.

    The API key is never exposed to the browser. This client requests UK sold
    results only; matching and price selection remain Drop Rate business logic.
    """

    def __init__(self, *, api_key: str, timeout_seconds: float = 20.0) -> None:
        clean = api_key.strip()
        if not clean:
            raise ValueError("Trawl API key is required")
        self._api_key = clean
        self._timeout = timeout_seconds

    async def sold(self, *, query: str, max_pages: int = 1) -> dict[str, Any]:
        params = {
            "query": query,
            "site": "EBAY_GB",
            "max_pages": max_pages,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    "https://api.trawl.dev/ebay/v1/sold",
                    params=params,
                    headers={"x-api-key": self._api_key, "accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise TrawlApiError("eBay sold-data provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise TrawlApiError("eBay sold-data provider request failed", retryable=True) from exc

        if response.status_code >= 500:
            raise TrawlApiError(
                "eBay sold-data provider is temporarily unavailable",
                status_code=response.status_code,
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise TrawlApiError(
                "eBay sold-data provider credentials were rejected",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise TrawlApiError(
                "eBay sold-data provider credit or rate limit was reached",
                status_code=429,
                retryable=True,
            )
        if response.status_code >= 400:
            raise TrawlApiError(
                "eBay sold-data provider rejected the request",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TrawlApiError("eBay sold-data provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TrawlApiError("eBay sold-data provider returned an invalid response shape")
        return payload


@dataclass(frozen=True, slots=True)
class SoldComparable:
    item_id: str
    title: str
    sold_at: datetime
    price_minor: int
    shipping_minor: int | None
    condition_raw: str | None
    url: str | None

    @property
    def delivered_minor(self) -> int | None:
        if self.shipping_minor is None:
            return None
        return self.price_minor + self.shipping_minor


def _money_minor(value: object, *, expected_currency: str | None = None, currency: object = None) -> int | None:
    if expected_currency is not None:
        if not isinstance(currency, str) or currency.strip().upper() != expected_currency:
            return None
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("£", "").replace(",", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sold_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    clean = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.strptime(clean, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_search_name(name: str, card_number: str) -> str:
    clean = " ".join(name.strip().split())
    # Collectr sometimes appends a numeric disambiguator such as "(073)".
    # The true collector number is already required separately.
    clean = _TRAILING_DISAMBIGUATOR_RE.sub("", clean).strip()
    return clean or name.strip()


def _language_matches(title: str, language: str) -> bool:
    normalised = _normalise_text(title)
    canonical = language.strip().casefold()
    if canonical == "japanese":
        return any(_contains_term(normalised, term) for term in ("japanese", "jpn", "jp"))
    if canonical == "english":
        return not any(_contains_term(normalised, term) for term in _NON_ENGLISH_TERMS)
    return _contains_term(normalised, language)


def _condition_matches(title: str, condition_raw: str | None, expected: str | None, *, graded: bool) -> bool:
    if graded:
        return True
    if not expected:
        return False
    combined = _normalise_text(" ".join(filter(None, (title, condition_raw))))
    expected_norm = _normalise_text(expected)
    aliases = {
        "near mint": ("near mint", "nm"),
        "lightly played": ("lightly played", "lp"),
        "moderately played": ("moderately played", "mp"),
        "heavily played": ("heavily played", "hp"),
        "damaged": ("damaged", "dmg"),
    }
    terms = aliases.get(expected_norm, (expected_norm,))
    return any(_contains_term(combined, term) for term in terms)


def _set_reprint_guard(title: str, game: str, set_name: str) -> bool:
    """Conservatively separate common One Piece reprint/promo wording."""
    if game.strip().casefold() != "one piece":
        return True
    title_norm = _normalise_text(title)
    set_norm = _normalise_text(set_name)
    canonical_is_reprint = any(term in set_norm for term in ("prb01", "prb02", "the best"))
    canonical_is_promo = "promotion" in set_norm or "promo" in set_norm
    if canonical_is_reprint:
        return any(_contains_term(title_norm, term) for term in ("prb01", "prb02", "the best", "reprint"))
    if canonical_is_promo:
        return any(_contains_term(title_norm, term) for term in ("promo", "promotion", "event", "campaign", "anniversary"))
    if any(_contains_term(title_norm, term) for term in _REPRINT_TERMS):
        return False
    return True


def _matches_comp(row: dict[str, Any], target: dict[str, Any]) -> bool:
    title = row.get("title")
    if not isinstance(title, str) or not title.strip():
        return False
    if _looks_like_multi_item_listing(title):
        return False

    card_number = target["card_number"]
    if not _contains_term(_normalise_text(title), card_number):
        return False
    search_name = _canonical_search_name(target["name"], card_number)
    if not _contains_term(_normalise_text(title), search_name):
        return False

    if not _language_matches(title, target["language"]):
        return False
    if not _set_reprint_guard(title, target["game"], target["set_name"]):
        return False

    grading_company = target["grading_company"]
    grade = target["grade"]
    if grading_company:
        if not _contains_term(_normalise_text(title), grading_company):
            return False
        if not _contains_term(_normalise_text(title), grade):
            return False
    else:
        if any(_contains_term(_normalise_text(title), term) for term in _RAW_GRADED_TERMS):
            return False

    if not _variant_matches(title, target["variant"]):
        return False

    condition_raw = row.get("condition_raw")
    if condition_raw is None and isinstance(row.get("condition"), str):
        condition_raw = row.get("condition")
    if not _condition_matches(
        title,
        condition_raw if isinstance(condition_raw, str) else None,
        target["condition"],
        graded=bool(grading_company),
    ):
        return False
    return True


def _query_for_target(target: dict[str, Any]) -> str:
    parts = [
        _canonical_search_name(target["name"], target["card_number"]),
        target["card_number"],
    ]
    if target["language"].strip().casefold() == "japanese":
        parts.append("Japanese")
    if target["grading_company"]:
        parts.extend((target["grading_company"], target["grade"]))
    variant = _normalise_text(target["variant"])
    if variant and variant != "normal":
        parts.append(target["variant"])
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def select_five_newest_comps(payload: dict[str, Any], *, target: dict[str, Any]) -> list[SoldComparable]:
    rows = payload.get("results", [])
    if not isinstance(rows, list):
        raise ValueError("Sold-data response is missing results")

    accepted: dict[str, SoldComparable] = {}
    for row in rows:
        if not isinstance(row, dict) or not _matches_comp(row, target):
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        sold_at = _sold_at(row.get("date_sold"))
        if sold_at is None:
            continue
        currency = row.get("currency")
        price_minor = _money_minor(row.get("sale_price"), expected_currency="GBP", currency=currency)
        if price_minor is None or price_minor <= 0:
            continue
        shipping_minor = _money_minor(row.get("shipping_price"))
        title = str(row.get("title") or "").strip()
        accepted[item_id] = SoldComparable(
            item_id=item_id,
            title=title,
            sold_at=sold_at,
            price_minor=price_minor,
            shipping_minor=shipping_minor,
            condition_raw=(str(row.get("condition_raw")).strip() if row.get("condition_raw") is not None else None),
            url=(str(row.get("item_link")).strip() if row.get("item_link") else None),
        )

    return sorted(accepted.values(), key=lambda comp: comp.sold_at, reverse=True)[:5]


def five_sold_store_price(comps: list[SoldComparable]) -> int:
    if len(comps) != 5:
        raise ValueError("Exactly five comparable sold records are required")
    return int(median([comp.price_minor for comp in comps]))


async def _target_snapshot(connection, owner_id: UUID, inventory_id: UUID) -> dict[str, Any]:
    row = await connection.fetchrow(
        """
        select
            i.id, i.owner_id, i.catalogue_id, i.version, i.status,
            i.condition, i.grading_company, i.grade, i.language,
            i.store_price_minor,
            p.product_type, p.game, p.name, p.set_name, p.card_number,
            p.variant, p.rarity
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        where i.id=$1 and i.owner_id=$2
        """,
        inventory_id, owner_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if row["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
        raise HTTPException(status_code=409, detail="Only active inventory can be priced")
    if row["product_type"] != "CARD":
        raise HTTPException(status_code=422, detail="Five-sold pricing v1 supports cards only")
    if not row["card_number"] or not str(row["card_number"]).strip():
        raise HTTPException(status_code=422, detail="Exact collector number is required for eBay sold pricing")
    if not row["language"] or not str(row["language"]).strip():
        raise HTTPException(status_code=422, detail="Physical language is required for eBay sold pricing")
    if not row["grading_company"] and not row["condition"]:
        raise HTTPException(status_code=422, detail="Condition or grade is required for eBay sold pricing")
    return dict(row)


async def _fetch_comp_result(target: dict[str, Any]) -> dict[str, Any]:
    api_key = get_settings().trawl_api_key
    if not api_key:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Trawl eBay sold-data access is not configured",
                "required_environment_variable": "TCG_TRAWL_API_KEY",
            },
        )
    client = TrawlEbaySoldClient(api_key=api_key)
    try:
        payload = await client.sold(query=_query_for_target(target), max_pages=1)
    except TrawlApiError as exc:
        raise HTTPException(
            status_code=502 if exc.status_code != 429 else 429,
            detail={
                "message": exc.detail,
                "provider_status_code": exc.status_code,
                "retryable": exc.retryable,
            },
        ) from exc

    comps = select_five_newest_comps(payload, target=target)
    if len(comps) < 5:
        return {
            "status": "BLOCKED",
            "reason": "Fewer than five exact comparable UK eBay sold records were found",
            "query": _query_for_target(target),
            "comparable_count": len(comps),
            "comps": comps,
            "store_price_minor": None,
        }
    return {
        "status": "READY",
        "reason": None,
        "query": _query_for_target(target),
        "comparable_count": 5,
        "comps": comps,
        "store_price_minor": five_sold_store_price(comps),
    }


async def _persist_comp(connection, target: dict[str, Any], comp: SoldComparable, *, query: str) -> bool:
    key = stable_source_record_key("EBAY", "TRAWL", comp.item_id, comp.sold_at.isoformat())
    observation = NormalizedMarketObservation(
        source="EBAY",
        source_record_key=key,
        observation_type="SOLD",
        observed_at=comp.sold_at,
        price_minor=comp.price_minor,
        shipping_minor=comp.shipping_minor,
        currency="GBP",
        price_gbp_minor=comp.price_minor,
        shipping_gbp_minor=comp.shipping_minor,
        fx_rate_to_gbp=1.0,
        catalogue_id=str(target["catalogue_id"]),
        condition=target["condition"],
        grading_company=target["grading_company"],
        grade=target["grade"],
        language=target["language"],
        source_country="GB",
        sample_size=1,
        evidence_quality=1.0,
        metadata={
            "access_method": "TRAWL_API",
            "provider": "TRAWL",
            "market_source": "EBAY",
            "marketplace": "EBAY_GB",
            "provider_item_id": comp.item_id,
            "url": comp.url,
            "title": comp.title,
            "query": query,
            "selection_rule": "FIVE_NEWEST_EXACT_COMPARABLE_SALES",
            "sale_price_excludes_shipping": True,
            "shipping_observed_separately": comp.shipping_minor is not None,
        },
    ).validate()
    row = await connection.fetchrow(
        """
        insert into tcg.market_observations(
            catalogue_id, source, source_record_key, observation_type, observed_at,
            price_minor, shipping_minor, currency, price_gbp_minor, shipping_gbp_minor,
            fx_rate_to_gbp, condition, grading_company, grade, language, seal_status,
            source_country, sample_size, evidence_quality, metadata
        ) values(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20::jsonb
        )
        on conflict (source, source_record_key) do nothing
        returning id
        """,
        UUID(observation.catalogue_id), observation.source, observation.source_record_key,
        observation.observation_type, observation.observed_at, observation.price_minor,
        observation.shipping_minor, observation.currency, observation.price_gbp_minor,
        observation.shipping_gbp_minor, observation.fx_rate_to_gbp, observation.condition,
        observation.grading_company, observation.grade, observation.language,
        observation.seal_status, observation.source_country, observation.sample_size,
        observation.evidence_quality, __import__("json").dumps(observation.metadata),
    )
    return row is not None


async def _price_one(pool, *, user_id: UUID, request_id: str, inventory_id: UUID, apply: bool) -> dict[str, Any]:
    async with user_connection(pool, user_id, request_id) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]
        target = await _target_snapshot(connection, owner_id, inventory_id)

    result = await _fetch_comp_result(target)
    serialised_comps = [
        {
            "item_id": comp.item_id,
            "title": comp.title,
            "sold_at": comp.sold_at,
            "price_minor": comp.price_minor,
            "shipping_minor": comp.shipping_minor,
            "url": comp.url,
        }
        for comp in result["comps"]
    ]
    if result["status"] != "READY" or not apply:
        return {
            "inventory_id": inventory_id,
            **{key: value for key, value in result.items() if key != "comps"},
            "comps": serialised_comps,
            "applied": False,
        }

    async with user_connection(pool, user_id, request_id) as connection:
        current_owner = await _owner(connection)
        if current_owner["id"] != owner_id:
            raise HTTPException(status_code=409, detail="Owner context changed during pricing")
        async with connection.transaction():
            current = await _target_snapshot(connection, owner_id, inventory_id)
            fields = (
                "catalogue_id", "condition", "grading_company", "grade", "language",
                "game", "name", "set_name", "card_number", "variant",
            )
            if current["version"] != target["version"] or any(current[field] != target[field] for field in fields):
                raise HTTPException(status_code=409, detail="Inventory identity changed during eBay sold lookup")

            inserted = 0
            for comp in result["comps"]:
                if await _persist_comp(connection, current, comp, query=result["query"]):
                    inserted += 1

            updated = await connection.fetchrow(
                """
                update tcg.inventory_items
                   set store_price_minor=$1,
                       market_value_minor=$1,
                       recommended_retail_minor=$1,
                       pricing_updated_at=now(),
                       version=version+1,
                       updated_at=now()
                 where id=$2 and owner_id=$3 and version=$4
                 returning id,inventory_code,store_price_minor,market_value_minor,
                           recommended_retail_minor,pricing_updated_at,version
                """,
                result["store_price_minor"], inventory_id, owner_id, current["version"],
            )
            if updated is None:
                raise HTTPException(status_code=409, detail="Inventory changed during Store Price update")

    return {
        "inventory_id": inventory_id,
        "status": "PRICED",
        "query": result["query"],
        "comparable_count": 5,
        "store_price_minor": result["store_price_minor"],
        "comps": serialised_comps,
        "inserted_observations": inserted,
        "applied": True,
        "inventory": dict(updated),
    }


@router.get("/status")
async def ebay_five_sold_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            """
            select
              count(*) filter(where i.status in ('DRAFT','INSPECTION','APPROVED'))::int as active_items,
              count(*) filter(where i.status in ('DRAFT','INSPECTION','APPROVED') and i.store_price_minor is null)::int as missing_store_price,
              count(distinct (i.catalogue_id,i.condition,i.grading_company,i.grade,i.language))
                filter(where i.status in ('DRAFT','INSPECTION','APPROVED') and i.store_price_minor is null)::int as missing_price_groups
            from tcg.inventory_items i
            where i.owner_id=$1
            """,
            owner["id"],
        )
    return jsonable_encoder({
        "configured": bool(settings.trawl_api_key),
        "method": "median of five newest exact comparable eBay UK sold item prices; shipping recorded separately",
        **dict(row),
    })


@router.post("/{inventory_id}/preview")
async def preview_ebay_five_sold(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    return jsonable_encoder(
        await _price_one(
            request.app.state.db_pool,
            user_id=user.user_id,
            request_id=request.state.request_id,
            inventory_id=inventory_id,
            apply=False,
        )
    )


@router.post("/{inventory_id}/apply")
async def apply_ebay_five_sold(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    return jsonable_encoder(
        await _price_one(
            request.app.state.db_pool,
            user_id=user.user_id,
            request_id=request.state.request_id,
            inventory_id=inventory_id,
            apply=True,
        )
    )


@router.post("/batch/apply-missing")
async def apply_missing_ebay_five_sold(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=10, ge=1, le=25),
) -> dict:
    """Price a bounded number of distinct physical pricing identities.

    One provider call is reused across identical physical copies. Cards that do
    not produce five exact comps remain unchanged and are returned as BLOCKED.
    """
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select distinct on (
                i.catalogue_id, i.condition, i.grading_company, i.grade, i.language
            )
                i.id
            from tcg.inventory_items i
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and i.store_price_minor is null
            order by i.catalogue_id,i.condition,i.grading_company,i.grade,i.language,i.created_at,i.id
            limit $2
            """,
            owner["id"], limit,
        )

    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            result = await _price_one(
                request.app.state.db_pool,
                user_id=user.user_id,
                request_id=request.state.request_id,
                inventory_id=row["id"],
                apply=True,
            )
        except HTTPException as exc:
            result = {
                "inventory_id": row["id"],
                "status": "ERROR",
                "applied": False,
                "status_code": exc.status_code,
                "detail": exc.detail,
            }
        results.append(result)

    return jsonable_encoder({
        "requested_groups": len(rows),
        "priced_groups": sum(1 for result in results if result.get("applied")),
        "blocked_groups": sum(1 for result in results if not result.get("applied")),
        "results": results,
    })
