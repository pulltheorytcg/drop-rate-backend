"""Actual Postgres transactions, stable-source replay, ownership and readback."""
import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import asyncpg

from app.book_bulk_import import ImportPaused, apply_batch, _apply_one
from app.book_catalogue import with_book_details
from app.book_catalogue_sources import normalise
from app.book_research import catalogue_candidates
from book_bulk_samples import entry, gcd, publisher


async def exercise(db, users):
    root = Path(__file__).resolve().parents[1]
    sql = (root / 'database/migrations/20260927180056_collectible_identity_foundation.sql').read_text()
    # Replace the earlier browse test's minimal stub with the REAL source table,
    # unique index, constraints and policies. This is a disposable local DB only.
    await db.execute('''alter table tcg.provider_catalogue_mappings rename to fixture_prior_mappings;
        create schema if not exists auth; create table if not exists auth.users(id uuid primary key);''')
    await db.execute(re.search(r'create table tcg\.provider_catalogue_mappings \([\s\S]*?\n\);', sql).group())
    await db.execute('''alter table tcg.provider_catalogue_mappings enable row level security;
        alter table tcg.provider_catalogue_mappings force row level security;
        grant select,insert,update on tcg.provider_catalogue_mappings to tcg_api;''')
    for policy in re.findall(r'create policy \w+ on tcg\.provider_catalogue_mappings\n[\s\S]*?;', sql):
        await db.execute(policy)
    stock = await db.fetch('select * from tcg.inventory_items order by id')
    baseline = await db.fetchval('select count(*) from tcg.catalogue_products')
    rows = [entry(9101, True), entry(9102, False), normalise('GCD', gcd(9103, True)), normalise('GCD', gcd(9104, False))]
    results = await apply_batch(db, rows, 'fixture-bulk')
    assert all(r[0] == 'IMPORTED' for r in results), results
    assert all(r[0] == 'EXISTING' for r in await apply_batch(db, rows, 'fixture-retry'))
    assert await db.fetchval('select count(*) from tcg.catalogue_products') == baseline + 4
    assert await db.fetchval('select count(*) from tcg.provider_catalogue_mappings') == 4

    # A later publisher snapshot may change the source record, not the existing
    # identity or someone's copy. It must go to review instead of being appended.
    changed = publisher(9101); changed['book']['issue_number'] = '999'
    assert (await apply_batch(db, [normalise('PUBLISHER', changed)], 'changed'))[0][2] == 'SOURCE_CHANGED_REVIEW_REQUIRED'
    collision = publisher(9101); collision['record_id'] = 'different'; collision['book']['series_title'] = 'Conflicting title'
    assert (await apply_batch(db, [normalise('PUBLISHER', collision)], 'collision'))[0][2] == 'BARCODE_IDENTITY_CONFLICT'
    same = publisher(9101); same['record_id'] = 'another-source-record'
    reused = await apply_batch(db, [normalise('PUBLISHER', same)], 'same-edition')
    assert reused[0][0] == 'EXISTING' and reused[0][1] == rows[0]['id']
    assert await db.fetchval('select count(*) from tcg.catalogue_products') == baseline + 4

    # Fail after the first row: neither the identity nor source ledger commits.
    count = 0
    async def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('synthetic interrupted chunk')
        return await _apply_one(*args)
    try:
        with patch('app.book_bulk_import._apply_one', fail_second):
            await apply_batch(db, [entry(9201), entry(9202)], 'interrupted')
    except RuntimeError:
        pass
    else:
        raise AssertionError('Interrupted batch must roll back')
    assert not await db.fetchval('select exists(select 1 from tcg.catalogue_products where id=$1)', UUID(entry(9201)['id']))
    assert await db.fetchval('select count(*) from tcg.provider_catalogue_mappings') == 5

    ids = [UUID(r['id']) for r in rows]
    for user in users:
        async with db.transaction():
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)", str(user))
            products = await db.fetch('select id as catalogue_id,product_type,language,name from tcg.catalogue_products where id=any($1::uuid[]) order by name', ids)
            assert len(products) == 4
            books = await with_book_details(db, products)
            assert sum(bool(b.get('reference_image_path')) for b in books) == 2
            assert sum(bool(b.get('book_data_attribution')) for b in books) == 2
            assert all(b['book_market_status'] == 'PRINTING_REVIEW_REQUIRED' and b.get('market_value_minor') is None for b in books)
            for row in rows[:2]:
                candidates = await catalogue_candidates(db, {**row['book'], 'language': 'English'})
                assert len(candidates) == 1 and candidates[0]['image_url'] == row['image_url']
    # A seller cannot forge the trusted publisher/STRUCTURED provenance needed
    # for a dynamic reference, nor write a source receipt under the shared RLS.
    try:
        async with db.transaction():
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)", str(users[0]))
            await db.execute("insert into tcg.provider_catalogue_mappings(catalogue_id,system_code,source_provider,provider_entity_type,provider_id,verification_basis) values($1,'MANGA','PUBLISHER','COMIC_PRINTING','forged','DETERMINISTIC_EXACT')", ids[0])
    except asyncpg.InsufficientPrivilegeError:
        pass
    else:
        raise AssertionError('Seller cannot write source mappings')
    # Exercise real read-only mode and verify the guard catches it before writes.
    await db.execute('set default_transaction_read_only=on')
    try:
        try:
            await apply_batch(db, [entry(9301)], 'readonly')
        except ImportPaused as exc:
            assert str(exc) == 'DATABASE_READ_ONLY'
        else:
            raise AssertionError('Read-only database must pause import')
    finally:
        await db.execute('set default_transaction_read_only=off')
    assert stock == await db.fetch('select * from tcg.inventory_items order by id')
    assert await db.fetchval('select count(*) from tcg.catalogue_products') == baseline + 4
    print('PASS: bulk comics + manga, exact artwork/attribution across owners, replay, source conflicts, barcode collision, transactional rollback, read-only guard and seller RLS; inventory unchanged.')
