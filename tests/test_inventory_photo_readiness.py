"""Photo exception queue: owner separation, exact slab photo and no false R2 claims."""
from __future__ import annotations

from uuid import UUID

import pytest

from app.inventory_photo_readiness import SQL, photo_action_queue


OWNER=UUID("00000000-0000-4000-8000-000000000001")
OTHER=UUID("00000000-0000-4000-8000-000000000002")


class ReadOnlyConnection:
    def __init__(self,rows=None):
        self.rows=rows or []
        self.requests=[]
    async def fetch(self,sql,*args):
        assert sql==SQL
        assert "i.owner_id=$1" in sql
        assert "m.owner_id=$1" in sql
        assert "m.scope='INVENTORY_ITEM'" in sql
        assert "m.rights_tier='FIRST_PARTY_CAPTURE'" in sql
        assert "m.capture_context='GRADED_SLAB'" in sql
        assert "m.source_type IN ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')" in sql
        assert "m.approval_status='APPROVED'" in sql
        assert "m.revoked_at IS NULL" in sql
        assert "mm.content_sha256" in sql
        assert "tcg.reference_image_mirrors" not in sql
        assert "INSERT " not in sql.upper() and "UPDATE " not in sql.upper()
        assert "DELETE " not in sql.upper()
        self.requests.append(args)
        return self.rows


@pytest.mark.asyncio
async def test_queue_stays_bound_to_single_member_owner():
    conn=ReadOnlyConnection([{
        "id":UUID("00000000-0000-4000-8000-000000000011"),
        "inventory_code":"INV-000011",
        "version":1,"status":"APPROVED","graded":True,
        "sealed":False,"has_capture":False,
        "has_approved_capture":False,"has_r2_mirror_index":False,
        "action_required":"CAPTURE_GRADED_SLAB",
        "owner_held_total":12,"owner_graded_total":1,
        "missing_first_party_total":12,"captured_not_r2_total":0
    }])
    data=await photo_action_queue(conn,OWNER,limit=5,offset=0)
    assert conn.requests==[(OWNER,5,0)]
    assert data["owner_graded_total"]==1
    assert data["missing_first_party_total"]==12
    assert data["items"][0]["action_required"]=="CAPTURE_GRADED_SLAB"
    assert "owner_id" not in data["items"][0]
    assert "object_key" not in data["items"][0]
    assert data["actual_r2_bytes_verified_by_this_endpoint"] is False
    assert data["published_to_shopify"] is False
    assert data["source_table_writes"]==0


@pytest.mark.asyncio
async def test_no_rows_does_not_claim_photos_ready():
    out=await photo_action_queue(ReadOnlyConnection(),OWNER)
    assert out["owner_held_total"]==0
    assert out["items"]==[]
    assert out["actual_r2_bytes_verified_by_this_endpoint"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,limit,offset",[
    ("00000000-0000-4000-8000-000000000001",50,0),
    (None,50,0),(OWNER,101,0),(OWNER,0,0),
    (OWNER,True,0),(OWNER,50,-1),(OWNER,50,True),
])
async def test_invalid_authorisation_or_page_fails_before_sql(owner,limit,offset):
    conn=ReadOnlyConnection()
    with pytest.raises(ValueError):
        await photo_action_queue(conn,owner,limit=limit,offset=offset)
    assert conn.requests==[]


def test_slabs_never_fall_back_to_provider_image():
    assert "ma.scope" not in SQL
    assert "CANONICAL_CARD" not in SQL
    assert "CANONICAL_PRODUCT" not in SQL
    assert "GRADED_SLAB" in SQL
    assert "CAPTURE_GRADED_SLAB" in SQL
    assert "VERIFY_R2_COPY_BYTES" in SQL
    assert "MIRROR_FIRST_PARTY_TO_R2" in SQL
    assert "source_type IN ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')" in SQL
