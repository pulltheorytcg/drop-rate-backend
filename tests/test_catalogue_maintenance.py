from contextlib import asynccontextmanager
import hashlib
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.shopify_client import ShopifyApiError, ShopifyMediaScopeRequired

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


def test_opt_in_one_piece_recovery_is_once_only_and_backs_off_failed_attempts():
    assert jobs.one_piece_recovery_due(None,NOW)
    assert not jobs.one_piece_recovery_due(
        {'status':'COMPLETE','started_at':NOW-timedelta(days=8)},NOW)
    for status in ('RUNNING','INCOMPLETE','FAILED'):
        assert not jobs.one_piece_recovery_due({'status':status,'started_at':NOW},NOW)
        assert jobs.one_piece_recovery_due(
            {'status':status,'started_at':NOW-timedelta(hours=2)},NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize('result,expected', [
    ({'checked':9000,'priced':3768,'official_base_priced':33,'provider_failures':0},'COMPLETE'),
    ({'checked':0,'priced':0,'provider_failures':1},'INCOMPLETE'),
])
async def test_one_time_reference_refresh_preserves_receipts_and_uses_only_cardmarket(monkeypatch,result,expected):
    receipts=[];calls=[];actor=uuid4()
    async def receipt(*args):
        receipts.append(args)
        return uuid4()
    async def refresh(*args,**kwargs):
        calls.append((args,kwargs))
        return result
    monkeypatch.setattr(jobs,'receipt',receipt)
    monkeypatch.setattr(jobs,'refresh_one_piece_prices',refresh)
    assert await jobs.run_one_piece_base_recovery(object(),actor)==expected
    assert len(calls)==1 and calls[0][0][1]==actor
    assert calls[0][1]=={'official_base_only':True}
    assert receipts[0][2]==jobs.ONE_PIECE_BASE_RECOVERY_JOB
    assert receipts[0][3]=='RUNNING'
    assert receipts[1][3]==expected
    report=receipts[1][4]
    assert report['scope']=='REFERENCE_ONLY'
    assert report['inventory_writes']==report['store_price_writes']==0
    assert report['one_piece']==result
    assert len(receipts[1])==6  # update the original receipt, not another run


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


@pytest.mark.parametrize('failure',['none','source','detail','interrupted','exception','missing_receipt'])
def test_catalogue_pagination_continues_without_treating_provider_failures_as_progress(failure):
    report={'more_due_at_start':True,'provider_failures':0,
            **{name:{'provider_failures':0} for name in ('pokemon_catalogue','one_piece','dragon_ball')}}
    if failure=='source':report['one_piece']['provider_failures']=1
    if failure=='detail':report['provider_failures']=1
    if failure=='interrupted':report['reason']='INTERRUPTED'
    if failure=='exception':report['reason']='ValueError'
    if failure=='missing_receipt':report.pop('dragon_ball')
    run={'status':'INCOMPLETE','started_at':NOW,'report':report}
    assert jobs.due(run,NOW)==(failure=='none')
    assert jobs.due(run,NOW+timedelta(hours=2))


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
@pytest.mark.parametrize('failure', [HTTPException(422,'Media review required'), ShopifyApiError('Collection assignment rejected'), ShopifyMediaScopeRequired()])
async def test_automatic_sync_uses_exact_existing_pipeline_and_records_blockers(monkeypatch, failure):
    actor=uuid4();item=dict(id=uuid4(),owner_id=uuid4(),version=7)
    conn=Connection([item]);pool=Pool(conn);published=[];receipts=[]
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(connection):return {}
    async def publish(connection,**kwargs):
        published.append(kwargs);raise failure
    async def prices(*args,**kwargs):return dict(candidate_count=0,synced_count=0,failed_count=0)
    async def receipt(*args):receipts.append(args);return uuid4()
    monkeypatch.setattr(jobs,'user_connection',user_connection);monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'publish_inventory_to_shopify',publish);monkeypatch.setattr(jobs,'reconcile_shopify_product_prices',prices)
    monkeypatch.setattr(jobs,'receipt',receipt)
    settings=SimpleNamespace(shopify_publish_enabled=True,shopify_seller_sync_enabled=True,catalogue_maintenance_actor_user_id=str(actor))
    await jobs.shopify_pass(pool,settings)
    assert published[0]['inventory_id']==item['id'] and published[0]['owner_id']==item['owner_id']
    assert published[0]['expected_version']==7 and published[0]['test_mode'] is False
    if isinstance(failure, ShopifyMediaScopeRequired):
        assert any(r[3]=='INCOMPLETE' and r[4].get('result')=='PERMISSION_REQUIRED'
                   and r[4].get('required_scope')=='write_files' for r in receipts)
    elif isinstance(failure, HTTPException):
        assert any(r[3]=='INCOMPLETE' and r[4].get('http_status')==422 for r in receipts)
    else:
        assert any(r[3]=='FAILED' and r[4].get('reason')=='ShopifyApiError' for r in receipts)
    heartbeat = next(r for r in receipts if r[4].get('heartbeat'))
    assert heartbeat[3] == 'INCOMPLETE'
    assert heartbeat[4]['publication_failures'] + heartbeat[4]['publication_incomplete'] == 1
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
    monkeypatch.setattr(jobs,'refresh_pokemon_catalogue_prices',one_piece)
    await jobs.warm_prices(pool,uuid4(),80)
    assert len(requests)==1 and len(requests[0][0][3])==40
    assert requests[0][1]['fx_provider'] is not None
    assert receipts[-1][3]=='INCOMPLETE' and receipts[-1][4]['provider_failures']==40


