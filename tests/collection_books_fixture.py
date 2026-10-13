"""Book admission additions to the disposable signed-HTTP/RLS collection fixture."""
import asyncio
import json
import re
from copy import deepcopy
from uuid import UUID, uuid4

import asyncpg


async def prepare(db, root):
    sql = (root / 'database/migrations/20260927180056_collectible_identity_foundation.sql').read_text()
    await db.execute('drop table tcg.catalogue_product_profiles')
    for name in ('collectible_systems', 'catalogue_product_profiles', 'comic_printing_details'):
        definition = re.search(rf'create table tcg\.{name} \([\s\S]*?\n\);', sql).group()
        await db.execute(definition)
        await db.execute(f'alter table tcg.{name} enable row level security; alter table tcg.{name} force row level security;')
        for policy in re.findall(rf'create policy \w+ on tcg\.{name}\n[\s\S]*?;', sql):
            # Defined below before the first policy is installed.
            if 'current_access_role' in policy:
                await db.execute('''create or replace function tcg.current_access_role() returns text language sql stable as
                    $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$;''')
            await db.execute(policy)
    await db.execute('''insert into tcg.collectible_systems(code,display_name,franchise,system_kind) values
        ('ONE_PIECE_CARD_GAME','One Piece','One Piece','TCG'),('MARVEL_COMICS','Marvel Comics','Marvel','COMICS'),
        ('DC_COMICS','DC Comics','DC','COMICS');
        alter table tcg.catalogue_products alter column id set default gen_random_uuid();
        grant select,insert on tcg.catalogue_products,tcg.catalogue_product_profiles,tcg.comic_printing_details to tcg_api;
        grant update on tcg.catalogue_product_profiles,tcg.comic_printing_details to tcg_api;
        grant update on tcg.inventory_items to tcg_api;
        grant select on tcg.collectible_systems to tcg_api;
        alter table tcg.catalogue_products enable row level security;
        alter table tcg.catalogue_products force row level security;
        create policy catalogue_read on tcg.catalogue_products for select to tcg_api using(exists(select 1 from tcg.owners));
        create policy catalogue_insert on tcg.catalogue_products for insert to tcg_api with check(exists(select 1 from tcg.owners));''')
    for name in ('validate_catalogue_product_profile', 'validate_collectible_subtype'):
        definition = re.search(rf'create or replace function tcg\.{name}\(\)[\s\S]*?\n\$\$;', sql).group()
        await db.execute(definition)
    for name in ('catalogue_product_profiles_validate', 'comic_printing_details_validate'):
        await db.execute(re.search(rf'create trigger {name}[\s\S]*?;', sql).group())
    await db.execute((root / 'database/migrations/20261013222139_seller_comics_manga.sql').read_text())


async def exercise(client, db, headers, ua, ub, uf, owner_a, owner_b):
    path = '/api/v1/owner/books/intake'
    printing = dict(system_code='MARVEL_COMICS',series_title='Fixture Spider-Man',issue_number='1',
                    printing_number=1,release_year=2022,cover_code='Cover A',book_format='SINGLE_ISSUE')
    payload = dict(new_catalogue=dict(product_type='COMIC',game='Books',name='Book',set_name='Series',
                                     language='English',comic_printing=printing),condition='Very Fine')
    for actor, expected in ((None,401),(uf,403)):
        response = await client.post(path,json=payload,headers=headers(actor,uuid4()) if actor else {})
        assert response.status_code == expected,response.text
    key = uuid4()
    responses = await asyncio.gather(*[client.post(path,json=payload,headers=headers(ua,key)) for _ in range(2)])
    assert all(r.status_code == 201 for r in responses),[r.text for r in responses]
    assert len({r.json()['inventory']['id'] for r in responses}) == 1
    result = responses[0].json(); cat = UUID(result['catalogue']['id'])
    row = await db.fetchrow('select * from tcg.inventory_items where id=$1',UUID(result['inventory']['id']))
    assert row['owner_id'] == owner_a and row['status'] == 'DRAFT' and not row['identity_confirmed']
    assert row['sale_intent'] == 'PERSONAL_COLLECTION' and row['market_value_minor'] is None
    assert row['store_price_minor'] is None and row['condition'] == 'Very Fine' and row['seal_status'] is None
    assert await db.fetchval('select identity_status from tcg.comic_printing_details where catalogue_id=$1',cat) == 'NEEDS_REVIEW'
    # Another seller can own a separate copy of the same shared identity.
    second = await client.post(path,json=payload,headers=headers(ub,uuid4()))
    assert second.status_code == 201 and second.json()['catalogue']['id'] == str(cat),second.text
    assert second.json()['inventory']['owner_id'] == str(owner_b)
    assert second.json()['inventory']['id'] != result['inventory']['id']
    changed = deepcopy(payload); changed['new_catalogue']['comic_printing']['printing_number'] = 2
    assert (await client.post(path,json=changed,headers=headers(ua,key))).status_code == 409
    other_edition = await client.post(path,json=changed,headers=headers(ua,uuid4()))
    assert other_edition.status_code == 201 and other_edition.json()['catalogue']['id'] != str(cat),other_edition.text
    graded = {**payload,'condition':None,'grading_company':'CBCS','grade':'9.8','certificate_number':'BOOK-0001'}
    slab = await client.post(path,json=graded,headers=headers(ua,uuid4()))
    assert slab.status_code == 201 and slab.json()['inventory']['grade'] == '9.8',slab.text
    assert (await client.post(path,json=graded,headers=headers(ub,uuid4()))).status_code == 409
    for extra in [dict(condition='Near Mint'),dict(seal_status='SEALED'),dict(grade='11'),dict(certificate_number=None),dict(language='Japanese')]:
        response = await client.post(path,json={**graded,**extra},headers=headers(ua,uuid4()))
        assert response.status_code == 422,response.text
    manga = deepcopy(payload); manga['new_catalogue']['comic_printing'].update(system_code='MANGA',book_format='MANGA',
        publisher='Fixture Publisher',series_title='Fixture Manga',issue_number='2',barcode_gtin='978-1-234567-89-0')
    response = await client.post(path,json=manga,headers=headers(ua,uuid4()))
    assert response.status_code == 201 and response.json()['catalogue']['game'] == 'Manga',response.text
    assert response.json()['catalogue']['name'] == 'Fixture Manga Volume 2'
    # Restricted SQL role also rejects self-verification and invalid physical fields.
    for statement, args, error in [
        ("update tcg.inventory_items set condition='Lightly Played' where id=$1",[row['id']],asyncpg.CheckViolationError),
        ("update tcg.inventory_items set seal_status='SEALED' where id=$1",[row['id']],asyncpg.CheckViolationError),
    ]:
        async with db.transaction():
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)",str(ua))
            try:
                async with db.transaction(): await db.execute(statement,*args)
            except error: pass
            else: raise AssertionError('Database physical guard allowed invalid book state')
    async with db.transaction():
        await db.execute('set local role tcg_api')
        await db.execute("select set_config('tcg.user_id',$1,true)",str(ub))
        assert not await db.fetchval('select exists(select 1 from tcg.inventory_items where id=$1)',row['id'])
        assert await db.execute("update tcg.comic_printing_details set identity_status='VERIFIED' where catalogue_id=$1",cat) == 'UPDATE 0'
        assert await db.execute("update tcg.catalogue_product_profiles set identity_status='VERIFIED' where catalogue_id=$1",cat) == 'UPDATE 0'
    assert await db.fetchval('select count(*) from tcg.catalogue_products where product_type=\'COMIC\'') == 3
    return 3
