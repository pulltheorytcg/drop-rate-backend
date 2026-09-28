from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .brands import brand_sql
from .db import user_connection
from .physical_state import validate_physical_state
from .pricing import _recalculate_one


router = APIRouter(prefix="/api/v1/owner", tags=["owner-portal"])
BRAND_SQL = brand_sql("p")
VISIBLE_STATUSES = ("DRAFT", "INSPECTION", "APPROVED", "RESERVED", "SOLD", "WITHDRAWN")
OWNER_SCAN_SOURCE = "OWNER_SCAN"


class OwnerRecognitionIntakeRequest(BaseModel):
    recognition_run_id: UUID
    selected_catalogue_id: UUID
    condition: str | None = Field(default=None, max_length=80)
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_physical_details(self) -> "OwnerRecognitionIntakeRequest":
        self.condition = self.condition.strip() if self.condition else None
        self.grading_company = self.grading_company.strip() if self.grading_company else None
        self.grade = self.grade.strip() if self.grade else None
        self.certificate_number = self.certificate_number.strip() if self.certificate_number else None
        self.language = self.language.strip() if self.language else None

        if (self.grading_company is None) != (self.grade is None):
            raise ValueError("grading_company and grade must both be set or both cleared")
        if self.certificate_number and not self.grading_company:
            raise ValueError("certificate_number requires grading_company and grade")
        if self.condition is None and self.grading_company is None:
            raise ValueError("Choose a raw-card condition or provide grading company and grade")
        return self


def _owner_scan_payload_hash(payload: OwnerRecognitionIntakeRequest) -> str:
    canonical = payload.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _owner_scan_inventory_payload(row: object, catalogue: object, *, replayed: bool, valuation: dict | None = None, valuation_error: str | None = None) -> dict:
    inventory = dict(row)
    catalogue_row = dict(catalogue)
    recommended = inventory.get("recommended_retail_minor")
    store_price = inventory.get("store_price_minor")
    has_valuation = (
        valuation is not None
        or inventory.get("market_value_minor") is not None
        or recommended is not None
        or store_price is not None
    )
    return {
        "inventory": {
            "id": inventory.get("id"),
            "inventory_code": inventory.get("inventory_code"),
            "catalogue_id": inventory.get("catalogue_id"),
            "status": inventory.get("status"),
            "condition": inventory.get("condition"),
            "grading_company": inventory.get("grading_company"),
            "grade": inventory.get("grade"),
            "certificate_number": inventory.get("certificate_number"),
            "language": inventory.get("language"),
            "identity_confirmed": bool(inventory.get("identity_confirmed")),
            "market_value_minor": inventory.get("market_value_minor"),
            "recommended_retail_minor": recommended,
            "store_price_minor": store_price,
            "store_value_minor": store_price if store_price is not None else recommended,
            "pricing_updated_at": inventory.get("pricing_updated_at"),
            "created_at": inventory.get("created_at"),
            "updated_at": inventory.get("updated_at"),
        },
        "catalogue": {
            "id": catalogue_row.get("id"),
            "product_type": catalogue_row.get("product_type"),
            "game": catalogue_row.get("game"),
            "name": catalogue_row.get("name"),
            "set_name": catalogue_row.get("set_name"),
            "card_number": catalogue_row.get("card_number"),
            "variant": catalogue_row.get("variant"),
            "rarity": catalogue_row.get("rarity"),
            "language": catalogue_row.get("language"),
        },
        "identity_status": "SELLER_CONFIRMED_PENDING_DROP_RATE_VERIFICATION",
        "valuation": {
            "status": "CALCULATED" if has_valuation else "UNAVAILABLE",
            "snapshot": valuation.get("snapshot") if valuation is not None else None,
            "detail": valuation_error,
        },
        "replayed": replayed,
    }


@router.get("/overview")
async def owner_overview(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
) -> dict:
    owner_id = access["owner_id"]
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        summary = await connection.fetchrow(
            """
            select
                count(*)::int as total_inventory_count,
                count(*) filter (where status='DRAFT')::int as draft_count,
                count(*) filter (where status='INSPECTION')::int as inspection_count,
                count(*) filter (where status='APPROVED')::int as approved_count,
                count(*) filter (where status='RESERVED')::int as reserved_count,
                count(*) filter (where status='SOLD')::int as sold_count,
                count(*) filter (where status='WITHDRAWN')::int as withdrawn_count,
                coalesce(sum(market_value_minor) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_market_value_minor,
                coalesce(sum(store_price_minor) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_store_price_minor,
                coalesce(sum(coalesce(store_price_minor,recommended_retail_minor)) filter (
                    where status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
                ),0)::bigint as active_store_value_minor
            from tcg.inventory_items
            where owner_id=$1
            """,
            owner_id,
        )

    return jsonable_encoder(
        {
            "owner": {
                "display_name": access["display_name"],
                "owner_type": access["owner_type"],
            },
            "summary": dict(summary),
        }
    )


