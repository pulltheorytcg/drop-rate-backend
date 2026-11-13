"""Read-only eBay Browse service bridge for the independent Base44 API.

The existing Railway eBay OAuth client remains the only holder of eBay credentials.
This route is intentionally NEVER a sold-price source or a valuation engine.
"""
from __future__ import annotations

import hmac
import os
import re
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ebay_official_client import EbayApiError, EbayOfficialClient
from .settings import get_settings


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

SUPPORTED_CATEGORIES = frozenset({
    "pokemon", "one-piece", "naruto", "dragon-ball", "riftbound",
    "lorcana", "yugioh", "mtg", "comics", "manga", "funko",
    "figures", "sports", "lego", "sealed",
})
ALIASES = {
    "pokémon": "pokemon", "pokemon tcg": "pokemon",
    "one piece": "one-piece", "one piece card game": "one-piece",
    "dragon ball": "dragon-ball", "dragon ball super": "dragon-ball",
    "fusion world": "dragon-ball", "yu-gi-oh!": "yugioh",
    "yu-gi-oh": "yugioh", "yu gi oh": "yugioh",
    "magic": "mtg", "magic the gathering": "mtg",
    "disney lorcana": "lorcana", "funko pop": "funko",
    "funko pops": "funko", "figurines": "figures",
    "sports cards": "sports", "comic": "comics",
}
SEARCH_TERMS = {
    "pokemon": "Pokemon", "one-piece": "One Piece", "naruto": "Naruto",
    "dragon-ball": "Dragon Ball", "riftbound": "Riftbound",
    "lorcana": "Lorcana", "yugioh": "Yu-Gi-Oh",
    "mtg": "Magic Gathering", "comics": "comic",
    "manga": "manga", "funko": "Funko Pop",
    "figures": "figure", "sports": "sports card",
    "lego": "LEGO", "sealed": "sealed booster",
}
SAFE_TERM = re.compile(r"^[\w\s.\-/:#&'!()+]{1,150}$", re.UNICODE)


class MarketLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(default=None, min_length=2, max_length=80)
    game: str | None = Field(default=None, min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=150)
    set_name: str | None = Field(default=None, max_length=150)
    set_code: str | None = Field(default=None, max_length=80)
    card_number: str | None = Field(default=None, max_length=80)
    variant: str | None = Field(default=None, max_length=120)
    rarity: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)
    edition: str | None = Field(default=None, max_length=120)
    printing: str | None = Field(default=None, max_length=120)
    condition: str | None = Field(default=None, max_length=120)
    grading_company: str | None = Field(default=None, max_length=80)
    grade: str | None = Field(default=None, max_length=20)
    cert_number: str | None = Field(default=None, max_length=100)
    product_type: str | None = Field(default=None, max_length=120)
    publisher: str | None = Field(default=None, max_length=120)
    series: str | None = Field(default=None, max_length=120)
    issue_number: str | None = Field(default=None, max_length=80)
    volume: str | None = Field(default=None, max_length=80)
    isbn: str | None = Field(default=None, max_length=80)
    manufacturer: str | None = Field(default=None, max_length=120)
    franchise: str | None = Field(default=None, max_length=120)
    product_number: str | None = Field(default=None, max_length=80)
    seal_status: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def check_identity(self) -> "MarketLookup":
        category = (self.game or self.category or "").strip().lower()
        category = ALIASES.get(category, category)
        if category not in SUPPORTED_CATEGORIES:
            raise ValueError("Unsupported collectible category")
        if bool(self.grading_company) != bool(self.grade):
            raise ValueError("Grading company and grade are required together")
        for value in self.model_dump().values():
            if value is not None and not SAFE_TERM.fullmatch(value.strip()):
                raise ValueError("Invalid search term")
        return self

    @property
    def canonical_category(self) -> str:
        raw = (self.game or self.category or "").strip().lower()
        return ALIASES.get(raw, raw)


class MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lookup: MarketLookup


def build_search_query(lookup: MarketLookup) -> str:
    """Search hints only; not evidence of matching printing/condition/grade."""
    terms = [SEARCH_TERMS[lookup.canonical_category], lookup.name]
    for field in ("set_code", "set_name", "card_number", "variant",
                  "edition", "printing", "language", "grading_company", "grade",
                  "issue_number", "volume", "isbn", "product_number"):
        value = getattr(lookup, field)
        if value and value.lower() not in " ".join(terms).lower():
            terms.append(value)
    return " ".join(terms)[:350]


def extract_active_listings(payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    """Only explicit GBP asking prices; no unverified identity or sold claims."""
    rows = payload.get("itemSummaries", [])
    if not isinstance(rows, list):
        return []
    records: list[dict[str, Any]] = []
    for item in rows[:40]:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        if not isinstance(price, dict) or price.get("currency") != "GBP":
            continue
        value = price.get("value")
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", value):
            continue
        name = item.get("title")
        item_id = item.get("itemId")
        if not isinstance(name, str) or not isinstance(item_id, str):
            continue
        link = item.get("itemWebUrl")
        records.append({
            "source": "EBAY_BROWSE_UK",
            "evidence_type": "ACTIVE_ASKING_PRICE",
            "item_id": item_id,
            "title": name[:250],
            "item_url": link if isinstance(link, str) and link.startswith("https://www.ebay.") else None,
            "price": value,
            "currency": "GBP",
            "condition": item.get("condition"),
            "buying_options": item.get("buyingOptions", []),
            "identity_verified": False,
            "sold_price_verified": False,
        })
        if len(records) >= limit:
            break
    return records


def authorize_bridge(secret: str | None, provided: str | None) -> None:
    if (not secret or len(secret) < 32 or not provided
            or not hmac.compare_digest(secret, provided)):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/base44-ebay-browse")
async def base44_ebay_browse(
    request: MarketRequest,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
) -> dict[str, Any]:
    """Service-to-service ONLY, read-only, no Supabase or Shopify modifications."""
    authorize_bridge(os.getenv("BASE44_MARKET_API_KEY"), x_api_key)
    if os.getenv("BASE44_EBAY_BRIDGE_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=503, detail="eBay bridge is disabled")
    settings = get_settings()
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        raise HTTPException(status_code=503, detail="eBay Browse credentials not configured")
    query = build_search_query(request.lookup)
    client = EbayOfficialClient(
        client_id=settings.ebay_client_id,
        client_secret=settings.ebay_client_secret,
        marketplace_id=settings.ebay_marketplace_id,
        timeout_seconds=9.0,
    )
    try:
        data = await client.search_items(
            query=query, limit=15, item_location_country="GB",
            fixed_price_only=True,
        )
    except EbayApiError as exc:
        status = 429 if exc.status_code == 429 else 502
        raise HTTPException(status_code=status, detail="eBay Browse unavailable") from exc

    listings = extract_active_listings(data, limit=10)
    return {
        "schema_version": "1.0.0",
        "source": "EBAY_BROWSE_UK",
        "category": request.lookup.canonical_category,
        "query": request.lookup.model_dump(exclude_none=True),
        "status": "ACTIVE_CONTEXT_AVAILABLE" if listings else "NO_ACTIVE_LISTINGS",
        "evidence_type": "ACTIVE_ASKING_PRICE",
        "listings": listings,
        "verified_sold_count": 0,
        "market_value_eligible": False,
        "market_value_gbp": None,
        "identity_verified": False,
        "persisted": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
