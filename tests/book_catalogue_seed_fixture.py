"""Real catalogue constraints, replay and cross-owner reference readback."""
from uuid import UUID
from pathlib import Path

from app.book_catalogue import with_book_details
from app.inventory_intake import _find_exact_catalogue
from app.schemas import ManualCatalogueCreate
from scripts.seed_book_catalogue import load_seed, seed_sql


async def exercise(db, users):
    batches = [load_seed(), load_seed(Path(__file__).resolve().parents[1] / 'backend/data/book_catalogue_expansion_20261021.json')]
    seed = {'entries': [r for batch in batches for r in batch['entries']]}
    inventory = await db.fetch('select * from tcg.inventory_items order by id')
    before = await db.fetchval('select count(*) from tcg.catalogue_products')
    for batch in batches:
        await db.execute(seed_sql(batch))
        await db.execute(seed_sql(batch))
    assert await db.fetchval('select count(*) from tcg.catalogue_products') == before + 46
    assert inventory == await db.fetch('select * from tcg.inventory_items order by id')
    ids = [UUID(row['id']) for row in seed['entries']]
    for user in users:
        async with db.transaction():
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)", str(user))
            rows = await db.fetch('''select p.id as catalogue_id,p.product_type,p.language,p.name
                from tcg.catalogue_products p where p.id=any($1::uuid[]) order by p.name''', ids)
            assert len(rows) == 46
            enriched = await with_book_details(db, rows)
            assert sum(row['book_details']['printing_number'] is None for row in enriched) == 45
            assert all(row['publisher_source_url'].startswith('https://') for row in enriched)
            assert all(row['artwork_kind'] == 'PUBLISHER_REFERENCE' for row in enriched)
            assert all('reference_kind=book' in row['reference_image_path'] for row in enriched)
            assert all(row['book_market_status'] == 'PRINTING_REVIEW_REQUIRED' for row in enriched)
            assert all(row.get('market_value_minor') is None for row in enriched)
            for row in seed['entries']:
                product = ManualCatalogueCreate(**row['catalogue'], comic_printing=row['book'])
                assert (await _find_exact_catalogue(db, product))['id'] == UUID(row['id'])
    assert not await db.fetchval("select exists(select 1 from tcg.comic_printing_details where catalogue_id=any($1::uuid[]) and identity_status<>'STRUCTURED')", ids)
    print('PASS: 46 publisher editions inserted once, replay added zero, two restricted users see the same references, intake reuses exact identities, no stock/price/media approval writes.')
