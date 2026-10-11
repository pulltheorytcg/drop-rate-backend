"""Real PostgreSQL regression for the production graded/raw-state rejection.

Synthetic collection with the reported batch dimensions, NOT the user's CSV.
Uses actual import handlers, restricted tcg_api, and the guard function read
from committed production migrations. This does not import live customer stock.
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg

from app import imports, owner_auto_imports as api, import_inventory
from app.db import _init_connection, user_connection
from app.import_review import ImportCandidateSkipRequest
from owner_auto_import_postgres import SCHEMA, expected_error

ROOT=Path(__file__).resolve().parents[1]


def committed_guard():
    pattern=re.compile(
        r'create\s+(?:or\s+replace\s+)?function\s+tcg\.validate_inventory_condition_state\s*\(\s*\)'
        r'.*?\bas\s+(\$[A-Za-z0-9_]*\$).*?\1\s*;',re.I|re.S)
    definitions=[]
    for path in sorted((ROOT/'database/migrations').glob('*.sql')):
        for match in pattern.finditer(path.read_text()):
            definitions.append((path.name,match.group(0)))
    assert definitions,'Production condition-state guard is missing from committed migrations'
    name,sql=definitions[-1]
    assert 'Graded card inventory cannot also use raw card condition' in sql
    return name,sql


def collection():
    out=io.StringIO();writer=csv.writer(out,lineterminator='\n')
    writer.writerow(['Portfolio Name','Category','Product Name','Set','Card Number','Rarity',
                     'Variance','Quantity','Card Condition','Language','Grade','Average Cost Paid'])
    for i in range(483):
        recognised=i<88
        qty=2 if i<7 or 88<=i<132 else 1
        writer.writerow(['Synthetic','Pokemon',f'Synthetic Card {i}','Regression Set',f'{i:03}',
                         'C','Normal',qty,'Near Mint','English' if recognised else '',
                         'PSA 10' if i in (10,20,30,100) else 'Ungraded',''])
    return imports.ImportPreviewRequest(filename='synthetic-regression.csv',adapter='COLLECTR',content=out.getvalue())


def small_collection(quantity):
    return imports.ImportPreviewRequest(filename='synthetic-small.csv',adapter='COLLECTR',content=(
        'Portfolio Name,Category,Product Name,Set,Card Number,Rarity,Variance,Quantity,Card Condition,Language,Grade,Average Cost Paid\n'
        f'Synthetic,Pokemon,Synthetic Card 10,Regression Set,010,C,Normal,{quantity},Near Mint,English,PSA 10,\n'))


async def main():
    dsn=os.environ['IMPORT_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'127.0.0.1','localhost'} and url.path=='/import_intake_test','Disposable local database only'
    db=await asyncpg.connect(dsn);await _init_connection(db);pool=None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"),'Refusing nonempty database'
        await db.execute(SCHEMA)
        source,guard=committed_guard()
        await db.execute(guard)
        await db.execute('''create trigger inventory_condition_state_guard
            before insert or update on tcg.inventory_items
            for each row execute function tcg.validate_inventory_condition_state();
            alter table tcg.inventory_items add constraint inventory_items_check check(
              (grading_company is null and grade is null and certificate_number is null)
              or (grading_company is not null and grade is not null));
            alter table tcg.inventory_items add constraint inventory_items_physical_state_separation_check check(
              (nullif(btrim(condition),'') is null or
               (grading_company is null and grade is null and certificate_number is null and seal_status is null))
              and (seal_status is null or
               (nullif(btrim(condition),'') is null and grading_company is null and grade is null and certificate_number is null)));
        ''')
        migration=list((ROOT/'database/migrations').glob('*_owner_incremental_import_intake.sql'))
        assert len(migration)==1
        await db.execute(migration[0].read_text())
        owner_a,owner_b,actor_a,actor_b=[uuid4() for _ in range(4)]
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,'CONSIGNOR',1000)",[(owner_a,'Synthetic A'),(owner_b,'Synthetic B')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",[(actor_a,owner_a),(actor_b,owner_b)])
        cards={i:uuid4() for i in [*range(88),100]}
        await db.executemany('''insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
            values($1,$2,'CARD','Pokemon',$3,'Regression Set',$4,'Normal','C','English')''',
            [(card,f'synthetic:{i}',f'Synthetic Card {i}',f'{i:03}') for i,card in cards.items()])
        async def setup(connection):
            await connection.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=5,init=_init_connection,setup=setup,command_timeout=30)
        req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),state=SimpleNamespace(request_id='grade-state-regression'))
        a=SimpleNamespace(user_id=actor_a);b=SimpleNamespace(user_id=actor_b)
        preview=await imports.preview_import(collection(),req,a)
        batch=UUID(preview['batch_id'])
        assert preview['physical_units']==534 and preview['ready_units']==95 and preview['review_rows']==395
        # Match the old existing-preview shape: source-receipt metadata wasn't
        # present before incremental intake. Do not change production previews.
        await db.execute("update tcg.import_candidates set normalized_record=normalized_record-'_collectr_source_identity' where batch_id=$1",batch)
        before=await db.fetch('select id,raw_record,normalized_record,status from tcg.import_candidates where batch_id=$1 order by source_row',batch)
        project=import_inventory.inventory_condition_for_copy
        import_inventory.inventory_condition_for_copy=lambda record:record.get('condition')
        try:
            try:
                await api.add_recognised(batch,imports.ImportCommitRequest(version=1),req,a)
                raise AssertionError('Original production failure was not reproduced')
            except asyncpg.CheckViolationError as exc:
                assert 'Graded card inventory cannot also use raw card condition' in str(exc)
        finally:
            import_inventory.inventory_condition_for_copy=project
        assert await db.fetchval('select count(*) from tcg.inventory_items')==0
        assert before==await db.fetch('select id,raw_record,normalized_record,status from tcg.import_candidates where batch_id=$1 order by source_row',batch)
        result=await api.add_recognised(batch,imports.ImportCommitRequest(version=1),req,a)
        assert result['created_count']==95 and result['summary']['review_rows']==395 and result['summary']['review_units']==439
        assert result['automatic_intake'] and result['status']=='PREVIEW'
        inventory=await db.fetch('select * from tcg.inventory_items where owner_id=$1 order by id',owner_a)
        graded=[r for r in inventory if r['grade']]
        assert len(graded)==3 and all(r['condition'] is None and r['grading_company']=='PSA' and r['grade']=='10' for r in graded)
        assert all(r['source_record']['Card Condition']=='Near Mint' for r in graded)
        assert all(r['condition']=='Near Mint' for r in inventory if not r['grade'])
        assert all(r['owner_id']==owner_a and r['status']=='DRAFT' and not r['identity_confirmed'] and r['acquisition_cost_minor'] is None for r in inventory)
        for _ in range(3):
            replay=await api.upload_collection(collection(),req,a)
            assert replay['created_count']==0
        assert inventory==await db.fetch('select * from tcg.inventory_items where owner_id=$1 order by id',owner_a)
        pending=await db.fetchrow("select id from tcg.import_candidates where batch_id=$1 and catalogue_id=$2 and status='REVIEW'",batch,cards[100])
        assert pending
        await expected_error(api.confirm_candidate(batch,pending['id'],api.ConfirmImportCandidate(version=result['version'],catalogue_id=cards[100]),req,b),404)
        async with user_connection(pool,actor_b,'foreign') as c:
            assert await c.fetchval('select count(*) from tcg.inventory_items')==0
        confirmed=await api.confirm_candidate(batch,pending['id'],api.ConfirmImportCandidate(version=result['version'],catalogue_id=cards[100]),req,a)
        assert confirmed['created_count']==2 and confirmed['candidate']['status']=='COMMITTED'
        assert confirmed['summary']['added_units']==97
        assert await db.fetchval("select count(*) from tcg.inventory_items where owner_id=$1 and grade='10' and condition is null",owner_a)==5
        # Separate owner: complete graded snapshot and +1 re-export retain the
        # raw source condition as a receipt key; no new physical duplicates.
        one=await api.upload_collection(small_collection(1),req,b)
        assert one['created_count']==1 and one['status']=='COMMITTED'
        two=await api.upload_collection(small_collection(2),req,b)
        assert two['created_count']==1 and two['status']=='COMMITTED'
        assert (await api.upload_collection(small_collection(2),req,b))['created_count']==0
        assert await db.fetchval('select count(*) from tcg.inventory_items where owner_id=$1',owner_b)==2
        # Keep the actual database guard intact: bad direct physical writes
        # still fail. No trigger is disabled or broadened by the application fix.
        try:
            async with user_connection(pool,actor_b,'guard-still-active') as c:
                await c.execute("insert into tcg.inventory_items(id,inventory_code,catalogue_id,owner_id,condition,grading_company,grade) values($1,$2,$3,$4,'Near Mint','PSA','10')",uuid4(),'SYNTHETIC-INVALID',cards[10],owner_b)
            raise AssertionError('Production grade guard was weakened')
        except asyncpg.CheckViolationError:
            pass
        assert await db.fetchval('select count(*)=count(distinct inventory_code) from tcg.inventory_items')
        assert await db.fetchval('select count(*) from tcg.catalogue_products')==len(cards)
        print(f'PASS: production guard from {source}; old rejection reproduced/rolled back; synthetic 483 rows/534 copies -> 95 saved + 439 review copies; graded/raw separation; manual graded save; exact retries; owner isolation; graded +1 snapshot; guard unchanged.')
    finally:
        if pool: await pool.close()
        await db.close()


if __name__=='__main__':
    asyncio.run(main())
