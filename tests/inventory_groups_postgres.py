"""Real restricted-role pagination and exact-copy detail checks in disposable CI."""
from uuid import uuid4
from unittest.mock import patch
from app.db import user_connection
from app.inventory_display_groups import inventory_group_page
from app.owner_inventory import COPIES_SQL
from app.inventory_collection_filters import append_collection_filters, collection_facets, collection_state_counts
from app.inventory_value_sort import inventory_value_page


async def verify_display_groups(db, pool, owner, actor, foreign, foreign_actor):
    product, alternate = uuid4(), uuid4()
    for identifier, variant in [(product, 'base'), (alternate, 'parallel')]:
        await db.execute("""insert into tcg.catalogue_products
          (id,product_type,game,name,set_name,card_number,variant,rarity,language)
          values($1,'CARD','One Piece',$3,'Synthetic set','TEST-101',$2,'SR','English')""", identifier, variant,
          'Alphabetical first' if variant=='parallel' else 'Quantity test')
    await db.execute("insert into tcg.collectible_systems(code,system_kind) values('SPORTS_CARDS','SPORTS_CARD')")
    await db.execute("insert into tcg.catalogue_product_profiles(catalogue_id,system_code,identity_status) values($1,'SPORTS_CARDS','NEEDS_REVIEW')",alternate)
    ids = []
    async def copy(*, owner_id=owner, catalogue=product, condition=None, language='English',
                   company=None, grade=None, certificate=None, status='DRAFT', position=0):
        identifier = uuid4(); ids.append(identifier)
        await db.execute("""insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,
          condition,language,grading_company,grade,certificate_number,status,sale_intent,updated_at,created_at)
          values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'PERSONAL_COLLECTION',
            '2026-10-15 16:00:00+00'::timestamptz-make_interval(secs=>$11),
            '2026-10-15 16:00:00+00'::timestamptz+make_interval(secs=>$11))""",
          identifier, f'INV-QUANTITY-{len(ids):04}', owner_id, catalogue, condition, language,
          company, grade, certificate, status, position)
        return identifier
    # This one group used to be split across the 50-copy page boundary.
    raw = [await copy(status=['DRAFT','INSPECTION','APPROVED','RESERVED'][n % 4], position=n) for n in range(61)]
    implicit = await copy(language=None, position=62)
    nm = [await copy(condition='Near Mint', position=70+n) for n in range(2)]
    lp = [await copy(condition='Lightly Played', position=75+n) for n in range(2)]
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
        assert first[:2] == (13, 76), first[:2]
        assert set(first[2]) == set(raw + [implicit]), 'Group split at a physical-copy page boundary'
        second = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 1)
        assert set(second[2]) == set(nm), 'Explicit condition must be separate from unknown'
        third = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 2)
        assert set(third[2]) == set(lp), 'Lightly Played must never merge into Near Mint'
        all_pages = []
        for offset in range(13):
            total, copies, page = await inventory_group_page(connection, where, [owner, [product, alternate]], 1, offset)
            all_pages.extend(page)
        assert len(all_pages) == len(set(all_pages)) == 76
        assert other_owner not in all_pages
        assert (await inventory_group_page(connection, where, [owner, [product, alternate]], 1, 13))[2] == []
        # Alternate sorts are applied to groups, before page selection; no
        # last-page-only or post-enrichment client sorting is permitted.
        assert (await inventory_group_page(connection,where,[owner,[product,alternate]],1,0,sort='name'))[2]==[parallel]
        assert (await inventory_group_page(connection,where,[owner,[product,alternate]],1,0,sort='newest'))[2]==[withdrawn]
        assert set((await inventory_group_page(connection,where,[owner,[product,alternate]],1,0,sort='oldest'))[2])==set(raw+[implicit])
        filters=[where];params=[owner,[product,alternate]]
        append_collection_filters(filters,params,category='TCG',language='Japanese',grading='RAW')
        assert (await inventory_group_page(connection,' and '.join(filters),params,1,0))==(1,1,[jp])
        filters=[where];params=[owner,[product,alternate]]
        append_collection_filters(filters,params,category='SPORTS')
        assert (await inventory_group_page(connection,' and '.join(filters),params,1,0))==(1,1,[parallel]), 'SPORTS_CARD systems must map to the Sports category'
        filters=[where];params=[owner,[product,alternate]]
        append_collection_filters(filters,params,grading='GRADED')
        graded=await inventory_group_page(connection,' and '.join(filters),params,50,0)
        assert graded[:2]==(6,6) and set(graded[2])==set(slabs+partial+certificates)
        own_facets=await collection_facets(connection,owner)
        assert 'One Piece' in own_facets['games'] and 'Japanese' in own_facets['languages']
        assert (await collection_facets(connection,foreign))['games']==[], 'Facet query crossed owner scope'
        counts=await collection_state_counts(connection,owner)
        for label,state in [('personal','PERSONAL'),('for_sale','ALL_FOR_SALE'),('preparing','PREPARING'),('review','REVIEW'),('ready','READY'),('listed','LISTED')]:
            selection=['i.owner_id=$1'];values=[owner]
            append_collection_filters(selection,values,listing_state=state)
            assert (await inventory_group_page(connection,' and '.join(selection),values,50,0))[1]==counts[label]
        assert set((await collection_state_counts(connection,foreign)).values())=={0}, 'Overview state counts crossed owner scope'
        async def values(_,items):
            for row in items:
                value=2000 if row['condition']=='Near Mint' else 100
                row['reference_value']={'status':'AVAILABLE','market_value_minor':value}
                row['market_value_minor']=value
            return items
        # Exercise the complete value-sort candidate query under the real
        # restricted role, without requiring market evidence in this fixture.
        with patch('app.inventory_value_sort.add_shared_reference_values',values):
            page=await inventory_value_page(connection,where,[owner,[product,alternate]],1,0,grouped=True,descending=True)
            assert (page.total,page.copy_total)==(13,76) and set(page.ids)==set(nm)
            assert str(other_owner) not in page.snapshots
            foreign_page=await inventory_value_page(connection,where,[foreign,[product,alternate]],1,0,grouped=True,descending=True)
            assert foreign_page.total==foreign_page.copy_total==0 and not foreign_page.ids
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
