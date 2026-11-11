"""Optional purchase cost must not block selling or become an invented zero."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import ebay_sales, finance, owner_portal_api
from app.shopify_pipeline import _test_sync_missing
from app.shopify_pooling import _evaluate_group
from test_shopify_pooling import _pair


@pytest.mark.parametrize('cost',[None,0,800])
@pytest.mark.parametrize('product_type,condition,seal_status',[
    ('CARD','Near Mint',None),('COMIC','Mint',None),('SEALED',None,'SEALED'),('COLLECTION',None,'UNSEALED')])
def test_shopify_publication_uses_optional_cost_without_relaxing_dispatch(cost,product_type,condition,seal_status):
    item=dict(status='APPROVED',identity_confirmed=True,acquisition_cost_minor=cost,
        product_type=product_type,grading_company=None,grade=None,condition=condition,
        condition_review_status='VERIFIED_NEAR_MINT',seal_status=seal_status,language='English',
        catalogue_language='English',store_price_minor=2000,storage_location_id='location',
        registered_location_id='location',registered_location_active=True,card_number='1',variant='Printing 1')
    assert _test_sync_missing(item)==[]
    assert _test_sync_missing(dict(item,storage_location_id=None))==['registered storage location']
    assert item['acquisition_cost_minor']==cost


@pytest.mark.parametrize('cost',[None,0,800])
def test_approved_pooled_stock_does_not_need_a_purchase_cost(cost):
    first,second=_pair(acquisition_cost_minor=cost)
    result=_evaluate_group([first,second])
    assert result['ready'] is True and result['quantity']==2
    assert first['acquisition_cost_minor']==second['acquisition_cost_minor']==cost


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),state=SimpleNamespace(request_id='synthetic'))


@pytest.mark.asyncio
@pytest.mark.parametrize('cost',[None,0,800])
async def test_ebay_readiness_preserves_nullable_cost_and_photo_requirement(monkeypatch,cost):
    owner,inventory,actor=uuid4(),uuid4(),uuid4()
    row=dict(id=inventory,owner_id=owner,catalogue_id=uuid4(),inventory_code='INV-SYNTHETIC',acquisition_cost_minor=cost,
        product_type='CARD',status='APPROVED',sale_intent='FOR_SALE',identity_confirmed=True,
        language='English',store_price_minor=2000,storage_location_id=uuid4(),version=3,
        grading_company=None,grade=None,condition='Near Mint',condition_review_status='VERIFIED_NEAR_MINT')
    photos=['FRONT','BACK']
    class Connection:
        async def fetchrow(self,sql,*params):
            if 'tcg.inventory_items' in sql:
                assert params==(inventory,owner);return dict(row)
            assert 'tcg.ebay_inventory_links' in sql;return dict(state='LIVE')
        async def fetchval(self,sql,*params):
            assert 'tcg.shopify_shipping_profiles' in sql;return True
        async def fetch(self,sql,*params):
            assert 'tcg.media_assets' in sql
            if "scope='CANONICAL_CARD'" in sql:
                assert params==(row['catalogue_id'],)
                return []
            assert params==(owner,inventory,False)
            assert "rights_tier='FIRST_PARTY_CAPTURE'" in sql
            assert "capture_context='GRADED_SLAB'" in sql
            return [dict(
                side=side,
                shopify_cdn_url=f'https://cdn.shopify.com/s/files/{side.lower()}.jpg',
                owner_id=owner, inventory_id=inventory,
                scope='INVENTORY_ITEM', media_kind='IMAGE',
                source_type='FOUNDER_UPLOAD', rights_tier='FIRST_PARTY_CAPTURE',
                capture_context='RAW_UNSLEEVED', rights_status='VERIFIED',
                approval_status='APPROVED', source_status='ACTIVE',
                revoked_at=None, shopify_file_status='READY'
            ) for side in photos]
    @asynccontextmanager
    async def connection(*args,**kwargs):
        yield Connection()
    async def owner_record(conn):return dict(id=owner)
    monkeypatch.setattr(ebay_sales,'user_connection',connection)
    monkeypatch.setattr(ebay_sales,'_owner',owner_record)
    settings=SimpleNamespace(ebay_price_markup_bps=0)
    plan=await ebay_sales._load_listing_plan(request(),SimpleNamespace(user_id=actor),inventory,3,settings)
    assert plan['item']['acquisition_cost_minor']==cost and plan['already_live'] is True
    photos.pop()  # A saved front scan is now enough without the back.
    still_ready=await ebay_sales._load_listing_plan(request(),SimpleNamespace(user_id=actor),inventory,3,settings)
    assert still_ready['already_live'] is True
    photos.pop()  # No approved catalogue or first-party scan remains.
    with pytest.raises(HTTPException) as error:
        await ebay_sales._load_listing_plan(request(),SimpleNamespace(user_id=actor),inventory,3,settings)
    assert error.value.status_code==409
    assert error.value.detail['blockers']==['approved catalogue image or saved front scan required']


@pytest.mark.asyncio
@pytest.mark.parametrize('cost',[None,0,800])
async def test_manual_sale_snapshots_optional_cost_unchanged(monkeypatch,cost):
    owner,inventory,actor=uuid4(),uuid4(),uuid4();writes=[]
    class Connection:
        async def fetchrow(self,sql,*params):
            if 'select id from tcg.orders' in sql:return None
            assert "set status = 'SOLD'" in sql
            return dict(id=inventory,inventory_code='INV-SYNTHETIC',status='SOLD',version=4)
        async def fetch(self,sql,*params):
            assert 'for update' in sql and params==(owner,[inventory])
            return [dict(id=inventory,inventory_code='INV-SYNTHETIC',owner_id=owner,acquisition_cost_minor=cost,status='APPROVED',version=3)]
        async def execute(self,sql,*params):writes.append((sql,params))
    @asynccontextmanager
    async def connection(*args,**kwargs):yield Connection()
    async def owner_record(conn):return dict(id=owner)
    monkeypatch.setattr(finance,'user_connection',connection)
    monkeypatch.setattr(finance,'_owner',owner_record)
    payload=finance.ManualSaleCreate(reference='synthetic-cost-'+str(cost),items=[finance.ManualSaleItem(
        inventory_id=inventory,sale_price_minor=2500,discount_minor=500)])
    result=await finance.create_manual_sale(payload,request(),SimpleNamespace(user_id=actor))
    assert result['items'][0]['cost_basis_minor']==cost
    sale_writes=[params for sql,params in writes if 'insert into tcg.order_items' in sql]
    assert len(sale_writes)==1 and sale_writes[0][6]==cost
    revenue=[params for sql,params in writes if 'insert into tcg.financial_ledger_entries' in sql]
    assert len(revenue)==1 and revenue[0][3:5]==('SALE_REVENUE',2000)


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[None,'SOLD','WITHDRAWN'])
async def test_collection_route_filters_active_before_count_and_page_but_preserves_explicit_history(monkeypatch,status):
    owner,actor=uuid4(),uuid4();calls=[]
    class Connection:
        async def fetchval(self,sql,*params):calls.append((sql,params));return 0
        async def fetch(self,sql,*params):calls.append((sql,params));return []
    @asynccontextmanager
    async def connection(*args,**kwargs):yield Connection()
    async def unchanged(conn,items):return items
    monkeypatch.setattr(owner_portal_api,'user_connection',connection)
    for helper in ('add_reference_artwork','add_shared_inventory_media','add_shared_reference_values'):
        monkeypatch.setattr(owner_portal_api,helper,unchanged)
    result=await owner_portal_api.owner_inventory(request(),SimpleNamespace(user_id=actor),
        dict(owner_id=owner,display_name='Synthetic owner',owner_type='CONSIGNOR'),search=None,status=status,
        limit=50,offset=0,group_copies=False,category='',game='',language='',grading='',format='',
        listing_state='',prepare_selling=False,sort='updated',include_facets=False)
    assert result['total']==0 and result['items']==[] and len(calls)==2
    for sql,params in calls:
        assert 'where i.owner_id=$1' in sql and params[0]==owner
        if status:
            assert 'and i.status=$2' in sql and params[1]==status
        else:
            assert "and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')" in sql
    assert calls[-1][1][-2:]==(50,0)
