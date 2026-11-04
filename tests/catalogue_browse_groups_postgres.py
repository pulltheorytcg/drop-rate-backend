"""Actual PostgreSQL facet SQL, grouping, pagination and RLS; synthetic data only.

Native CI accepts only a disposable localhost/catalogue_browse_groups_test DSN.
--pglite uses the existing pinned in-memory PostgreSQL test transport.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

from app.catalogue_browser import product_query, sets_query
from app.catalogue_browse_groups import BROWSE_GROUPS, SYSTEM_CATEGORIES, group_for
from app.db import _init_connection
from catalogue_r2_cache_postgres import (
    PGliteConnection, seed, authorized, OWNER_A, OWNER_B, ACTOR_A, ACTOR_B, PRIVATE,
)

ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = {"COMICS": "COMICS", "MANGA": "MANGA", "SPORTS": "SPORTS_CARDS", "FIGURES": "FIGURES"}
FACTS = [
    ("MARVEL_COMICS", {"publisher": "Marvel Comics"}),
    ("DC_COMICS", {"publisher": "DC Comics"}),
    ("OTHER_COMICS", {"publisher": " Image Comics "}),
    ("OTHER_COMICS", {"publisher": "Dark Horse"}),
    ("OTHER_COMICS", {"publisher": "IDW Publishing"}),
    ("OTHER_COMICS", {"publisher": "Unreviewed publisher"}),
    ("OTHER_COMICS", {"publisher": ["Image Comics"]}),
    ("MANGA", {"series_title": " One Piece ", "publisher": "VIZ Media"}),
    ("MANGA", {"series_title": "Baby & Me", "publisher": "VIZ Media"}),
    ("MANGA", {"series_title": "Initial D", "publisher": "Tokyopop"}),
    ("MANGA", {"series_title": "Princess Jellyfish", "publisher": "Kodansha"}),
    ("MANGA", {"series_title": "Other VIZ title", "publisher": "VIZ Media"}),
    ("MANGA", {"series_title": "Shonen unreviewed title", "publisher": "Kodansha"}),
    ("SPORTS_CARDS", {"manufacturer": "Topps"}),
    ("SPORTS_CARDS", {"manufacturer": " TOPPS "}),
    ("SPORTS_CARDS", {"manufacturer": "Panini"}),
    ("SPORTS_CARDS", {"manufacturer": "Unreviewed"}),
    ("SPORTS_CARDS", {"manufacturer": ["Topps"]}),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "Pop!"}),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "pop"}),
    ("FIGURES", {"manufacturer": "Good Smile Company", "product_line": "Nendoroid"}),
    ("FIGURES", {"manufacturer": "Funko", "product_line": "Other"}),
    ("FIGURES", {"manufacturer": {"name": "Funko"}, "product_line": "Pop!"}),
    ("FIGURES", {"manufacturer": "Other", "product_line": "Pop!"}),
    ("MANGA", {"series_title": "İnitial D", "publisher": "Kodansha"}),
    ("SPORTS_CARDS", {"manufacturer": "PanİNİ"}),
]
IDS = [UUID(int=700000 + index) for index in range(len(FACTS))]


async def checks(db):
    await seed(db)
    await db.execute("""create function tcg.current_access_role() returns text language sql stable as
      $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$;
      create table tcg.comic_printing_details(catalogue_id uuid primary key,
        system_code text,series_title text,attributes jsonb default '{}');
      grant select on tcg.comic_printing_details to tcg_api;
      alter table tcg.comic_printing_details enable row level security;
      alter table tcg.comic_printing_details force row level security;
      alter table tcg.catalogue_product_profiles enable row level security;
      alter table tcg.catalogue_product_profiles force row level security;""")
    foundation = (ROOT / "database/migrations/20260927180056_collectible_identity_foundation.sql").read_text()
    # Run the repository's actual existing read policies, not a permissive test
    # substitute. This feature does not introduce or alter database policies.
    for table in ("catalogue_product_profiles", "comic_printing_details"):
        policy = re.search(rf"create policy api_read on tcg\.{table}\s+for select to tcg_api using \([^;]+;", foundation)
        assert policy, table
        await db.execute(policy.group())
    for index, ((system, facts), item_id) in enumerate(zip(FACTS, IDS)):
        kind = "FIGURE" if system == "FIGURES" else "CARD" if system == "SPORTS_CARDS" else "COMIC"
        await db.execute("""insert into tcg.catalogue_products
          (id,product_type,game,name,set_name,card_number,variant,rarity,language,created_by_user_id)
          values($1,$2,$3,$4,'Shared group fixture','1','Base','','English',$5)""",
          item_id, kind, system, f"Synthetic group {index:03d}", ACTOR_A)
        attributes = {"private_note": PRIVATE}
        if system == "SPORTS_CARDS":
            attributes["sports_card"] = facts
        elif system == "FIGURES":
            attributes["figure_details"] = facts
        await db.execute("""insert into tcg.catalogue_product_profiles
          (catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
          values($1,$2,$3,'VERIFIED',current_date-1,$4::jsonb)""", item_id, system, kind, json.dumps(attributes))
        if kind == "COMIC":
            await db.execute("""insert into tcg.comic_printing_details
              values($1,$2,$3,$4::jsonb)""", item_id, system, facts.get("series_title", "Synthetic book series"),
              json.dumps({"publisher": facts.get("publisher"), "private_note": PRIVATE}))
    # One mixed-manufacturer set: two Topps identities and a Panini identity.
    # Owner A owns two copies of one Topps identity; B owns the other identity.
    for number, owner, item, value in ((1, OWNER_A, IDS[13], 100), (2, OWNER_A, IDS[13], 200),
                                      (3, OWNER_B, IDS[14], 900), (4, OWNER_A, IDS[15], 600)):
        await db.execute("""insert into tcg.inventory_items
          values($1,$2,$3,'DRAFT',$4,10,20,$5)""", UUID(int=800000+number), owner, item, value, PRIVATE)
    # A future or unreviewed sports record must stay excluded even if it has
    # an otherwise matching manufacturer. Neither facet relaxes release/review.
    for number, status, date in ((1, "NEEDS_REVIEW", "current_date-1"), (2, "VERIFIED", "current_date+5")):
        item_id = UUID(int=900000+number)
        await db.execute("""insert into tcg.catalogue_products
          values($1,'CARD','SPORTS_CARDS','Hidden Topps fixture','Shared group fixture','2','Base','','English',$2)""", item_id, ACTOR_A)
        await db.execute(f"""insert into tcg.catalogue_product_profiles
          (catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
          values($1,'SPORTS_CARDS','CARD',$2,{date},'{{"sports_card":{{"manufacturer":"Topps"}}}}')""", item_id, status)
    inventory_before = await db.fetchval("select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i")
    checks_count = 0
    for actor, owner in ((ACTOR_A, OWNER_A), (ACTOR_B, OWNER_B)):
        async with authorized(db, actor):
            for category, groups in BROWSE_GROUPS.items():
                for group in groups:
                    expected = [str(item_id) for (system, facts), item_id in zip(FACTS, IDS)
                        if SYSTEM_CATEGORIES[system] == category and group_for(system, facts) == group]
                    query, params = product_query(owner_id=owner, category=category, browse_group=group, sort="name", limit=80)
                    rows = await db.fetch(query, *params)
                    assert [str(row["catalogue_id"]) for row in rows] == expected, (category, group, rows)
                    assert PRIVATE not in str(rows)
                    assert all(row["market_value_minor"] is None for row in rows)
                    paged_query, paged_params = product_query(owner_id=owner, category=category, browse_group=group,
                        q="Synthetic", sort="name", limit=1, offset=1)
                    page = await db.fetch(paged_query, *paged_params)
                    # The helper deliberately returns one sentinel for has_more.
                    assert [str(row["catalogue_id"]) for row in page] == expected[1:3]
                    set_sql, set_params = sets_query(owner_id=owner, system_code=SYSTEMS[category], browse_group=group, limit=80)
                    sets = await db.fetch(set_sql, *set_params)
                    assert sum(row["indexed_count"] for row in sets) == len(expected)
                    assert all(row["card_count"] == row["indexed_count"] for row in sets)
                    assert PRIVATE not in str(sets)
                    checks_count += 3
            for owned, expected in (("owned", [IDS[13]] if owner == OWNER_A else [IDS[14]]),
                                    ("not_owned", [IDS[14]] if owner == OWNER_A else [IDS[13]])):
                query, params = product_query(owner_id=owner, system_code="SPORTS_CARDS", browse_group="TOPPS", owned=owned)
                rows = await db.fetch(query, *params)
                assert {str(row["catalogue_id"]) for row in rows} == {str(item) for item in expected}
                if owned == "owned":
                    assert rows[0]["owned_quantity"] == (2 if owner == OWNER_A else 1)
            query, params = sets_query(owner_id=owner, system_code="SPORTS_CARDS", browse_group="TOPPS", q="shared", limit=1)
            sets = await db.fetch(query, *params)
            assert len(sets) == 1 and sets[0]["total_count"] == 1
            assert sets[0]["indexed_count"] == 2 and sets[0]["owned_count"] == 1
            # PostgreSQL sum(bigint) is numeric; the PGlite JSON transport
            # returns it as text, while native asyncpg returns Decimal.
            assert int(sets[0]["owned_value_minor"]) == (300 if owner == OWNER_A else 900)
            query, params = product_query(owner_id=owner, system_code="SPORTS_CARDS", browse_group="TOPPS",
                keys=["c:" + str(IDS[13]), "c:" + str(IDS[15])], sort="name")
            assert [str(row["catalogue_id"]) for row in await db.fetch(query, *params)] == [str(IDS[13])]
            query, params = product_query(owner_id=owner, category="COMICS", browse_group="INDIE", q="%' OR true --")
            assert not await db.fetch(query, *params)
            query, params = sets_query(owner_id=owner, system_code="COMICS", browse_group="INDIE", q="%' OR true --")
            assert not await db.fetch(query, *params)
    # SQL/RLS denial independently of the API auth dependency.
    async with authorized(db, None):
        query, params = product_query(owner_id=OWNER_A, category="MANGA", browse_group="SHONEN")
        assert not await db.fetch(query, *params)
    assert await db.fetchval("select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i") == inventory_before
    print(f"PASS: {checks_count} real PostgreSQL group/page/set parity checks; literal search, mixed saved identities, owner RLS, private-fact exclusion, release/review gates, and unchanged inventory")


async def main(pglite=False):
    if pglite:
        db = await PGliteConnection.open()
    else:
        dsn = os.environ["CATALOGUE_BROWSE_GROUPS_TEST_DSN"]
        parsed = urlsplit(dsn)
        assert parsed.hostname in ("localhost", "127.0.0.1") and parsed.path == "/catalogue_browse_groups_test", "Refusing a non-disposable database"
        db = await asyncpg.connect(dsn, server_settings={"statement_timeout": "15000", "TimeZone": "UTC"})
        await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), "Refusing a nonempty database"
        await checks(db)
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pglite", action="store_true")
    asyncio.run(main(parser.parse_args().pglite))
