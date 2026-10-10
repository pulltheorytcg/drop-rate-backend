"""Real catalogue query, publication selection and migration/RLS integration.

Refuses remote/nonempty databases. All records are disposable fixtures.
"""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID,uuid4

import asyncpg

from app.catalogue_browser import GAMES_SQL,SETS_SQL,product_query
from app.catalogue_maintenance import SHOPIFY_CANDIDATES
from app.db import _init_connection
from app.reference_sealed import save_sealed_set


async def main():
    dsn=os.environ['CATALOGUE_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/catalogue_test'
    db=await asyncpg.connect(dsn);await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute('''create schema tcg;create role tcg_api nologin nobypassrls;create role anon;create role authenticated;
          create role service_role;create role tcg_auditor;
          create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean language sql stable as $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
          create table tcg.collectible_systems(code text primary key);
          insert into tcg.collectible_systems values('POKEMON_TCG');
          create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date,
            declared_card_count int,source_url text,refreshed_at timestamptz,primary key(provider,system_code,language,set_id));
          create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,
            card_number text,number_key text,finish text,rarity text,image_url text,source_url text,evidence jsonb,refreshed_at timestamptz,
            primary key(provider,system_code,language,provider_id));
          create table tcg.provider_catalogue_mappings(source_provider text,system_code text,provider_language text,provider_id text,
            catalogue_id uuid,provider_entity_type text,provider_variant_key text,match_status text);
          create table tcg.catalogue_products(id uuid,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
          create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text,set_code text,release_date date,collectible_type text);
          create table tcg.inventory_items(id uuid,owner_id uuid,catalogue_id uuid,status text,sale_intent text,version int,market_value_minor bigint,
            inventory_code text,store_price_minor bigint,updated_at timestamptz default now());
          create table tcg.owners(id uuid,active boolean);
          create table tcg.shopify_inventory_links(id uuid,inventory_id uuid,test_mode boolean,sync_state text,owner_id uuid,
            version int,listing_key text,shopify_product_gid text,shopify_variant_gid text,synced_price_minor bigint,
            last_synced_at timestamptz,reserved_order_reference text,reserved_line_reference text);
          create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
          create table tcg.media_assets(catalogue_id uuid,shopify_cdn_url text,public_source_url text,scope text,side text,media_kind text,
            approval_status text,rights_status text,rights_tier text,source_status text,revoked_at timestamptz,approved_at timestamptz,created_at timestamptz,id uuid);
          create function tcg.catalogue_reference_value_v2(uuid,text) returns table(market_value_minor bigint,basis_condition text,pricing_updated_at timestamptz,valuation_source text)
            language sql stable as $$select null::bigint,null::text,null::timestamptz,null::text where false$$;
          grant usage on schema tcg to tcg_api;grant select,insert,update on all tables in schema tcg to tcg_api;
        ''')
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261008182234_reference_market_prices.sql').read_text())
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261009144903_catalogue_daily_maintenance.sql').read_text())
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261009183154_catalogue_market_evidence.sql').read_text())
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261010120815_database_wide_reference_guides.sql').read_text())
        await db.execute((Path(__file__).parents[1]/'database/migrations/20260930124000_shopify_price_reconciliation.sql').read_text())
        actor=UUID('00000000-0000-0000-0000-000000000001');owner=uuid4()
        await db.execute("set role tcg_api")
        await db.execute("select set_config('tcg.user_id',$1,false)",str(actor))
        record=dict(provider='CardTrader',system_code='POKEMON_TCG',language='Unknown',set_id='10',name='Set',source_url='https://api.cardtrader.com/fixture')
        product=dict(record,provider_id='12',name='Booster box',product_type='BOOSTER_BOX',image_url='https://cardtrader.com/uploads/blueprints/image/12/box.jpg',evidence={'retrieval_only':True})
        await save_sealed_set(db,record,[product]);await save_sealed_set(db,record,[product])
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==1
        assert await db.fetchval('select count(*) from tcg.catalogue_products')==0
        sql,args=product_query(owner_id=owner,product_type='SEALED')
        rows=await db.fetch(sql,*args)
        assert len(rows)==1 and rows[0]['key'].startswith('s:') and rows[0]['source_kind']=='SEALED_REFERENCE'
        assert rows[0]['owned_quantity']==0 and rows[0]['market_value_minor'] is None
        sql,args=product_query(owner_id=owner,product_type='CARD');assert not await db.fetch(sql,*args)
        sql,args=product_query(owner_id=owner,product_type='SEALED',language='English');assert not await db.fetch(sql,*args)
        sets=await db.fetch(SETS_SQL,owner,['POKEMON_TCG'],'Unknown','',41,0)
        assert len(sets)==1 and sets[0]['image_url']==product['image_url'] and sets[0]['indexed_count']==1
        assert (await db.fetch(GAMES_SQL,owner))[0]['products']==1
        from app.sealed_market import WRITE_SQL
        from app.catalogue_coverage import COVERAGE_SQL
        from datetime import datetime,timedelta,timezone
        now=datetime.now(timezone.utc)
        quote={'source':'CARDMARKET_BULK','price_gbp_minor':1000,'observed_at':now.isoformat()}
        args=('CardTrader','POKEMON_TCG','Unknown','12',[quote],1000,1000,now,now,now+timedelta(days=1))
        sealed_args=args
        await db.execute(WRITE_SQL,*args);await db.execute(WRITE_SQL,*args)
        assert await db.fetchval('select count(*) from tcg.reference_market_history')==1,'Identical retry duplicated history'
        sql,params=product_query(owner_id=owner,product_type='SEALED')
        priced=(await db.fetch(sql,*params))[0]
        assert priced['market_value_minor']==1000 and priced['market_value_source']=='CARDMARKET_BULK'
        assert 'mixed-language' in priced['basis_condition']
        assert (await db.fetch(COVERAGE_SQL))[0]['status']=='MIXED_LANGUAGE_GUIDE'
        older=list(args);older[5]=older[6]=500;older[8]=now-timedelta(days=1)
        await db.execute(WRITE_SQL,*older)
        assert await db.fetchval('select market_value_minor from tcg.reference_sealed_market_prices')==1000
        assert await db.fetchval('select count(*) from tcg.reference_market_history')==1
        try:
            await db.execute('delete from tcg.reference_market_history')
            raise AssertionError('API deleted immutable public price history')
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("insert into tcg.reference_cards(provider,system_code,language,provider_id) values('TCGdex','POKEMON_TCG','Japanese','fixture')")
        from app.reference_market import WRITE_SQL as CARD_PRICE_SQL
        support=[{'source':'TCGDEX_TCGPLAYER','original_minor':42,'original_currency':'USD','observed_at':now.isoformat()}]
        await db.execute(CARD_PRICE_SQL,'TCGdex','POKEMON_TCG','Japanese','fixture',support,None,None,now,now,now+timedelta(days=1))
        assert await db.fetchval('select market_value_minor from tcg.reference_market_prices') is None
        assert await db.fetchval('select count(*) from tcg.reference_market_history')==2
        # Replay the phone search against real Postgres. A set name containing
        # EB04 must not make OP14-007 appear for the exact query EB04 007.
        await db.execute("insert into tcg.collectible_systems values('ONE_PIECE_CARD_GAME')")
        await db.execute('''insert into tcg.reference_sets(provider,system_code,language,set_id,name,release_date)
          values('Bandai Official','ONE_PIECE_CARD_GAME','English','569117','The World’s Strongest Warriors [OP-17]','2020-01-01'),
          ('Bandai Official','ONE_PIECE_CARD_GAME','English','569114','The Azure Sea [OP14-EB04]','2020-01-01'),
          ('Bandai Official','ONE_PIECE_CARD_GAME','Japanese','550204','Egghead Crisis [EB04]','2020-01-01');
          insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number,rarity)
          values('Bandai Official','ONE_PIECE_CARD_GAME','English','EB04-007_p2','569117','Roronoa Zoro','EB04-007','SP CARD'),
          ('Bandai Official','ONE_PIECE_CARD_GAME','English','OP14-007','569114','Jewelry Bonney','OP14-007','C'),
          ('Bandai Official','ONE_PIECE_CARD_GAME','Japanese','EB04-007','550204','ロロノア・ゾロ','EB04-007','SR');''')
        from app.one_piece_market import WRITE_SQL as ONE_PIECE_PRICE_SQL
        identity={'name':'Roronoa Zoro','set_id':'569117','card_number':'EB04-007','set_name':'The World’s Strongest Warriors [OP-17]'}
        quote={'source':'CARDMARKET_BULK_SINGLES','price_gbp_minor':28105,'observed_at':now.isoformat(),'reference_identity':identity}
        one_piece_args=('Bandai Official','ONE_PIECE_CARD_GAME','English','EB04-007_p2',[quote],28105,28105,now,now,now+timedelta(days=1),*identity.values())
        await db.execute(ONE_PIECE_PRICE_SQL,*one_piece_args)
        await db.execute(ONE_PIECE_PRICE_SQL,*one_piece_args)
        assert await db.fetchval('select count(*) from tcg.reference_market_history')==3,'Guide retry duplicated history'
        assert await db.fetchval('select count(*) from tcg.inventory_items')==0,'Reference quote created physical stock'
        for query in ('EB04-007','Eb04 007','eb04007','EB-04-007','EB04\u2009007','Zoro SP'):
            for sort in ('newest','name','number','value_desc','value_asc'):
                sql,args=product_query(owner_id=owner,q=query,system_code='ONE_PIECE_CARD_GAME',language='English',sort=sort)
                found=await db.fetch(sql,*args)
                assert [row['provider_id'] for row in found]==['EB04-007_p2'],(query,sort,found)
                assert found[0]['market_value_minor']==28105 and found[0]['market_value_source']=='CARDMARKET_BULK_SINGLES'
                assert found[0]['owned_quantity']==0 and 'mixed-language' in found[0]['basis_condition']
        sql,args=product_query(owner_id=owner,q='EB04 007')
        assert {r['language'] for r in await db.fetch(sql,*args)}=={'English','Japanese'}
        await db.execute("update tcg.reference_cards set name='Changed identity' where provider_id='EB04-007_p2'")
        sql,args=product_query(owner_id=owner,q='EB04 007',language='English')
        assert (await db.fetch(sql,*args))[0]['market_value_minor'] is None,'Stale identity exposed the old guide'
        changed=list(one_piece_args);changed[5]=changed[6]=99999;changed[8]=now+timedelta(seconds=1)
        await db.execute(ONE_PIECE_PRICE_SQL,*changed)
        assert await db.fetchval("select market_value_minor from tcg.reference_market_prices where provider_id='EB04-007_p2'")==28105,'Identity race replaced cached evidence'
        await db.execute("update tcg.reference_cards set name='Roronoa Zoro' where provider_id='EB04-007_p2'")
        await db.execute("insert into tcg.owners values($1,true)",owner)
        ids=[uuid4() for _ in range(6)]
        for i,(status,intent) in enumerate([('APPROVED','FOR_SALE'),('DRAFT','FOR_SALE'),('APPROVED','PERSONAL_COLLECTION'),('SOLD','FOR_SALE'),('APPROVED','FOR_SALE'),('APPROVED','FOR_SALE')]):
            await db.execute('insert into tcg.inventory_items(id,owner_id,status,sale_intent,version) values($1,$2,$3,$4,1)',ids[i],owner,status,intent)
        await db.execute("insert into tcg.shopify_inventory_links(id,inventory_id,test_mode,sync_state) values($1,$2,false,'PUBLISHED'),($3,$4,true,'DRAFT')",uuid4(),ids[4],uuid4(),ids[5])
        assert [r['id'] for r in await db.fetch(SHOPIFY_CANDIDATES)]==[ids[0]]
        await db.execute("insert into tcg.catalogue_job_runs(job,actor_user_id,status,report) values('SHOPIFY_SYNC',$1,'INCOMPLETE',$2::jsonb)",actor,{'inventory_id':str(ids[0]),'version':1})
        assert not await db.fetch(SHOPIFY_CANDIDATES),'Blocked version did not back off'
        await db.execute('update tcg.inventory_items set version=2 where id=$1',ids[0])
        assert len(await db.fetch(SHOPIFY_CANDIDATES))==1,'Corrected inventory was not retried'
        await db.execute("update tcg.inventory_items set store_price_minor=1500,inventory_code='fixture' where id=$1",ids[4])
        link=await db.fetchval("update tcg.shopify_inventory_links set owner_id=$2,version=1,listing_key='single:fixture',synced_price_minor=1000 where inventory_id=$1 returning id",ids[4],owner)
        candidates=await db.fetchval('select tcg.shopify_price_sync_candidates(25)')
        assert len(candidates)==1 and candidates[0]['inventory_id']==str(ids[4])
        args=(link,owner,1,ids[4],2,1500,'fixture')
        assert (await db.fetchval('select tcg.finalize_shopify_price_sync($1,$2,$3,$4,$5,$6,$7)',*args))['status']=='RETRY_REQUIRED'
        assert await db.fetchval('select count(*) from tcg.audit_events')==0
        args=(link,owner,1,ids[4],1,1500,'fixture')
        assert (await db.fetchval('select tcg.finalize_shopify_price_sync($1,$2,$3,$4,$5,$6,$7)',*args))['status']=='SYNCED'
        assert not await db.fetchval('select tcg.shopify_price_sync_candidates(25)')
        assert await db.fetchval("select count(*) from tcg.audit_events where action='SHOPIFY_PRICE_SYNCED'")==1
        assert await db.fetchval('select store_price_minor from tcg.inventory_items where id=$1',ids[4])==1500
        await db.execute("select set_config('tcg.user_id',$1,false)",str(owner))
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==1
        assert await db.fetchval('select count(*) from tcg.reference_market_history')==3
        try:
            await db.execute(WRITE_SQL,*sealed_args)
            raise AssertionError('Non-admin replaced sealed price evidence')
        except asyncpg.InsufficientPrivilegeError:pass
        assert await db.fetchval('select count(*) from tcg.catalogue_job_runs')==0
        try:
            await db.execute("insert into tcg.catalogue_job_runs(job,actor_user_id,status) values('SHOPIFY_SYNC',$1,'RUNNING')",owner)
            raise AssertionError('Non-admin created an operational receipt')
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("select set_config('tcg.user_id','',false)")
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==0
        # Both Dragon Ball systems use their own explicit cross-provider IDs,
        # with the same cached catalogue reader and no inventory dependency.
        await db.execute("select set_config('tcg.user_id',$1,false)",str(actor))
        for system in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD'):
            await db.execute('insert into tcg.collectible_systems values($1)',system)
            db_record=dict(record,system_code=system)
            db_product=dict(product,system_code=system,evidence={'cardmarket_product_id':'12'})
            await save_sealed_set(db,db_record,[db_product])
            value=('CardTrader',system,'Unknown','12',[{'source':'CARDMARKET_BULK','price_gbp_minor':8000,
                   'observed_at':now.isoformat(),'valuation_role':'MIXED_LANGUAGE_REFERENCE'}],8000,8000,now,now,now+timedelta(days=1))
            await db.execute(WRITE_SQL,*value)
            sql,params=product_query(owner_id=owner,product_type='SEALED',system_code=system)
            found=await db.fetch(sql,*params)
            assert len(found)==1 and found[0]['market_value_minor']==8000 and found[0]['owned_quantity']==0
            coverage=[r for r in await db.fetch(COVERAGE_SQL) if r['system_code']==system]
            assert len(coverage)==1 and coverage[0]['status']=='MIXED_LANGUAGE_GUIDE'
        assert await db.fetchval('select count(*) from tcg.inventory_items')==6
        # The shared guide remains visible with no owned or canonical product.
        # Actual SQL also verifies source priority, freshness, identity and RLS.
        await db.execute('''insert into tcg.reference_sets(provider,system_code,language,set_id,name)
          values('TCGdex','POKEMON_TCG','English','sv01','Scarlet & Violet');
          insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number,source_url)
          values('TCGdex','POKEMON_TCG','English','sv01-001','sv01','Pineco','001/198','https://api.tcgdex.net/v2/en/cards/sv01-001')''')
        from app.pokemon_catalogue_market import WRITE_SQL as GUIDE_SQL
        identity=dict(name='Pineco',set_id='sv01',card_number='001/198',set_name='Scarlet & Violet')
        quote=dict(source='CARDMARKET_CATALOGUE',price_gbp_minor=8,observed_at=now.isoformat(),reference_identity=identity)
        guide_args=('TCGdex','POKEMON_TCG','English','sv01-001',[quote],8,38,now,now,now+timedelta(days=1),*identity.values())
        await db.execute(GUIDE_SQL,*guide_args);await db.execute(GUIDE_SQL,*guide_args)
        assert await db.fetchval("select count(*) from tcg.reference_market_history where provider_id='sv01-001'")==1
        for owner_filter in ('all','not_owned'):
            for sort in ('newest','value_asc','value_desc'):
                sql,args=product_query(owner_id=owner,q='Pineco',owned=owner_filter,sort=sort)
                found=await db.fetch(sql,*args)
                assert len(found)==1 and found[0]['owned_quantity']==0 and found[0]['catalogue_id'] is None
                assert found[0]['market_value_minor']==8 and found[0]['market_value_high_minor']==38
                assert found[0]['market_value_source']=='CARDMARKET_CATALOGUE' and not found[0]['market_refresh_needed']
        sql,args=product_query(owner_id=owner,q='Pineco')
        await db.execute(CARD_PRICE_SQL,'TCGdex','POKEMON_TCG','English','sv01-001',support,None,None,now,now,now+timedelta(days=1))
        assert (await db.fetch(sql,*args))[0]['market_value_minor']==8,'US context erased a catalogue guide'
        await db.execute("update tcg.reference_cards set name='Changed' where provider_id='sv01-001'")
        changed_sql,changed_args=product_query(owner_id=owner,q='Changed')
        assert (await db.fetch(changed_sql,*changed_args))[0]['market_value_minor'] is None
        later=list(guide_args);later[8]=now+timedelta(seconds=1);later[5]=99;later[6]=99
        await db.execute(GUIDE_SQL,*later)
        assert await db.fetchval('select market_value_minor from tcg.reference_catalogue_prices')==8
        await db.execute("update tcg.reference_cards set name='Pineco' where provider_id='sv01-001'")
        fresh=[dict(source='TCGDEX_CARDMARKET',price_gbp_minor=10,observed_at=now.isoformat())]
        await db.execute(CARD_PRICE_SQL,'TCGdex','POKEMON_TCG','English','sv01-001',fresh,10,10,now,now,now+timedelta(days=1))
        assert (await db.fetch(sql,*args))[0]['market_value_minor']==10,'A broad guide replaced an exact variant'
        await db.execute("update tcg.reference_market_prices set pricing_updated_at=now()-interval '8 days' where provider_id='sv01-001'")
        assert (await db.fetch(sql,*args))[0]['market_value_minor']==8
        total_before=sum(r['products'] for r in await db.fetch(COVERAGE_SQL))
        await db.execute("update tcg.reference_catalogue_prices set pricing_updated_at=now()-interval '8 days'")
        assert (await db.fetch(sql,*args))[0]['market_value_minor'] is None
        assert sum(r['products'] for r in await db.fetch(COVERAGE_SQL))==total_before,'Stale references disappeared from full coverage'
        await db.execute("select set_config('tcg.user_id',$1,false)",str(owner))
        assert await db.fetchval('select count(*) from tcg.reference_catalogue_prices')==1
        try:
            await db.execute(GUIDE_SQL,*guide_args)
            raise AssertionError('Non-admin replaced catalogue guide evidence')
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("select set_config('tcg.user_id','',false)")
        assert await db.fetchval('select count(*) from tcg.reference_catalogue_prices')==0
        await db.execute('reset role')
        for role in ('anon','authenticated'):
            assert not await db.fetchval("select has_table_privilege($1,'tcg.reference_catalogue_prices','SELECT')",role)
    finally:await db.close()
    print('PASS: real sealed query, replay, set previews, publication gating/backoff, price finalization/audit, migrations and RLS')


asyncio.run(main())
