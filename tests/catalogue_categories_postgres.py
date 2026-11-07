"""Real PostgreSQL category, publication and review-visibility checks in PGlite.

This starts a disposable database and never accepts production credentials.
"""
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app import catalogue_r2_live as live
from app.catalogue_browser import product_query
from app.catalogue_r2_browse import build_browse_index, indexed_catalogue_query
from app.catalogue_r2_navigation import build_navigation
from catalogue_r2_cache_postgres import PGliteConnection, seed, authorized, ACTOR_A, ACTOR_B, OWNER_A, OWNER_B

ROOT = Path(__file__).resolve().parents[1]
IDS = [UUID(f"30000000-0000-0000-0000-0000000000{n}") for n in (41, 42, 43, 44)]


async def check():
    db = await PGliteConnection.open()
    try:
        await seed(db)
        await db.execute('''create function tcg.current_access_role() returns text language sql stable as
          $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$''')
        for index, item_id in enumerate(IDS):
            figure = index >= 2
            kind, system = ("FIGURE", "FIGURES") if figure else ("CARD", "SPORTS_CARDS")
            await db.execute("""insert into tcg.catalogue_products
              (id,product_type,game,name,set_name,card_number,variant,rarity,language)
              values($1,$2,$3,$4,'Synthetic reference set','1','Base','','English')""",
                             item_id, kind, system, f"Synthetic category {index}")
            await db.execute("""insert into tcg.catalogue_product_profiles
              (catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
              values($1,$2,$3,$4,current_date-1,$5::jsonb)""", item_id, system, kind,
                             "VERIFIED" if index % 2 == 0 else "NEEDS_REVIEW",
                             json.dumps({"identity_source": "OFFICIAL_CATALOGUE" if index % 2 == 0 else "SELLER_ENTERED", "submitted_by_user_id": str(ACTOR_A)}))
        for number, system in enumerate(('MARVEL_COMICS', 'DC_COMICS', 'OTHER_COMICS', 'MANGA'), start=50):
            item_id = UUID(f'30000000-0000-0000-0000-{number:012d}')
            await db.execute("""insert into tcg.catalogue_products
              (id,product_type,game,name,set_name,card_number,variant,rarity,language)
              values($1,'COMIC',$2,'Synthetic book','Synthetic series','1','First','','English')""",
                             item_id, system)
            await db.execute("""insert into tcg.catalogue_product_profiles
              (catalogue_id,system_code,collectible_type,identity_status,release_date)
              values($1,$2,'COMIC','VERIFIED',current_date-1)""", item_id, system)
        for migration in ("20261030002930_live_catalogue_r2_publication.sql", "20261030085900_r2_relevant_change_invalidation.sql", "20261103150140_catalogue_review_visibility_r2.sql"):
            await db.execute((ROOT / "database/migrations" / migration).read_text())
        shared = {relation: json.loads(await db.fetchval(live.chunk_sql(relation), 1000, 0))
                  for relation in live.RELATIONS}
        published = {row["id"] for row in shared["catalogue_products"]}
        assert str(IDS[0]) in published and str(IDS[2]) in published
        assert str(IDS[1]) not in published and str(IDS[3]) not in published
        assert "submitted_by_user_id" not in json.dumps(shared)
        snapshot = live.LiveCatalogue(1, "synthetic", shared)
        mappings = [dict(row) for row in await db.fetch("select source_provider,system_code,provider_language,provider_id,provider_entity_type,provider_variant_key,match_status,catalogue_id::text from tcg.provider_catalogue_mappings")]
        index = build_browse_index(shared, verified_mappings=mappings)
        for category, expected in (("SPORTS", {str(IDS[0])}), ("FIGURES", {str(IDS[2])}), ("TCG", set())):
            query, args = product_query(owner_id=OWNER_A, category=category, limit=80)
            async with authorized(db, ACTOR_A):
                actual = [dict(row) for row in await db.fetch(query, *args)]
                sql, cached_args = snapshot.sql(query, args)
                cached = [dict(row) for row in await db.fetch(sql, *cached_args)]
                assert actual == cached, f"Live SQL and R2 differ for {category}"
                bounded_sql, bounded_args, mode = indexed_catalogue_query(query, args, index)
                bounded = [dict(row) for row in await db.fetch(bounded_sql, *bounded_args)]
                assert actual == bounded, (category, mode, [{key: (left.get(key), right.get(key)) for key in left if left.get(key) != right.get(key)} for left, right in zip(actual, bounded)], len(actual), len(bounded))
                assert mode == "FILTERED_NEWEST", mode
            actual_new = {str(row["catalogue_id"]) for row in actual if str(row.get("catalogue_id")) in {str(item_id) for item_id in IDS}}
            assert actual_new == expected
        # These are the complete requests emitted by the five UI defaults.
        # Category-only requests above do not expose the old six-parameter
        # collision between two static lists and system/text search.
        requests = [
            dict(category='TCG', product_type='CARD'),
            dict(category='SPORTS', system_code='SPORTS_CARDS', product_type='CARD'),
            dict(category='COMICS', system_code='COMICS', product_type='COMIC'),
            dict(category='MANGA', system_code='MANGA', product_type='COMIC'),
            dict(category='FIGURES', system_code='FIGURES', product_type='FIGURE'),
            dict(category='TCG', system_code='POKEMON_TCG'),
            dict(category='TCG', system_code='POKEMON_TCG', product_type='SEALED'),
            dict(category='COMICS', system_code='DC_COMICS', product_type='COMIC'),
        ]
        checked = 0
        for actor, owner in ((ACTOR_A, OWNER_A), (ACTOR_B, OWNER_B)):
            async with authorized(db, actor):
                for scope in requests:
                    text = 'Fixture' if scope['category'] == 'TCG' else 'Synthetic'
                    for search in ({}, dict(q=text), dict(q=text, limit=1, offset=1)):
                        query, args = product_query(owner_id=owner, **scope, **search)
                        actual = [dict(row) for row in await db.fetch(query, *args)]
                        bounded_sql, bounded_args, mode = indexed_catalogue_query(query, args, index)
                        bounded = [dict(row) for row in await db.fetch(bounded_sql, *bounded_args)]
                        assert actual == bounded, (actor, scope, search, mode, actual, bounded)
                        assert mode == ('SEARCH_CATEGORY_TEXT' if search else 'FILTERED_NEWEST')
                        if not search.get('offset'):
                            assert actual, ('Category fixture must not pass vacuously', scope, search)
                        assert not {str(IDS[1]), str(IDS[3])}.intersection(
                            str(row['catalogue_id']) for row in bounded)
                        checked += 1
        async with authorized(db, ACTOR_A):
            query, args = product_query(owner_id=OWNER_A, keys=[f"c:{IDS[0]}", f"c:{IDS[2]}"])
            assert len(await db.fetch(query, *args)) == 2, "Unscoped saved references must cross categories"
            query, args = product_query(owner_id=OWNER_A, category="TCG", keys=[f"c:{IDS[0]}"])
            assert not await db.fetch(query, *args), "Explicit category still applies to keyed queries"
        nav = {row["system_code"]: row for row in build_navigation(shared).games()}
        assert nav["SPORTS_CARDS"]["products"] == nav["FIGURES"]["products"] == 1
        generation = await db.fetchval("select generation from tcg_private.live_catalogue_r2_publication where singleton")
        await db.execute("update tcg.catalogue_product_profiles set identity_status='NEEDS_REVIEW' where catalogue_id=$1", IDS[0])
        assert await db.fetchval("select generation from tcg_private.live_catalogue_r2_publication where singleton") == generation + 1
        assert str(IDS[0]) not in {row["id"] for row in json.loads(await db.fetchval(live.chunk_sql("catalogue_products"), 1000, 0))}
        assert not await db.fetchval("select has_function_privilege('tcg_api','tcg_private.invalidate_live_catalogue_r2()','EXECUTE')")
        print(f"PASS: {checked} complete UI category/search SQL parity checks across two owners, plus category isolation, private identity exclusion, saved cross-category lookup and review invalidation")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(check())
