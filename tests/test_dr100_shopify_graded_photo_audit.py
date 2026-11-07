"""DR100: do not confuse a published Shopify link with approved slab images."""
from uuid import UUID
from unittest.mock import AsyncMock

import pytest

from app import shopify_graded_photo_audit as audit
from app import catalogue_maintenance as maintenance


ACTOR=UUID("11111111-1111-4111-8111-111111111111")
OWNER=UUID("22222222-2222-4222-8222-222222222222")
INVENTORY=UUID("33333333-3333-4333-8333-333333333333")


def row(*,front=False,back=False):
    return dict(
        id=INVENTORY,owner_id=OWNER,version=6,
        grading_company="PSA",grade="10",
        shopify_product_gid="gid://shopify/Product/123",
        shopify_variant_gid="gid://shopify/ProductVariant/456",
        front_ready=front,back_ready=back,
    )


class FakeConnection:
    def __init__(self,rows, previous=None):
        self.rows=rows
        self.previous=previous
        self.fetches=[]
    async def fetch(self,sql,limit):
        self.fetches.append((sql,limit))
        return self.rows
    async def fetchrow(self,sql,owner,dedupe):
        assert "tcg.action_required_items" in sql
        assert owner==OWNER
        assert dedupe==audit.dedupe_for(INVENTORY)
        return {"status":self.previous} if self.previous else None


@pytest.fixture
def downstream(monkeypatch):
    authorise=AsyncMock()
    upsert=AsyncMock(return_value={"status":"OPEN"})
    resolve=AsyncMock(return_value={"status":"RESOLVED"})
    monkeypatch.setattr(audit,"require_platform_admin",authorise)
    monkeypatch.setattr(audit,"upsert_action_required",upsert)
    monkeypatch.setattr(audit,"resolve_action_required",resolve)
    return authorise,upsert,resolve


@pytest.mark.asyncio
async def test_published_graded_without_exact_photos_produces_owner_action(downstream):
    authorised,upsert,resolve=downstream
    report=await audit.audit_published_graded_media(
        FakeConnection([row()]),actor_user_id=ACTOR)
    assert report["graded_published_checked"]==1
    assert report["missing"]==1 and report["new_or_reopened"]==1
    assert report["shopify_publications_changed"]==0
    assert report["ownership_changed"]==0
    authorised.assert_awaited_once()
    upsert.assert_awaited_once()
    kw=upsert.await_args.kwargs
    assert kw["owner_id"]==OWNER and kw["entity_id"]==INVENTORY
    assert kw["entity_type"]=="INVENTORY_ITEM"
    assert kw["severity"]=="HIGH"
    assert kw["code"]==audit.ACTION_CODE
    assert kw["metadata"]["missing_sides"]==["FRONT","BACK"]
    assert kw["metadata"]["no_automatic_delisting"] is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_both_slab_sides_does_not_create_or_reopen(downstream):
    _,upsert,resolve=downstream
    report=await audit.audit_published_graded_media(
        FakeConnection([row(front=True,back=True)]),actor_user_id=ACTOR)
    assert report["ready"]==1 and report["missing"]==0
    upsert.assert_not_awaited()
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_open_action_is_noop_not_version_increment(downstream):
    _,upsert,resolve=downstream
    report=await audit.audit_published_graded_media(
        FakeConnection([row(front=True)],previous="OPEN"),actor_user_id=ACTOR)
    assert report["existing_open"]==1 and report["new_or_reopened"]==0
    upsert.assert_not_awaited()
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_remediated_photo_action_closes_only_own_dedupe_key(downstream):
    _,upsert,resolve=downstream
    report=await audit.audit_published_graded_media(
        FakeConnection([row(front=True,back=True)],previous="OPEN"),actor_user_id=ACTOR)
    assert report["resolved"]==1
    kw=resolve.await_args.kwargs
    assert kw=={
        "owner_id":OWNER,"dedupe_key":audit.dedupe_for(INVENTORY),
        "actor_user_id":ACTOR,"status":"RESOLVED",
    }
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_still_missing_after_resolved_action_reopens_only_new_dr100_record(downstream):
    _,upsert,resolve=downstream
    report=await audit.audit_published_graded_media(
        FakeConnection([row()],previous="RESOLVED"),actor_user_id=ACTOR)
    assert report["new_or_reopened"]==1
    assert upsert.await_args.kwargs["dedupe_key"]==audit.dedupe_for(INVENTORY)
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_shopify_gid_fails_closed_before_creating_action(downstream):
    _,upsert,resolve=downstream
    candidate={**row(), "shopify_product_gid":"123"}
    with pytest.raises(ValueError,match="verified Shopify IDs"):
        await audit.audit_published_graded_media(
            FakeConnection([candidate]),actor_user_id=ACTOR)
    upsert.assert_not_awaited()
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_batch_size_never_partially_edits_other_founders(downstream):
    _,upsert,_=downstream
    with pytest.raises(ValueError,match="limit exceeded"):
        await audit.audit_published_graded_media(
            FakeConnection([row() for _ in range(101)]),actor_user_id=ACTOR)
    upsert.assert_not_awaited()


def test_sql_proves_exact_owned_first_party_slab_not_certificate_or_raw_reference():
    sql=audit.PUBLISHED_GRADED_AUDIT_SQL
    assert "m.owner_id=i.owner_id" in sql
    assert "m.inventory_id=i.id" in sql
    assert "m.capture_context='GRADED_SLAB'" in sql
    assert "m.rights_tier='FIRST_PARTY_CAPTURE'" in sql
    assert "m.approval_status='APPROVED'" in sql
    assert "m.rights_status='VERIFIED'" in sql
    assert "m.shopify_file_status='READY'" in sql
    assert "m.revoked_at is null" in sql
    assert sql.count("m.shopify_file_status='READY'")==2
    assert "l.test_mode=false" in sql
    assert "l.sync_state='PUBLISHED'" in sql
    assert "i.status='APPROVED' and i.sale_intent='FOR_SALE'" in sql
    assert "l.owner_id=i.owner_id" in sql


def test_existing_shopify_maintenance_catches_audit_failure_and_preserves_sales_pipeline():
    from inspect import getsource
    src=getsource(maintenance.shopify_pass)
    assert "audit_published_graded_media" in src
    assert "graded_audit_failed=True" in src
    assert "'graded_media_audit':graded_audit" in src
    assert "reconcile_shopify_product_prices(" in src
    assert "publish_inventory_to_shopify(" in src