@pytest.mark.asyncio
async def test_sealed_only_refresh_updates_the_coverage_receipt(monkeypatch):
    now=datetime.now(timezone.utc);events=[]
    class DailyConnection(Connection):
        async def fetch(self,sql,*args):
            if 'reference_sync_runs' in sql:
                return [dict(source=s,status='COMPLETE',started_at=now,report={'importer_revision':jobs.SOURCE_REVISIONS.get(s,1)}) for s in jobs.SOURCES]
            revisions={'REFERENCE_PRICES':jobs.REFERENCE_JOB_REVISION,'SEALED_REFERENCE_PRICES':jobs.SEALED_MARKET_REVISION-1,
                       'CATALOGUE_VALUES':jobs.CATALOGUE_VALUE_REVISION,'CARDMARKET_VALUES':jobs.CARDMARKET_VALUE_REVISION,
                       'CATALOGUE_COVERAGE':1}
            return [dict(job=j,status='COMPLETE',
                         started_at=(jobs.weekly_price_slot(now)-timedelta(seconds=1)
                                     if j=='SEALED_REFERENCE_PRICES' else now),
                         report={'importer_revision':r}) for j,r in revisions.items()]
    conn=DailyConnection()
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(*args):pass
    async def sealed(*args):events.append('sealed')
    async def coverage(*args):events.append('coverage')
    monkeypatch.setattr(jobs,'user_connection',user_connection)
    monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'refresh_sealed_prices',sealed)
    monkeypatch.setattr(jobs,'record_coverage',coverage)
    async def safe_capacity(_):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419, 'off')
    monkeypatch.setattr(jobs,'check_database_capacity',safe_capacity)
    await jobs.daily_pass(Pool(conn),SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4())))
    assert events==['sealed','coverage']


@pytest.mark.asyncio
async def test_opt_in_official_base_recovery_runs_once_under_daily_lock(monkeypatch):
    now=datetime.now(timezone.utc);events=[];state={'completed':False}
    class DailyConnection(Connection):
        async def fetch(self,sql,*args):
            if 'reference_sync_runs' in sql:
                return [dict(source=s,status='COMPLETE',started_at=now,
                             report={'importer_revision':jobs.SOURCE_REVISIONS.get(s,1)})
                        for s in jobs.SOURCES]
            revisions={'REFERENCE_PRICES':jobs.REFERENCE_JOB_REVISION,
                       'SEALED_REFERENCE_PRICES':jobs.SEALED_MARKET_REVISION,
                       'CATALOGUE_VALUES':jobs.CATALOGUE_VALUE_REVISION,
                       'CARDMARKET_VALUES':jobs.CARDMARKET_VALUE_REVISION,
                       'CATALOGUE_COVERAGE':1}
            result=[dict(job=j,status='COMPLETE',started_at=now,
                         report={'importer_revision':rev}) for j,rev in revisions.items()]
            if state['completed']:
                result.append(dict(job=jobs.ONE_PIECE_BASE_RECOVERY_JOB,
                                   status='COMPLETE',started_at=now,report={'importer_revision':1}))
            return result
    conn=DailyConnection()
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(*args):pass
    async def recovery(*args):events.append('recovery');return 'COMPLETE'
    async def coverage(*args):events.append('coverage')
    async def capacity(_):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419,'off')
    monkeypatch.setattr(jobs,'user_connection',user_connection)
    monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'run_one_piece_base_recovery',recovery)
    monkeypatch.setattr(jobs,'record_coverage',coverage)
    monkeypatch.setattr(jobs,'check_database_capacity',capacity)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
                             one_piece_base_recovery_enabled=True)
    await jobs.daily_pass(Pool(conn),settings)
    assert events==['recovery','coverage']
    assert any('pg_try_advisory_lock' in sql for sql,_ in conn.calls)
    assert any('pg_advisory_unlock' in sql for sql,_ in conn.calls)
    state['completed']=True
    await jobs.daily_pass(Pool(conn),settings)
    assert events==['recovery','coverage']
    state['completed']=False
    settings.one_piece_base_recovery_enabled=False
    await jobs.daily_pass(Pool(conn),settings)
    assert events==['recovery','coverage']


