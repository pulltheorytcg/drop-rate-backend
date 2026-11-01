"""Founder-reviewed consignment comic photos; never an inventory approval API."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .access_control import require_platform_admin_request
from .auth import AuthenticatedUser, require_user
from .channel_sync_wakeup import request_shopify_sync
from .comic_listing_preparation import _shopify
from .db import user_connection


router = APIRouter(prefix="/api/v1/shopify/comic-review", tags=["comic-photo-review"],
                   dependencies=[Depends(require_platform_admin_request)])


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    decision: Literal["APPROVE", "RETAKE"]
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def reason_required_for_retake(self):
        if self.decision == "RETAKE" and not self.reason.strip():
            raise ValueError("Tell the seller why this photograph needs retaking")
        return self


class ReviewVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)


REVIEW_SCOPE_SQL = """from tcg.media_assets m
    join tcg.inventory_items i on i.id=m.inventory_id and i.owner_id=m.owner_id
    join tcg.catalogue_products p on p.id=i.catalogue_id
    join tcg.owners o on o.id=m.owner_id
    where o.owner_type='CONSIGNOR' and p.product_type='COMIC'
      and m.scope='INVENTORY_ITEM' and m.source_type='CONSIGNOR_UPLOAD'
      and m.rights_tier='FIRST_PARTY_CAPTURE'"""


@router.get("/queue")
async def comic_photo_review_queue(request: Request,
                                   user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch("""select m.id,m.inventory_id,m.owner_id,m.version,m.side,
            m.shopify_file_status,m.shopify_cdn_url,m.approval_status,m.rights_status,
            m.source_status,m.revocation_reason,m.created_at,
            i.inventory_code,i.status as inventory_status,i.condition,i.grading_company,i.grade,
            p.name,p.card_number,p.language,o.display_name as seller_name
            """ + REVIEW_SCOPE_SQL + """
              and m.approval_status='PENDING'
              and i.status in ('DRAFT','INSPECTION','APPROVED')
            order by m.created_at,m.id limit 100""")
    return jsonable_encoder({"items": [dict(row) for row in rows]})


async def _review_asset(connection, asset_id: UUID, *, lock: bool = False):
    row = await connection.fetchrow("""select m.*,i.status as inventory_status,i.grading_company,i.grade,
        i.inventory_code,p.name,o.display_name as seller_name
        """ + REVIEW_SCOPE_SQL + " and m.id=$1" + (" for update of m" if lock else ""), asset_id)
    if row is None:
        raise HTTPException(404, "Consignment comic photo not found")
    return dict(row)


@router.post("/{asset_id}/refresh-file")
async def refresh_comic_photo_file(
    asset_id: UUID, payload: ReviewVersion, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        asset = await _review_asset(connection, asset_id)
        if asset["version"] != payload.version:
            raise HTTPException(409, "Photo changed. Refresh the review queue.")
        if asset["approval_status"] != "PENDING" or asset["source_status"] != "ACTIVE":
            raise HTTPException(409, "Only active pending photo evidence can be refreshed")
    client = _shopify()
    current = asset["shopify_file_status"]
    if current == "NOT_UPLOADED":
        if not asset["public_source_url"]:
            raise HTTPException(422, "No submitted photo source to import")
        file_row = await client.create_file_from_url(source_url=asset["public_source_url"],
                                                     alt_text=asset["alt_text"])
    elif current in {"UPLOADED", "PROCESSING", "READY"}:
        if not asset["shopify_file_gid"]:
            raise HTTPException(409, "Photo import is missing its Shopify file ID")
        file_row = await client.get_file(asset["shopify_file_gid"])
    else:
        raise HTTPException(409, "Photo import failed. Request a retake.")
    file_id = str(file_row.get("id") or "")
    file_status = str(file_row.get("fileStatus") or "").upper()
    image = file_row.get("image") if isinstance(file_row.get("image"), dict) else {}
    cdn_url = str(image.get("url") or "")
    if not file_id or file_status not in {"UPLOADED", "PROCESSING", "READY", "FAILED"}:
        raise HTTPException(502, "Shopify returned an invalid photo import status")
    if file_status == "READY" and not cdn_url:
        raise HTTPException(502, "Shopify returned a ready file without a photo URL")
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        row = await connection.fetchrow("""update tcg.media_assets set
            shopify_file_gid=$3,shopify_file_status=$4,
            shopify_cdn_url=coalesce(nullif($5,''),shopify_cdn_url),
            shopify_error=case when $4='FAILED' then 'Photo import failed' else null end,
            updated_at=clock_timestamp(),version=version+1
            where id=$1 and version=$2 and approval_status='PENDING' and source_status='ACTIVE'
            returning id,version,approval_status,shopify_file_status,shopify_cdn_url""",
            asset_id, payload.version, file_id, file_status, cdn_url)
        if row is None:
            raise HTTPException(409, "Photo changed during import. Refresh the review queue.")
    return jsonable_encoder({"asset": dict(row), "message": "Photo file refreshed; staff approval is still required."})


@router.post("/{asset_id}/decision")
async def review_comic_photo(
    asset_id: UUID, payload: ReviewDecision, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        asset = await _review_asset(connection, asset_id, lock=True)
        if asset["version"] != payload.version:
            raise HTTPException(409, "Photo changed. Refresh before deciding.")
        if asset["approval_status"] != "PENDING" or asset["source_status"] != "ACTIVE":
            raise HTTPException(409, "This photo is no longer awaiting review")
        if asset["inventory_status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
            raise HTTPException(409, "Inactive inventory cannot have photos approved")
        expected_context = "GRADED_SLAB" if asset["grading_company"] and asset["grade"] else "RAW_UNSLEEVED"
        if payload.decision == "APPROVE":
            if asset["capture_context"] != expected_context:
                raise HTTPException(422, "Physical photo context does not match the graded/raw comic")
            if asset["shopify_file_status"] != "READY" or not asset["shopify_cdn_url"]:
                raise HTTPException(422, "The physical photo must be available for inspection before approval")
            if not asset["rights_basis"] or not asset["alt_text"]:
                raise HTTPException(422, "Photo rights and description must be recorded")
            row = await connection.fetchrow("""update tcg.media_assets set
                rights_status='VERIFIED',approval_status='APPROVED',
                rights_basis=$4,approved_by_user_id=$5,approved_at=clock_timestamp(),
                rights_verified_at=clock_timestamp(),source_checked_at=clock_timestamp(),
                source_status_note='Exact physical comic photograph reviewed by Drop Rate',
                updated_at=clock_timestamp(),version=version+1
                where id=$1 and owner_id=$2 and version=$3 returning id,version,approval_status,side""",
                asset_id, asset["owner_id"], payload.version,
                "Seller-owned exact-copy image; identity, rights and visible photo reviewed by Drop Rate. "
                + (payload.reason.strip() or "No additional reviewer note"), user.user_id)
        else:
            row = await connection.fetchrow("""update tcg.media_assets set
                rights_status='REJECTED',approval_status='REJECTED',source_status='REVOKED',
                revoked_at=clock_timestamp(),revoked_by_user_id=$4,revocation_reason=$5,
                updated_at=clock_timestamp(),version=version+1
                where id=$1 and owner_id=$2 and version=$3 returning id,version,approval_status,side""",
                asset_id, asset["owner_id"], payload.version, user.user_id, payload.reason.strip())
        if row is None:
            raise HTTPException(409, "Photo changed during review")
    if payload.decision == "APPROVE":
        request_shopify_sync(request)
    return jsonable_encoder({"asset": dict(row), "message":
        "Photo approved for the exact copy. Inventory and shipping still require separate approval."
        if payload.decision == "APPROVE" else "Photo rejected with a retake reason. The seller may submit a new photo."})
