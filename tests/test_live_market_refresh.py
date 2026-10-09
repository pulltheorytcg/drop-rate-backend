from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import live_market_refresh as market

NOW = datetime(2026,10,9,tzinfo=timezone.utc)


def target(**overrides):
    value = dict(id=uuid4(),owner_id=uuid4(),catalogue_id=UUID('00000000-0000-4000-8000-000000000001'),version=2,
        inventory_code='INV-TEST',status='APPROVED',identity_confirmed=True,product_type='CARD',game='Pokemon',
        name='Seel',set_name='Phantasmal Flames',card_number='021/094',variant='Normal',rarity='Common',
        condition='Near Mint',language='English',grading_company=None,grade=None,seal_status=None,store_price_minor=100,
        profile_identity_status=None,sealed_identity_status=None,sealed_product_type=None,set_code=None)
    return dict(value,**overrides)


def sold(n=1,**overrides):
    return dict(dict(item_id=str(n),title='Pokemon Seel 021/094 Phantasmal Flames NM',sale_price=3+n,
        shipping_price=1,currency='GBP',date_sold=(NOW-timedelta(days=n)).isoformat(),condition_raw='Near Mint'),**overrides)


def payload(rows=None):
    return dict(site='EBAY_GB',currency='GBP',results=rows or [sold(n) for n in range(1,6)])


@pytest.mark.parametrize('title',[
    'Seel 021/094 Phantasmal Flames NM x10',
    'Seel 021/094 Phantasmal Flames NM choose your card',
    'Seel 021/094 Different Set NM',
    'Seel 021/094 Phantasmal Flames Japanese NM',
    'Seel 021/094 Phantasmal Flames Reverse Holo NM',
    'Seel 021/094 Phantasmal Flames NM Stamped',
    'Seel 021 then 094 Phantasmal Flames NM',
    'Seel 021/094 Phantasmal Flames Proxy NM',
])
def test_wrong_products_never_become_comparables(title):
    assert not market.exact_card_match(sold(title=title),target())


def test_equivalent_number_keeps_original_provider_title():
    title='Seel 21/94 Phantasmal Flames NM'
    comps=market.select_comps(payload([sold(n,title=title) for n in range(1,6)]),target(),NOW)
    assert len(comps)==5
    assert comps[0]['title']==title


def test_grade_must_follow_its_grading_company():
    t=target(grading_company='PSA',grade='9',condition=None)
    assert market.exact_card_match(sold(title='Seel 021/094 Phantasmal Flames PSA 9'),t)
    assert not market.exact_card_match(sold(title='Seel 021/094 Phantasmal Flames PSA 10 9 cards'),t)
    assert not market.exact_card_match(sold(title='Seel 021/094 Phantasmal Flames PSA 9.5'),t)


def test_one_piece_base_parallel_and_promo_are_distinct():
    t=target(game='One Piece',name='Sabo',card_number='OP07-118',set_name='500 Years in the Future',variant='Foil')
    base='Sabo OP07-118 English NM'
    assert market.exact_card_match(sold(title=base),t)
    assert not market.exact_card_match(sold(title=base+' Parallel'),t)
    assert not market.exact_card_match(sold(title=base),dict(t,name='Sabo (Parallel)'))
    assert market.exact_card_match(sold(title=base+' Parallel'),dict(t,name='Sabo (Parallel)'))
    assert not market.exact_card_match(sold(title=base+' Promo'),dict(t,name='Sabo (Treasure Campaign)',set_name='Promotion Cards'))


def test_wrong_market_future_and_old_records_are_not_prices():
    with pytest.raises(ValueError):
        market.select_comps(dict(payload(),site='EBAY_US'),target(),NOW)
    rows=[sold(n) for n in range(1,6)]+[sold(9,date_sold=(NOW+timedelta(days=1)).isoformat()),sold(90,currency='$')]
    assert len(market.select_comps(payload(rows),target(),NOW))==5
    assert not market.select_comps(payload([sold(n,date_sold=(NOW-timedelta(days=91)).isoformat()) for n in range(5)]),target(),NOW)


def test_five_exact_sales_use_existing_engine_not_arithmetic_average():
    rows=[sold(n,sale_price=p) for n,p in enumerate([4,5,6,7,100],1)]
    comps=market.select_comps(payload(rows),target(),NOW)
    result=market.value_comps(comps,target(),now=NOW)
    assert result.algorithm_version=='drop-rate-market-v4'
    assert result.market_value_minor in {500,600}
    assert result.source_count==1 and result.sold_observation_count>=4
    with pytest.raises(ValueError):
        market.value_comps(comps[:4],target(),now=NOW)


def test_identity_key_shares_copies_but_not_physical_or_print_differences():
    t=target()
    assert market.identity_key(t)==market.identity_key(dict(t,id=uuid4(),owner_id=uuid4(),version=9))
    for field,value in [('language','Japanese'),('variant','Reverse Holofoil'),('grade','10'),('condition','Damaged'),('name','Seel (Stamped)')]:
        assert market.identity_key(t)!=market.identity_key(dict(t,**{field:value}))


def test_unverified_and_unsupported_products_remain_pending():
    assert market.eligibility(target(identity_confirmed=False))=='IDENTITY_UNCONFIRMED'
    assert market.eligibility(target(product_type='COLLECTION'))=='EXACT_SEALED_PRODUCT_MATCH_REQUIRED'
    assert market.eligibility(target()) is None


@pytest.mark.asyncio
async def test_save_value_preserves_selling_price_and_records_source(monkeypatch):
    calls=[]
    class DB:
        async def fetchrow(self,*args): return None
        async def fetchval(self,sql,*args):
            calls.append((sql,args))
            return uuid4()
    t=target(store_price_minor=9000)
    comps=market.select_comps(payload(),t,NOW)
    await market.save_value(DB(),t,comps,'Seel 021/094',NOW)
    assert 'insert into tcg.pricing_snapshots' in calls[0][0]
    assert 'LIVE_EBAY_MARKET_V1' in calls[0][1][-2]
    assert 'store_price_minor' not in calls[1][0]
    assert 'owner_id=$5 and version=$6' in calls[1][0]


@pytest.mark.asyncio
@pytest.mark.parametrize('changed',[False,True])
async def test_group_revalidates_identity_after_network_and_never_prices_changed_copy(monkeypatch,changed):
    t=target()
    saved=[]; records=[]; inside=False
    class DB:
        async def fetch(self,*args): return [dict(t,version=3 if changed else 2)]
    @asynccontextmanager
    async def conn(*args):
        nonlocal inside
        inside=True
        try: yield DB()
        finally: inside=False
    class Client:
        async def sold(self,**kwargs):
            assert not inside
            return payload([sold(n,date_sold=(datetime.now(timezone.utc)-timedelta(days=n)).isoformat()) for n in range(1,6)])
    async def admin(*args): return {}
    async def persist(*args,**kwargs): return True
    async def save(*args): saved.append(args[1])
    async def record(*args,**kwargs): records.append(kwargs)
    monkeypatch.setattr(market,'user_connection',conn)
    monkeypatch.setattr(market,'require_platform_admin',admin)
    monkeypatch.setattr(market,'_persist_comp',persist)
    monkeypatch.setattr(market,'save_value',save)
    monkeypatch.setattr(market,'_record_run',record)
    result=await market.refresh_group(None,uuid4(),uuid4(),[t],Client())
    assert result['updated']==(0 if changed else 1)
    assert len(saved)==(0 if changed else 1)
    assert records[0]['metadata']['skipped_changed']==int(changed)