@router.get("/inventory")
async def owner_inventory(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    search: str | None = Query(default=None, max_length=160),
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    owner_id = access["owner_id"]
    search_value = (search or "").strip()
    status_value = (status or "").strip().upper()

    params: list[object] = [owner_id]
    filters = ["i.owner_id=$1"]

    if search_value:
        params.append(f"%{search_value}%")
        idx = len(params)
        filters.append(
            f"""(
                i.inventory_code ilike ${idx}
                or p.name ilike ${idx}
                or p.set_name ilike ${idx}
                or coalesce(p.card_number,'') ilike ${idx}
                or p.game ilike ${idx}
            )"""
        )

    if status_value:
        if status_value not in VISIBLE_STATUSES:
            filters.append("false")
        else:
            params.append(status_value)
            filters.append(f"i.status=${len(params)}")

    where = " and ".join(filters)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        total = await connection.fetchval(
            f"""
            select count(*)::int
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where {where}
            """,
            *params,
        )

        page_params = [*params, limit, offset]
        rows = await connection.fetch(
            f"""
            select
                i.inventory_code,
                p.product_type,
                p.game,
                {BRAND_SQL} as brand,
                p.name,
                p.set_name,
                p.card_number,
                p.variant,
                p.rarity,
                coalesce(i.language,p.language) as language,
                i.condition,
                i.grading_company,
                i.grade,
                i.status,
                i.market_value_minor,
                i.store_price_minor,
                i.recommended_retail_minor,
                i.pricing_updated_at,
                i.created_at,
                i.updated_at,
                (
                    select coalesce(m.shopify_cdn_url,m.public_source_url)
                    from tcg.media_assets m
                    where (
                        (m.scope='INVENTORY_ITEM' and m.inventory_id=i.id)
                        or (
                            m.scope='CANONICAL_CARD'
                            and m.inventory_id is null
                            and m.catalogue_id=i.catalogue_id
                        )
                    )
                      and m.approval_status='APPROVED'
                      and m.rights_status='VERIFIED'
                      and m.rights_tier='STOREFRONT_ALLOWED'
                      and m.source_status='ACTIVE'
                      and m.revoked_at is null
                      and coalesce(m.shopify_cdn_url,m.public_source_url) is not null
                    order by
                      (m.inventory_id=i.id) desc,
                      (m.side='FRONT') desc,
                      m.approved_at desc nulls last,
                      m.created_at desc
                    limit 1
                ) as image_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where {where}
            order by i.updated_at desc,i.inventory_code
            limit ${len(page_params)-1} offset ${len(page_params)}
            """,
            *page_params,
        )

    return jsonable_encoder(
        {
            "owner": {
                "display_name": access["display_name"],
                "owner_type": access["owner_type"],
            },
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }
    )


@router.post("/recognition-intake", status_code=201)
async def owner_recognition_intake(
    payload: OwnerRecognitionIntakeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
) -> dict:
    """Create restricted seller-owned DRAFT inventory from a human-confirmed scan."""

    try:
        request_key = UUID(idempotency_key.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Idempotency-Key must be a UUID") from exc

    owner_id = UUID(str(access["owner_id"]))
    payload_hash = _owner_scan_payload_hash(payload)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        existing = await connection.fetchrow(
            """
            select i.*
            from tcg.inventory_items i
            where i.owner_id=$1 and i.intake_request_key=$2
            """,
            owner_id,
            request_key,
        )
        if existing is not None:
            source_record = existing["source_record"] or {}
            if isinstance(source_record, str):
                try:
                    source_record = json.loads(source_record)
                except json.JSONDecodeError:
                    source_record = {}
            if (
                not isinstance(source_record, dict)
                or source_record.get("source") != OWNER_SCAN_SOURCE
                or source_record.get("payload_hash") != payload_hash
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used for a different seller intake",
                )
            catalogue = await connection.fetchrow(
                "select * from tcg.catalogue_products where id=$1",
                existing["catalogue_id"],
            )
            if catalogue is None:
                raise HTTPException(status_code=409, detail="Seller intake catalogue is missing")
            return jsonable_encoder(
                _owner_scan_inventory_payload(existing, catalogue, replayed=True)
            )

        run = await connection.fetchrow(
            """
            select
                r.id,r.status,r.decision,r.top_catalogue_id,
                c.id as candidate_id,c.catalogue_id,c.hard_rejected
            from tcg.recognition_runs r
            join tcg.recognition_candidates c
              on c.run_id=r.id and c.catalogue_id=$3
            where r.id=$1
              and r.owner_id=$2
            order by c.rank
            limit 1
            """,
            payload.recognition_run_id,
            owner_id,
            payload.selected_catalogue_id,
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail="Recognition run or selected candidate was not found for this seller",
            )
        if run["status"] not in {"EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH"}:
            raise HTTPException(status_code=409, detail="Recognition run is not ready for confirmation")
        if run["hard_rejected"]:
            raise HTTPException(status_code=422, detail="A rejected recognition candidate cannot be added")

        feedback = await connection.fetchrow(
            """
            select outcome,selected_catalogue_id
            from tcg.recognition_feedback
            where run_id=$1 and owner_id=$2
            order by created_at desc,id desc
            limit 1
            """,
            payload.recognition_run_id,
            owner_id,
        )
        if (
            feedback is None
            or feedback["outcome"] not in {"CONFIRMED_TOP", "CORRECTED_TO_CANDIDATE"}
            or feedback["selected_catalogue_id"] != payload.selected_catalogue_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Confirm the selected recognition candidate before adding it to inventory",
            )

        catalogue = await connection.fetchrow(
            "select * from tcg.catalogue_products where id=$1",
            payload.selected_catalogue_id,
        )
        if catalogue is None:
            raise HTTPException(status_code=404, detail="Catalogue product not found")
        if catalogue["product_type"] != "CARD":
            raise HTTPException(status_code=422, detail="Seller scan intake currently supports cards only")

        try:
            validate_physical_state(
                product_type=catalogue["product_type"],
                condition=payload.condition,
                seal_status=None,
                grading_company=payload.grading_company,
                grade=payload.grade,
                certificate_number=payload.certificate_number,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        inventory_id = uuid4()
        inventory_code = f"INV-{inventory_id.hex.upper()}"
        physical_language = payload.language or catalogue["language"]
        source_record = {
            "source": OWNER_SCAN_SOURCE,
            "recognition_run_id": str(payload.recognition_run_id),
            "selected_catalogue_id": str(payload.selected_catalogue_id),
            "payload_hash": payload_hash,
            "seller_confirmed": True,
        }

        inventory = await connection.fetchrow(
            """
            insert into tcg.inventory_items(
                id,inventory_code,catalogue_id,owner_id,
                condition,grading_company,grade,certificate_number,language,
                identity_confirmed,status,intake_request_key,source_record,sale_intent
            ) values(
                $1,$2,$3,$4,
                $5,$6,$7,$8,$9,
                false,'DRAFT',$10,$11::jsonb,'FOR_SALE'
            )
            on conflict (intake_request_key) do nothing
            returning *
            """,
            inventory_id,
            inventory_code,
            payload.selected_catalogue_id,
            owner_id,
            payload.condition,
            payload.grading_company,
            payload.grade,
            payload.certificate_number,
            physical_language,
            request_key,
            json.dumps(source_record),
        )
        if inventory is None:
            raise HTTPException(
                status_code=409,
                detail="Seller intake conflicted; refresh inventory before retrying",
            )

        valuation: dict | None = None
        valuation_error: str | None = None
        try:
            valuation = await _recalculate_one(connection, owner_id, inventory_id)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            valuation_error = str(exc.detail)

        inventory = await connection.fetchrow(
            "select * from tcg.inventory_items where id=$1 and owner_id=$2",
            inventory_id,
            owner_id,
        )
        if inventory is None:
            raise HTTPException(status_code=409, detail="Seller inventory creation could not be verified")

        return jsonable_encoder(
            _owner_scan_inventory_payload(
                inventory,
                catalogue,
                replayed=False,
                valuation=valuation,
                valuation_error=valuation_error,
            )
        )
