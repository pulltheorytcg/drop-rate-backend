"""Disposable PostgreSQL: actual portfolio, history SQL, migrations and RLS.

Uses the existing pinned PGlite runtime, never a production DSN or provider.
Synthetic history is deliberately different from today's cached guide quote.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.inventory_market_movers import HISTORY_SQL, shared_weekly_movers
from app.inventory_reference_values import reference_portfolio
from catalogue_r2_cache_postgres import PGliteConnection, authorized
from shared_reference_fixture import install_reference_schema
from shared_reference_postgres import SCHEMA


async def main():
    db = await PGliteConnection.open()
    try:
        await db.execute(SCHEMA)
        await install_reference_schema(db)
        owner_a, owner_b, actor_a, actor_b, card = [uuid4() for _ in range(5)]
        for owner, actor in ((owner_a, actor_a), (owner_b, actor_b)):
            await db.execute("insert into tcg.owners(id,display_name,owner_type,active) values($1,'Synthetic','CONSIGNOR',true)", owner)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')", actor, owner)
        await db.execute("insert into tcg.catalogue_products values($1,'CARD','Pokemon','Synthetic','Fixture set','001','Normal','Common','English')", card)
        for owner, status in ((owner_a, 'DRAFT'), (owner_a, 'RESERVED'), (owner_a, 'SOLD'),
                              (owner_a, 'WITHDRAWN'), (owner_b, 'DRAFT')):
            await db.execute("""insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,
                language,condition,status,market_value_minor,store_price_minor)
                values($1,$2,$3,$4,'English','Near Mint',$5,999999,999999)""", uuid4(), str(uuid4()), owner, card, status)
        now = datetime.now(timezone.utc)
        checked = now-timedelta(days=1)
        digest = await db.fetchval("""select md5(concat_ws(chr(31),product_type,game,name,set_name,
            card_number,variant,rarity,language)) from tcg.catalogue_products where id=$1""", card)
        reference = dict(provider='Cardmarket', system_code='POKEMON_TCG', reference_language='English',
                         provider_id='fixture-001', set_id='fixture')
        quote = dict(source='CARDMARKET_BULK_SINGLES', finish='Normal', source_field='trend',
                     product_id='fixture-001', original_currency='EUR', fx_source='ECB_EURO_REFERENCE_RATES',
                     reference_printing_id='fixture-001', reference_rarity='Common',
                     reference_identity=dict(name='Synthetic', set_id='fixture', card_number='001', set_name='Fixture set'),
                     price_gbp_minor=1200, observed_at=checked.isoformat())
        current = dict(id=str(uuid4()), catalogue_id=str(card), identity_digest=digest, basis_key='guide-normal',
                       basis_condition=None, basis_language='English', grading_company=None, grade=None, seal_status=None,
                       market_value_minor=1200, recommended_retail_minor=1300, confidence=0.5,
                       algorithm_version='drop-rate-market-v4', oldest_sale_at=None,
                       evidence_checked_at=checked.isoformat(), calculated_at=(checked+timedelta(minutes=10)).isoformat(),
                       calculation_day=checked.date().isoformat(), evidence_digest=str(uuid4()),
                       evidence=dict(method='CATALOGUE_CARDMARKET_V1', input_sale_count=0,
                           valuation_kind='REFERENCE_ESTIMATE', source='CARDMARKET', ruleset_revision='fixture-v1',
                           reference=reference, quote=quote))
        baseline = deepcopy(current)
        earlier = checked-timedelta(days=7)
        baseline.update(id=str(uuid4()), market_value_minor=1000, recommended_retail_minor=1100,
                        evidence_checked_at=earlier.isoformat(), calculated_at=(earlier+timedelta(minutes=10)).isoformat(),
                        calculation_day=earlier.date().isoformat(), evidence_digest=str(uuid4()))
        baseline['evidence']['quote'].update(price_gbp_minor=1000, observed_at=earlier.isoformat())
        await db.execute("insert into tcg.reference_sets values('Cardmarket','POKEMON_TCG','English','fixture','Fixture set',current_date-30)")
        await db.execute("""insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number,rarity)
            values('Cardmarket','POKEMON_TCG','English','fixture-001','fixture','Synthetic','001','Common')""")
        await db.execute("insert into tcg.reference_market_prices values('Cardmarket','POKEMON_TCG','English','fixture-001',$1::jsonb)", [quote])

        async def insert(row):
            await db.execute("insert into tcg.catalogue_market_snapshots select * from jsonb_populate_record(null::tcg.catalogue_market_snapshots,$1::jsonb)", row)

        async def result(actor=actor_a, owner=owner_a):
            async with authorized(db, actor):
                assert await db.fetchval('select current_user') == 'tcg_api'
                items = await reference_portfolio(db, [owner])
                return await shared_weekly_movers(db, items, now=now)

        await insert(current)
        await insert(baseline)
        before = await db.fetchval("select jsonb_agg(to_jsonb(s) order by id) from tcg.catalogue_market_snapshots s")
        actual = await result()
        assert actual['summary']['owned_item_count'] == 2
        assert actual['summary']['comparable_product_count'] == 1
        mover, = actual['movers']
        assert mover['quantity'] == 2 and mover['change_pct'] == 20 and mover['current_value_minor'] == 1200
        assert mover['comparison_kind'] == 'GUIDE_ESTIMATE'
        assert (await result(actor_b, owner_b))['movers'][0]['quantity'] == 1
        assert (await result(actor_a, owner_b))['summary']['status'] == 'EMPTY_COLLECTION'
        assert (await result(None, owner_a))['summary']['status'] == 'EMPTY_COLLECTION'
        assert before == await db.fetchval("select jsonb_agg(to_jsonb(s) order by id) from tcg.catalogue_market_snapshots s")
        assert not await db.fetchval('select tcg.cardmarket_reference_current($1::jsonb)', baseline['evidence']), 'Fixture must exercise older quote absent from the current cache'
        await db.execute('delete from tcg.catalogue_market_snapshots where id=$1', baseline['id'])

        # Each wrong series is a real historical row in PostgreSQL, never a mocked query response.
        changes = [
            {'identity_digest': 'old-printing'}, {'basis_key': 'other'}, {'basis_language': 'Japanese'},
            {'evidence': {**baseline['evidence'], 'source': 'OTHER'}},
            {'evidence': {**baseline['evidence'], 'ruleset_revision': 'other-v2'}},
            {'evidence': {**baseline['evidence'], 'book_identity_digest': 'different-book'}},
            {'evidence': {**baseline['evidence'], 'reference': {**reference, 'provider_id': 'other'}}},
            {'evidence': {**baseline['evidence'], 'quote': {**baseline['evidence']['quote'], 'finish': 'Reverse'}}},
            {'evidence': {**baseline['evidence'], 'quote': {**baseline['evidence']['quote'], 'fx_source': 'OTHER'}}},
            {'evidence_checked_at': (checked-timedelta(days=5)).isoformat(), 'calculated_at': (checked-timedelta(days=5)).isoformat()},
            {'evidence_checked_at': (checked-timedelta(days=9)).isoformat(), 'calculated_at': (checked-timedelta(days=9)).isoformat()},
            {'calculated_at': now.isoformat()},
            {'evidence': dict(method='CATALOGUE_EBAY_V4', input_sale_count=5, source='EBAY_GB'), 'oldest_sale_at': earlier.isoformat()},
        ]
        for change in changes:
            wrong = {**baseline, **change}
            await insert(wrong)
            checked_result = await result()
            assert checked_result['summary']['status'] == 'WAITING_FOR_HISTORY', change
            assert not checked_result['movers'], change
            await db.execute('delete from tcg.catalogue_market_snapshots where id=$1', baseline['id'])

        for prior, expected_status, expected_change in ((1500, 'READY', -20), (1200, 'NO_CHANGE', None)):
            await insert({**baseline, 'market_value_minor': prior})
            checked_result = await result()
            assert checked_result['summary']['status'] == expected_status
            assert ([r['change_pct'] for r in checked_result['movers']] or [None]) == [expected_change]
            await db.execute('delete from tcg.catalogue_market_snapshots where id=$1', baseline['id'])

        await insert(baseline)
        await db.execute("insert into tcg.market_source_mappings values($1,'CARDMARKET','REVIEW')", card)
        assert (await result())['summary']['status'] == 'NO_CURRENT_VALUES'
        await db.execute('delete from tcg.market_source_mappings')
        await db.execute("insert into tcg.provider_catalogue_mappings(catalogue_id,provider_language,match_status) values($1,'English','REJECTED')", card)
        assert (await result())['summary']['status'] == 'NO_CURRENT_VALUES'
        await db.execute('delete from tcg.provider_catalogue_mappings')
        await db.execute("update tcg.catalogue_products set variant='Changed printing' where id=$1", card)
        assert (await result())['summary']['status'] == 'NO_CURRENT_VALUES'
        await db.execute("update tcg.catalogue_products set variant='Normal' where id=$1", card)
        await db.execute("update tcg.catalogue_market_snapshots set evidence_checked_at=$2 where id=$1", current['id'], now-timedelta(days=9))
        assert (await result())['summary']['status'] == 'NO_CURRENT_VALUES'
        # Zero is rejected by the real monetary constraint as well as the pure percentage helper.
        try:
            await insert({**baseline, 'id': str(uuid4()), 'evidence_digest': str(uuid4()), 'market_value_minor': 0})
        except RuntimeError as exc:
            assert '23514' in str(exc)
        else:
            raise AssertionError('Zero-value historical price passed the real database constraint')
        await db.execute('delete from tcg.catalogue_market_snapshots')
        sold_current = {**current, 'basis_key': 'raw-english', 'basis_condition': 'Near Mint',
                        'oldest_sale_at': (checked-timedelta(days=5)).isoformat(),
                        'evidence': dict(method='CATALOGUE_EBAY_V4', input_sale_count=5, source='EBAY_GB')}
        sold_baseline = {**baseline, 'basis_key': 'raw-english', 'basis_condition': 'Near Mint',
                         'oldest_sale_at': (earlier-timedelta(days=5)).isoformat(),
                         'evidence': sold_current['evidence']}
        await insert(sold_current)
        await insert(sold_baseline)
        sold_result = await result()
        assert sold_result['movers'][0]['comparison_kind'] == 'SOLD_MARKET'
        assert sold_result['movers'][0]['change_pct'] == 20
        await db.execute('delete from tcg.catalogue_market_snapshots where id=$1', baseline['id'])
        for change in ({'basis_condition': 'Damaged'}, {'grading_company': 'PSA', 'grade': '10'},
                       {'seal_status': 'SEALED'}, {'basis_language': 'Japanese'},
                       {'oldest_sale_at': (earlier-timedelta(days=91)).isoformat()}):
            await insert({**sold_baseline, **change})
            assert (await result())['summary']['status'] == 'WAITING_FOR_HISTORY', change
            await db.execute('delete from tcg.catalogue_market_snapshots where id=$1', baseline['id'])
        print('PASS: exact bound PostgreSQL history query, real shared migrations, 18 cohort/time exclusions, guide and sold movement, rise/fall/unchanged, stale/mapping/identity rejection, owner RLS, grouped active copies and read-only snapshots')
    finally:
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())
