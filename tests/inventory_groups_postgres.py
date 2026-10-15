"""Real restricted-role pagination and exact-copy detail checks in disposable CI."""
from uuid import uuid4
from app.db import user_connection
from app.inventory_display_groups import inventory_group_page
from app.owner_inventory import COPIES_SQL


async def verify_display_groups(db, pool, owner, actor, foreign, foreign_actor):
    product, alternate = uuid4(), uuid4()
    for identifier, variant in [(product, 'base'), (alternate, 'parallel')]:
        await db.execute("""insert into tcg.catalogue_products
          (id,product_type,game,name,set_name,card_number,variant,rarity,language)
          values($1,'CARD','One Piece','Quantity test','Synthetic set','TEST-101',$2,'SR','English')""", identifier, variant)
    ids = []
    async def copy(*, owner_id=owner, catalogue=product, condition=None, language='English',
                   company=None, grade=None, certificate=None, status='DRAFT', position=0):
        identifier = uuid4(); ids.append(identifier)
        await db.execute("""insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,
          condition,language,grading_company,grade,certificate_number,status,sale_intent,updated_at)
          values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'PERSONAL_COLLECTION',
            '2026-10-15 16:00:00+00'::timestamptz-make_interval(secs=>$11))""",
          identifier, f'INV-QUANTITY-{len(ids):04}', owner_id, catalogue, condition, language,
          company, grade, certificate, status, position)
        return identifier
    # This one group used to be split across the 50-copy page boundary.
    raw = [await copy(status=['DRAFT','INSPECTION','APPROVED','RESERVED'][n % 4], position=n) for n in range(61)]
    implicit = await copy(language=None, position=62)
    nm = [await copy(condition='Near Mint', position=70+n) for n in range(2)]
    slabs = [await copy(company='PSA', grade='10', certificate=str(n), position=80+n) for n in range(2)]
    partial = [await copy(grade='10', position=90+n) for n in range(2)]
    certificates = [await copy(certificate=str(n), position=100+n) for n in range(2)]
    jp = await copy(language='Japanese', position=110)
    parallel = await copy(catalogue=alternate, position=120)
    sold = await copy(status='SOLD', position=130)
    withdrawn = await copy(status='WITHDRAWN', position=140)
    other_owner = await copy(owner_id=foreign)
    before = await db.fetchval("select jsonb_agg(to_jsonb(i) order by id) from tcg.inventory_items i where id=any($1::uuid[])", ids)
    where = 'i.owner_id=$1 and i.catalogue_id=any($2::uuid[])'
    async with user_connection(pool, actor, 'quantity-groups-fixture') as connection:
        first = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 0)
        assert first[:2] == (12, 74), first[:2]
        assert set(first[2]) == set(raw + [implicit]), 'Group split at a physical-copy page boundary'
        second = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 1)
        assert set(second[2]) == set(nm), 'Explicit condition must be separate from unknown'
        all_pages = []
        for offset in range(12):
            total, copies, page = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, offset)
            all_pages.extend(page)
        assert len(all_pages) == len(set(all_pages)) == 74
        assert other_owner not in all_pages
        assert (await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 12))[2] == []
        total, count, approved = await inventory_group_page(connection, where+" and i.status=$3", [owner,[product,alternate],'APPROVED'], 50, 0)
        assert total == 1 and count == 15 and set(approved) == set(raw[2::4])
        for identifier in slabs + partial + certificates:
            rows = await connection.fetch(COPIES_SQL, identifier, owner)
            assert [row['id'] for row in rows] == [identifier], 'Graded/certified copies were pooled'
        rows = await connection.fetch(COPIES_SQL, raw[0], owner)
        assert {row['id'] for row in rows} == set(raw + [implicit])
        assert await connection.fetch(COPIES_SQL, other_owner, owner) == []
        assert (await inventory_group_page(connection, where, [foreign,[product,alternate]], 50, 0))[:2] == (0,0)
    async with user_connection(pool, foreign_actor, 'quantity-other-owner') as connection:
        assert (await inventory_group_page(connection, where, [foreign,[product,alternate]], 50, 0)) == (1,1,[other_owner])
    after = await db.fetchval("select jsonb_agg(to_jsonb(i) order by id) from tcg.inventory_items i where id=any($1::uuid[])", ids)
    assert before == after, 'Read-only grouping changed physical stock'
    print('Inventory grouping PostgreSQL: 62-copy group intact across pagination; condition, grading, certificate, printing, language, history, filters and owner isolation PASS; zero copy writes.')
