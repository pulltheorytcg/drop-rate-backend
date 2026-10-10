from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.seller_inventory_policy import sealed_seller_candidate, seller_held_consignment
from app.shopify_pipeline import _test_sync_missing, _select_order_units, ShopifyProcessingError
from app.media_resolver import physical_photo_policy, resolve_storefront_media
from app.finance import _settlement_amounts


def stock():
    owner,catalogue,actor=map(str,(uuid4(),uuid4(),uuid4()))
    item=dict(id=str(uuid4()),owner_id=owner,catalogue_id=catalogue,owner_type='CONSIGNOR',
        product_type='SEALED',seal_status='SEALED',language='Japanese',catalogue_language='Japanese',
        catalogue_identity_status='VERIFIED',name='OP17 pack',set_name='OP17',variant='',identity_confirmed=True,
        condition=None,grading_company=None,grade=None,certificate_number=None,status='APPROVED',
        sale_intent='FOR_SALE',acquisition_cost_minor=None,storage_location_id=None,store_price_minor=1000)
    item['source_record']={'seller_held_approval':dict(owner_id=owner,catalogue_id=catalogue,
        actor_user_id=actor,language='Japanese',name=item['name'],set_name=item['set_name'],variant='')}
    return item


def test_exact_seller_held_stock_needs_no_invented_cost_or_warehouse():
    item=stock()
    assert sealed_seller_candidate(item) and seller_held_consignment(item)
    assert _test_sync_missing(item)==[]
    assert not physical_photo_policy(item)['physicalPhotosRequired']
    assert not resolve_storefront_media(item,[])['complete'],'Catalogue image must still be available'


@pytest.mark.parametrize('field,value',[
    ('owner_type','FOUNDER'),('product_type','CARD'),('seal_status','UNSEALED'),
    ('identity_confirmed',False),('name','Another pack'),('variant','box'),
    ('language','English'),('owner_id','another-owner'),('catalogue_id','another-product')])
def test_seller_held_approval_is_bound_to_owner_and_exact_identity(field,value):
    item=stock();item[field]=value
    assert not seller_held_consignment(item)


@pytest.mark.parametrize('field,value',[
    ('catalogue_identity_status','PENDING'),('language','English'),('seal_status','UNSEALED'),
    ('condition','Near Mint'),('grading_company','PSA'),('owner_type','FOUNDER')])
def test_uncertain_damaged_or_graded_stock_cannot_self_approve(field,value):
    item=stock();item[field]=value;assert not sealed_seller_candidate(item)


def test_unknown_cost_does_not_reduce_seller_proceeds_or_invent_profit():
    args=dict(item_revenue_minor=2000,shipping_revenue_minor=0,item_refunds_minor=0,shipping_refunds_minor=0,
              platform_fees_minor=0,payment_fees_minor=100,shipping_cost_minor=0,
              fulfilment_material_cost_minor=0,commission_minor=200,adjustments_minor=0)
    unknown=_settlement_amounts(**args,effective_cogs_minor=None)
    known=_settlement_amounts(**args,effective_cogs_minor=800)
    assert unknown['net_owner_proceeds_minor']==known['net_owner_proceeds_minor']==1700
    assert unknown['owner_profit_minor'] is None and known['owner_profit_minor']==900


@pytest.mark.asyncio
async def test_shopify_allocates_both_unknown_cost_consignment_copies():
    a=stock();b=deepcopy(a);b['id']=str(uuid4())
    for row in (a,b):row.update(inventory_id=row['id'],inventory_status='APPROVED',synced_price_minor=1000,
        sku='EXACT-OP17',created_by_user_id=str(uuid4()))
    connection=SimpleNamespace(fetch=AsyncMock(
        side_effect=lambda sql,*params: [] if "tcg.shopify_variant_pool_aliases" in sql else [a,b]
    ))
    specs=[dict(line={'sku':'EXACT-OP17'},variant_gid='gid://shopify/ProductVariant/1',
                line_reference='1',quantity=2,unit_price_minor=1000,discount_minor=0)]
    units=await _select_order_units(connection,order_reference='order',line_specs=specs)
    assert [x['link']['inventory_id'] for x in units]==[a['id'],b['id']]
    assert all(x['link']['acquisition_cost_minor'] is None for x in units)
    b['source_record']={}
    with pytest.raises(ShopifyProcessingError):
        await _select_order_units(connection,order_reference='order',line_specs=specs)
