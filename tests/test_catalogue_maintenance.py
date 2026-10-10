from contextlib import asynccontextmanager
import hashlib
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import catalogue_maintenance as jobs
from app import catalogue_browser as browser
from app.reference_sealed import sealed_reference,sealed_feed,category_type,expansion_system


NOW=datetime(2026,10,9,14,tzinfo=timezone.utc)


def test_daily_schedule_uses_london_time_and_recovers_without_restart_storm():
    assert jobs.daily_slot(NOW)==datetime(2026,10,9,2,tzinfo=timezone.utc)
    assert jobs.daily_slot(datetime(2026,12,1,14,tzinfo=timezone.utc)).hour==3
    assert jobs.daily_slot(datetime(2026,10,9,1,tzinfo=timezone.utc)).day==8
    assert jobs.due(None,NOW)
    assert not jobs.due({'status':'COMPLETE','started_at':NOW-timedelta(hours=1)},NOW)
    assert jobs.due({'status':'COMPLETE','started_at':NOW-timedelta(days=1)},NOW)
    assert jobs.due({'status':'INCOMPLETE','started_at':NOW-timedelta(hours=2)},NOW)
    assert not jobs.due({'status':'RUNNING','started_at':NOW-timedelta(minutes=10)},NOW)
    recent={'status':'INCOMPLETE','started_at':NOW,'report':{'importer_revision':1}}
    assert jobs.due(recent,NOW,revision=2)
    assert not jobs.due(dict(recent,report={'importer_revision':2}),NOW,revision=2)


def test_live_prefixed_categories_exclude_accessories_and_separate_fusion_world():
    game={'name':'Pokémon','id':5}
    assert category_type('Pokémon Booster Box',game)=='BOOSTER_BOX'
    assert category_type('Pokémon Booster',game)=='BOOSTER_PACK'
    assert category_type('Pokémon Box Set',game)=='COLLECTION'
    for label in ('Pokémon Deck Boxes','Pokémon Complete Set','Pokémon Singles','Pokémon Empty Boxes & Storage'):
        assert category_type(label,game) is None
    assert category_type('One Piece Bundles & Sets',{'name':'One Piece'})=='COLLECTION'
    masters='DRAGON_BALL_SUPER_MASTERS'
    assert expansion_system(masters,{'name':'Fusion World: Awakened Pulse'})=='DRAGON_BALL_SUPER_FUSION_WORLD'
    assert expansion_system(masters,{'name':'Awakened Pulse','code':'FB01'})=='DRAGON_BALL_SUPER_FUSION_WORLD'
    assert expansion_system(masters,{'name':'Galactic Battle','code':'BT01'})==masters


def test_sealed_references_do_not_assume_language_price_or_canonical_approval():
    blueprint={'id':12,'category_id':9,'expansion_id':10,'name':'Booster box','image_url':'https://cardtrader.com/uploads/blueprints/image/12/preview_box.jpg',
               'editable_properties':[{'name':'pokemon_language','default_value':'en'}]}
    row=sealed_reference(blueprint,{'id':10},'POKEMON_TCG',{'9':'BOOSTER_BOX'})
    assert row['language']=='Unknown' and row['product_type']=='BOOSTER_BOX'
    assert row['evidence']['exact_product_verified'] is False
    assert row['image_url'].endswith('/box.jpg')
    assert 'market_value_minor' not in row
    assert sealed_reference(dict(blueprint,category_id=1),{'id':10},'POKEMON_TCG',{'9':'BOOSTER_BOX'}) is None
    assert sealed_reference(dict(blueprint,expansion_id=11),{'id':10},'POKEMON_TCG',{'9':'BOOSTER_BOX'}) is None
    assert sealed_reference(dict(blueprint,image_url='https://evil.test/x.jpg'),{'id':10},'POKEMON_TCG',{'9':'BOOSTER_BOX'})['image_url'] is None


def test_unknown_sealed_language_requires_customer_choice_and_stays_unconfirmed():
    item=dict(product_type='SEALED',game='Pokemon',name='Sealed box',set_name='Set',card_number=None,provider_id='12',language='Unknown')
    payload=browser.BrowseIntake(key='s:ref',confirmed=True,seal_status='SEALED')
    with pytest.raises(HTTPException,match='Choose the physical'):browser.intake_payload(item,payload)
    result=browser.intake_payload(item,payload.model_copy(update={'language':'Japanese'}))
    assert result.new_catalogue.product_type=='SEALED' and result.new_catalogue.language=='Japanese'
    assert result.identity_confirmed is False and result.seal_status=='SEALED'
    with pytest.raises(HTTPException):browser.intake_payload(dict(item,language='English'),payload.model_copy(update={'language':'Japanese'}))


