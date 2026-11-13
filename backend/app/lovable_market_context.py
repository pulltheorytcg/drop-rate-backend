"""Authenticated on-demand Drop Rate catalogue -> Lovable eBay candidate bridge.

Read-only owner/admin preview. No record, quote, valuation or Shopify write.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .lovable_market_client import LovableMarketClient, LovableMarketError
from .market_ingestion import _owner

router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

_SYSTEM_GAME = {
    "POKEMON_TCG": "Pokemon",
    "ONE_PIECE_CARD_GAME": "One Piece",
    "DRAGON_BALL_SUPER_MASTERS": "Dragon Ball Masters",
    "DRAGON_BALL_SUPER_FUSION_WORLD": "Dragon Ball Fusion World",
    "NARUTO_BANDAI_LEGACY": "Naruto",
    "NARUTO_KAYOU": "Naruto",
    "YUGIOH": "Yu-Gi-Oh",
    "MTG": "Magic",
    "DISNEY_LORCANA": "Lorcana",
    "RIFTBOUND": "Riftbound",
}
_PRODUCT_CATEGORY = {
    "CARD": "tcg", "SEALED": "sealed_tcg", "COMIC": "comic",
    "FIGURE": "figure", "FUNKO": "funko", "LEGO": "lego",
}


class LovablePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["catalogue", "reference_card", "reference_sealed"]
    catalogue_id: UUID | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=100)
    system_code: str | None = Field(default=None, min_length=1, max_length=100)
    language: str | None = Field(default=None, min_length=1, max_length=80)
    provider_id: str | None = Field(default=None, min_length=1, max_length=200)
    condition: str | None = Field(default=None, min_length=1, max_length=80)
    grading_company: Literal["PSA", "BGS", "CGC", "SGC", "TAG", "CBCS", "PGX"] | None = None
    grade: str | None = Field(default=None, pattern=r"^(?:10(?:\.0)?|[0-9](?:\.\d)?)$")

    @model_validator(mode="after")
    def validate_identity(self) -> "LovablePreviewRequest":
        is_catalogue = self.source_kind == "catalogue"
        if is_catalogue != (self.catalogue_id is not None):
            raise ValueError("Provide catalogue_id for catalogue source only")
        if not is_catalogue and not all((self.provider, self.system_code, self.language, self.provider_id)):
            raise ValueError("Reference provider/system/language/id required")
        if bool(self.grade) != bool(self.grading_company):
            raise ValueError("Grade and grader must be supplied together")
        return self


def canonical_lookup(row: dict, source_kind: str, *, condition: str | None,
                     grading_company: str | None, grade: str | None) -> dict[str, str]:
    """Build identity from Supabase, not an arbitrary caller-entered search."""
    ptype = str(row.get("product_type") or "CARD").upper()
    game = str(row.get("game") or "").strip()
    if source_kind.startswith("reference_"):
        game = _SYSTEM_GAME.get(str(row.get("system_code") or "").upper(), "")
        if source_kind == "reference_sealed":
            ptype = "SEALED"
    category = _PRODUCT_CATEGORY.get(ptype)
    if ptype == "COMIC":
        category = "manga" if game.casefold() == "manga" else "comic"
    if ptype == "CARD" and game.casefold() in {"sports cards", "sports"}:
        category = "sports"
    if not category:
        raise HTTPException(status_code=422, detail="Collectible type unsupported")
    name = str(row.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Catalogue name unavailable")
    params: dict[str, str | None] = {
        "category": category,
        "name": name,
        "game": game if category in {"tcg", "sports", "sealed_tcg"} and game else None,
        "set_name": row.get("set_name"),
        "set_code": row.get("set_code"),
        "card_number": row.get("card_number") if category in {"tcg", "sports"} else None,
        "rarity": row.get("rarity") if category in {"tcg", "sports"} else None,
        "variant": row.get("variant"),
        "language": row.get("language") if row.get("language") not in {"Unknown", "Mixed"} else None,
        "condition": condition,
        "grading_company": grading_company,
        "grade": grade,
        "issue_number": row.get("card_number") if category == "comic" else None,
        "volume": row.get("card_number") if category == "manga" else None,
        "product_type": row.get("sealed_product_type") if category == "sealed_tcg" else None,
    }
    # Skip null/empty fields; never fill in guessed finish/language/grade.
    return {key: str(v)[:160] for key, v in params.items() if v is not None and str(v).strip()}


async def fetch_catalogue_identity(connection, payload: LovablePreviewRequest) -> dict:
    if payload.source_kind == "catalogue":
        row = await connection.fetchrow(
            """select p.id,p.product_type,p.game,p.name,p.set_name,p.card_number,
                   p.rarity,p.variant,p.language,pr.set_code,
                   null::text as sealed_product_type
               from tcg.catalogue_products p
               left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
               where p.id=$1""", payload.catalogue_id,
        )
    elif payload.source_kind == "reference_card":
        row = await connection.fetchrow(
            """select r.provider,r.system_code,r.language,r.provider_id,
                   r.name,r.card_number,r.rarity,
                   s.name as set_name,r.set_id as set_code,
                   null::text as variant,'CARD'::text as product_type
               from tcg.reference_cards r left join tcg.reference_sets s
                 on s.provider=r.provider and s.system_code=r.system_code
                  and s.language=r.language and s.set_id=r.set_id
               where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4""",
            payload.provider, payload.system_code, payload.language, payload.provider_id,
        )
    else:
        row = await connection.fetchrow(
            """select r.provider,r.system_code,r.language,r.provider_id,r.name,
                   s.name as set_name,r.set_id as set_code,
                   r.product_type as sealed_product_type,
                   'SEALED'::text as product_type
               from tcg.reference_sealed_products r left join tcg.reference_sets s
                 on s.provider=r.provider and s.system_code=r.system_code
                  and s.language=r.language and s.set_id=r.set_id
               where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4""",
            payload.provider, payload.system_code, payload.language, payload.provider_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Catalogue identity not found")
    return dict(row)


@router.get("/lovable-health")
async def lovable_health() -> dict:
    """Owner/admin check without consuming a single eBay Browse request."""
    try:
        return await LovableMarketClient.from_environment().health()
    except LovableMarketError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc


@router.post("/lovable-context")
async def lovable_context(
    payload: LovablePreviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """On-demand, read-only candidate evidence. All public values stay untouched."""
    try:
        client = LovableMarketClient.from_environment()
    except LovableMarketError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _owner(connection)
        identity = await fetch_catalogue_identity(connection, payload)
    lookup = canonical_lookup(
        identity, payload.source_kind, condition=payload.condition,
        grading_company=payload.grading_company, grade=payload.grade,
    )
    try:
        response = await client.search(lookup)
    except LovableMarketError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    return {
        **response,
        "lookup": lookup,
        "pricing_authority": "DROP_RATE_RAILWAY",
        "source_identity": {
            "source_kind": payload.source_kind,
            "catalogue_id": str(payload.catalogue_id) if payload.catalogue_id else None,
            "provider": payload.provider if payload.source_kind != "catalogue" else None,
            "provider_id": payload.provider_id if payload.source_kind != "catalogue" else None,
        },
    }