@pytest.mark.asyncio
async def test_pokewallet_free_job_once_hourly_then_switches_from_trial_to_apply(monkeypatch):
    now=datetime.now(timezone.utc)
    state={'prior':None,'calls':[],'receipts':[]}
    class DailyConnection(Connection):
        async def fetch(self,sql,*args):
            if 'reference_sync_runs' in sql:
                return [dict(source=s,status='COMPLETE',started_at=now,
                             report={'importer_revision':jobs.SOURCE_REVISIONS.get(s,1)})
                        for s in jobs.SOURCES]
            revisions={'REFERENCE_PRICES':jobs.REFERENCE_JOB_REVISION,
                       'SEALED_REFERENCE_PRICES':jobs.SEALED_MARKET_REVISION,
                       'CATALOGUE_VALUES':jobs.CATALOGUE_VALUE_REVISION,
                       'CARDMARKET_VALUES':jobs.CARDMARKET_VALUE_REVISION,
                       'CATALOGUE_COVERAGE':1}
            result=[dict(job=j,status='COMPLETE',started_at=now,
                         report={'importer_revision':r}) for j,r in revisions.items()]
            if state['prior']:
                result.append(dict(job='POKEWALLET_PRICES',status='COMPLETE',
                                   started_at=now,report=state['prior']))
            return result
    conn=DailyConnection()
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(*args):pass
    async def refresh(*args,**kwargs):
        state['calls'].append(kwargs)
        return {'requests':3,'eligible_quotes':12,'writes_attempted':0,'cursor':'Japanese:-88'}
    async def receipt(*args):state['receipts'].append(args)
    async def safe_capacity(_):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419,'off')
    monkeypatch.setattr(jobs,'user_connection',user_connection)
    monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'refresh_pokewallet_one_piece',refresh)
    monkeypatch.setattr(jobs,'receipt',receipt)
    monkeypatch.setattr(jobs,'check_database_capacity',safe_capacity)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        pokewallet_api_key='pk_live_hidden',pokewallet_pricing_apply_enabled=False,
        pokewallet_pricing_request_limit=60)
    await jobs.daily_pass(Pool(conn),settings)
    assert len(state['calls'])==1 and state['calls'][0]['dry_run'] is True
    assert state['calls'][0]['request_limit']==jobs.ONE_PIECE_HOURLY_REQUEST_BUDGET
    assert any(r[2]=='POKEWALLET_PRICES' and r[3]=='COMPLETE' for r in state['receipts'])
    state['prior']={'importer_revision':jobs.POKEWALLET_JOB_REVISION*10,'cursor':'Japanese:-88'}
    await jobs.daily_pass(Pool(conn),settings)
    assert len(state['calls'])==1  # never spend free quota every five minutes
    settings.pokewallet_pricing_apply_enabled=True
    await jobs.daily_pass(Pool(conn),settings)
    assert len(state['calls'])==2
    assert state['calls'][-1]['dry_run'] is False
    assert state['calls'][-1]['previous_cursor']=='Japanese:-88'


def test_unapplied_positive_trial_replays_from_before_the_dry_run():
    at=datetime.now(timezone.utc)
    rows=[{'started_at':at,'report':{'dry_run':False,'writes_attempted':0,
               'cursor':'Japanese:-58','eligible_quotes':0}},
          {'started_at':at,'report':{'dry_run':True,'eligible_quotes':66,
               'cursor':'Japanese:-8','writes_attempted':0}},
          {'started_at':at,'report':{'dry_run':True,'eligible_quotes':1,
               'cursor':'English:24305'}}]
    replay=jobs.unapplied_trial_cursor(rows)
    assert replay['cursor']=='English:24305'
    assert replay['replayed_trial_started_at']==at.isoformat()
    assert jobs.unapplied_trial_cursor([{**rows[0],
        'report':{**rows[0]['report'],'writes_attempted':23}},*rows[1:]]) is None
    assert jobs.unapplied_trial_cursor([{**rows[0],
        'report':{**rows[0]['report'],'replayed_trial_started_at':at.isoformat()}},*rows[1:]]) is None