def test_inflight_card_intake_retry_keeps_its_existing_idempotency_digest():
    payload=browser.BrowseIntake(key='r:printing',condition='Near Mint',confirmed=True)
    old_body='{"key":"r:printing","condition":"Near Mint","seal_status":null,"confirmed":true}'
    assert hashlib.sha256(old_body.encode()).hexdigest() in browser.browse_note(payload)


@pytest.mark.asyncio
async def test_cardtrader_feed_preserves_game_scope_and_excludes_single_cards(monkeypatch):
    async def no_sleep(_):pass
    monkeypatch.setattr(jobs.asyncio,'sleep',no_sleep)
    class Client:
        async def list_games(self):return [{'id':1,'name':'Pokémon'},{'id':2,'name':'Other'}]
        async def list_categories(self,game_id):return [{'id':9,'game_id':1,'name':'Pokémon Booster Box'},{'id':8,'game_id':1,'name':'Pokémon Singles'}]
        async def list_expansions(self):return [{'id':10,'game_id':1,'name':'Set','released_at':'2025-01-01'},{'id':11,'game_id':2,'name':'Wrong'}]
        async def list_blueprints(self,expansion_id):
            assert expansion_id==10
            return [{'id':12,'category_id':9,'name':'Booster box'},{'id':13,'category_id':8,'name':'Card'}]
    rows=[r async for r in sealed_feed(Client())]
    assert len(rows)==1 and len(rows[0][1])==1
    assert rows[0][0]['release_date']=='2025-01-01' and rows[0][0]['language']=='Unknown'


class Connection:
    def __init__(self,candidates=()):self.candidates=candidates;self.calls=[]
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        if 'pg_try_advisory_lock' in sql:return True
        if 'max(started_at)' in sql:return None
        return uuid4()
    async def fetch(self,sql,*args):return self.candidates
    async def execute(self,sql,*args):self.calls.append((sql,args))
    def is_closed(self):return False


class Pool:
    def __init__(self,connection):self.connection=connection
    @asynccontextmanager
    async def acquire(self):yield self.connection


@pytest.mark.asyncio
async def test_automatic_sync_uses_exact_existing_pipeline_and_records_blockers(monkeypatch):
    actor=uuid4();item=dict(id=uuid4(),owner_id=uuid4(),version=7)
    conn=Connection([item]);pool=Pool(conn);published=[];receipts=[]
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(connection):return {}
    async def publish(connection,**kwargs):
        published.append(kwargs);raise HTTPException(422,'Media review required')
    async def prices(*args,**kwargs):return dict(candidate_count=0,synced_count=0,failed_count=0)
    async def receipt(*args):receipts.append(args);return uuid4()
    monkeypatch.setattr(jobs,'user_connection',user_connection);monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'publish_inventory_to_shopify',publish);monkeypatch.setattr(jobs,'reconcile_shopify_product_prices',prices)
    monkeypatch.setattr(jobs,'receipt',receipt)
    settings=SimpleNamespace(shopify_publish_enabled=True,shopify_seller_sync_enabled=True,catalogue_maintenance_actor_user_id=str(actor))
    await jobs.shopify_pass(pool,settings)
    assert published[0]['inventory_id']==item['id'] and published[0]['owner_id']==item['owner_id']
    assert published[0]['expected_version']==7 and published[0]['test_mode'] is False
    assert any(r[3]=='INCOMPLETE' and r[4].get('http_status')==422 for r in receipts)
    assert any("set_config('tcg.user_id','',false)" in sql for sql,_ in conn.calls)
    assert any('pg_advisory_unlock' in sql for sql,_ in conn.calls)
    published.clear();settings.shopify_publish_enabled=False
    await jobs.shopify_pass(pool,settings);assert not published


@pytest.mark.asyncio
async def test_daily_price_warm_stops_on_provider_failure_and_reuses_fx(monkeypatch):
    conn=Connection([{'key':'r:'+str(i).zfill(32)} for i in range(81)]);pool=Pool(conn)
    @asynccontextmanager
    async def user_connection(*args):yield conn
    receipts=[];requests=[]
    async def receipt(*args):receipts.append(args);return uuid4()
    async def refresh(*args,**kwargs):
        requests.append((args,kwargs));return [{'market_value_minor':None,'provider_refresh_failed':True} for _ in args[3]]
    monkeypatch.setattr(jobs,'user_connection',user_connection);monkeypatch.setattr(jobs,'receipt',receipt)
    monkeypatch.setattr(jobs,'refresh_reference_prices',refresh)
    async def one_piece(*args):return {'checked':1,'priced':1,'provider_failures':0}
    monkeypatch.setattr(jobs,'refresh_one_piece_prices',one_piece)
    monkeypatch.setattr(jobs,'refresh_dragon_ball_prices',one_piece)
    await jobs.warm_prices(pool,uuid4(),80)
    assert len(requests)==1 and len(requests[0][0][3])==40
    assert requests[0][1]['fx_provider'] is not None
    assert receipts[-1][3]=='INCOMPLETE' and receipts[-1][4]['provider_failures']==40