def test_unapplied_positive_trial_direct_apply_uses_recorded_input_cursor():
    at=datetime.now(timezone.utc)
    trial={'started_at':at,'report':{'dry_run':True,'writes_attempted':0,
        'eligible_quotes':65,'input_cursor':'BT27', 'cursor':'BT7-04'}}
    replay=jobs.unapplied_trial_cursor([trial])
    assert replay=={'cursor':'BT27','replayed_trial_started_at':at.isoformat()}
    assert jobs.unapplied_trial_cursor([{**trial,'report':{
        **trial['report'],'eligible_quotes':0}}]) is None
    assert jobs.unapplied_trial_cursor([{**trial,'report':{
        **trial['report'],'input_cursor':None}}])['cursor'] is None
    assert jobs.unapplied_trial_cursor([{**trial,'report':{
        'dry_run':True,'eligible_quotes':65,'cursor':'BT7-04'}}]) is None


@pytest.mark.asyncio
async def test_apply_mode_uses_successful_trials_input_cursor(monkeypatch):
    now=datetime.now(timezone.utc)
    state={'called':[],'receipt':[]}
    class TrialConnection(Connection):
        async def fetch(self,sql,*args):
            if 'reference_sync_runs' in sql:
                return [dict(source=s,status='COMPLETE',started_at=now,
                    report={'importer_revision':jobs.SOURCE_REVISIONS.get(s,1)}) for s in jobs.SOURCES]
            if 'order by started_at desc limit 8' in sql:
                return [{'started_at':now,'report':{'dry_run':False,'writes_attempted':0,
                            'cursor':'Japanese:-58','eligible_quotes':0}},
                        {'started_at':now,'report':{'dry_run':True,'eligible_quotes':66,
                            'cursor':'Japanese:-8'}},
                        {'started_at':now,'report':{'dry_run':True,'eligible_quotes':1,
                            'cursor':'English:24305'}}]
            revisions={'REFERENCE_PRICES':jobs.REFERENCE_JOB_REVISION,
                       'SEALED_REFERENCE_PRICES':jobs.SEALED_MARKET_REVISION,
                       'CATALOGUE_VALUES':jobs.CATALOGUE_VALUE_REVISION,
                       'CARDMARKET_VALUES':jobs.CARDMARKET_VALUE_REVISION}
            return [dict(job=j,status='COMPLETE',started_at=now,
                         report={'importer_revision':r}) for j,r in revisions.items()]+[
                         dict(job='CATALOGUE_COVERAGE',status='COMPLETE',started_at=now,report={}),
                         dict(job='POKEWALLET_PRICES',status='COMPLETE',started_at=now,
                              report={'dry_run':False,'writes_attempted':0,'cursor':'Japanese:-58',
                                      'importer_revision':41})]
    conn=TrialConnection()
    @asynccontextmanager
    async def user_connection(*args):yield conn
    async def authorized(*args):pass
    async def refresh(*args,**kwargs):
        state['called'].append(kwargs)
        return {'writes_attempted':23,'eligible_quotes':23,'cursor':'English:3189'}
    async def receipt(*args):state['receipt'].append(args)
    async def capacity(_):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419,'off')
    monkeypatch.setattr(jobs,'user_connection',user_connection)
    monkeypatch.setattr(jobs,'require_platform_admin',authorized)
    monkeypatch.setattr(jobs,'refresh_pokewallet_one_piece',refresh)
    monkeypatch.setattr(jobs,'receipt',receipt)
    monkeypatch.setattr(jobs,'check_database_capacity',capacity)
    monkeypatch.setattr(jobs,'record_coverage',authorized)
    await jobs.daily_pass(Pool(conn),SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        pokewallet_api_key='pk_live_secret_fixture',pokewallet_pricing_apply_enabled=True,
        pokewallet_pricing_request_limit=15))
    assert len(state['called'])==1
    assert state['called'][0]['previous_cursor']=='English:24305'
    assert state['called'][0]['request_limit']==jobs.ONE_PIECE_HOURLY_REQUEST_BUDGET
    assert state['receipt'][-1][-1]['replayed_trial_started_at']==now.isoformat()
