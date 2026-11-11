"""Native RLS contract for the query-level owner identity optimization.

Runs only against a fresh, disposable local Postgres database. Never use a
production DSN: the setup creates test roles, schemas, policies and rows.
"""

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
NEW_MIGRATION = MIGRATIONS / "20261102001200_optimize_owner_identity_rls_initplan.sql"
POLICIES = {
    "action_required_items": (
        "own_action_required_access",
        "20260928211713_import_enrichment_action_queue.sql",
    ),
    "import_enrichment_items": (
        "own_enrichment_access",
        "20260928211713_import_enrichment_action_queue.sql",
    ),
    "media_assets": (
        "own_asset_writes",
        "20260925154423_media_assets_registry.sql",
    ),
}
READABLE_POLICY_FILE = "20260925154423_media_assets_registry.sql"


def original_policy(table: str, name: str, filename: str) -> str:
    source = (MIGRATIONS / filename).read_text()
    match = re.search(
        rf"\bcreate\s+policy\s+{name}\s+on\s+tcg\.{table}\b[^;]*;",
        source,
        flags=re.IGNORECASE,
    )
    assert match, f"Original policy {table}.{name} not found"
    return match.group()


async def main() -> None:
    dsn = os.environ["OWNER_RLS_TEST_DSN"]
    parsed = urlsplit(dsn)
    assert parsed.hostname in ("localhost", "127.0.0.1")
    assert parsed.path == "/owner_rls_test"
    db = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        assert not await db.fetchval(
            "select exists(select 1 from pg_namespace where nspname = 'tcg')"
        ), "Fresh disposable database only"

        await db.execute("create role tcg_api nologin nosuperuser nobypassrls")
        await db.execute("create schema tcg")
        await db.execute("grant usage on schema tcg to tcg_api")
        await db.execute("""
            create table tcg.owner_memberships (
                owner_id uuid not null, user_id uuid not null, active boolean not null
            );
            create table tcg.action_required_items (id uuid primary key, owner_id uuid not null);
            create table tcg.import_enrichment_items (id uuid primary key, owner_id uuid not null);
            create table tcg.media_assets (
                id uuid primary key, owner_id uuid not null,
                scope text not null default 'INVENTORY_ITEM'
            );
            alter table tcg.owner_memberships enable row level security;
            alter table tcg.owner_memberships force row level security;
            create policy member_read on tcg.owner_memberships
                for select to tcg_api using (
                    user_id = nullif(current_setting('tcg.user_id', true), '')::uuid
                    and active
                );
            grant select on tcg.owner_memberships to tcg_api;
        """)
        for table in POLICIES:
            await db.execute(f"alter table tcg.{table} enable row level security")
            await db.execute(f"alter table tcg.{table} force row level security")
            await db.execute(f"grant select, insert, update on tcg.{table} to tcg_api")
            policy, filename = POLICIES[table]
            await db.execute(original_policy(table, policy, filename))
        await db.execute(
            original_policy("media_assets", "readable_assets", READABLE_POLICY_FILE)
        )

        owners, users = [uuid4(), uuid4()], [uuid4(), uuid4(), uuid4()]
        await db.executemany(
            "insert into tcg.owner_memberships(owner_id,user_id,active) values($1,$2,$3)",
            [(owners[0], users[0], True), (owners[1], users[1], True),
             (owners[0], users[2], False)],
        )
        rows = {table: [uuid4(), uuid4()] for table in POLICIES}
        shared_media = uuid4()
        for table in POLICIES:
            await db.executemany(
                f"insert into tcg.{table}(id,owner_id) values($1,$2)",
                list(zip(rows[table], owners)),
            )
        await db.execute(
            "insert into tcg.media_assets(id,owner_id,scope) values($1,$2,'CANONICAL_CARD')",
            shared_media, owners[1],
        )

        async def visible_for(user: object) -> dict[str, set]:
            async with db.transaction():
                await db.execute("set local role tcg_api")
                if user is not None:
                    await db.execute(
                        "select set_config('tcg.user_id', $1, true)", str(user)
                    )
                return {
                    table: {r["id"] for r in await db.fetch(f"select id from tcg.{table}")}
                    for table in POLICIES
                }

        before = [await visible_for(user) for user in (*users, None)]
        for table in ("action_required_items", "import_enrichment_items"):
            assert before[0][table] == {rows[table][0]}
            assert before[1][table] == {rows[table][1]}
            assert before[2][table] == before[3][table] == set()
        assert before[0]["media_assets"] == {rows["media_assets"][0], shared_media}
        assert before[1]["media_assets"] == {rows["media_assets"][1], shared_media}
        assert before[2]["media_assets"] == before[3]["media_assets"] == {shared_media}

        old_policy_metadata = await db.fetch("""
            select tablename, policyname, cmd, roles
            from pg_policies where schemaname = 'tcg'
              and policyname in (
                'own_action_required_access', 'own_enrichment_access',
                'own_asset_writes', 'readable_assets'
              ) order by tablename, policyname
        """)
        assert len(old_policy_metadata) == 4
        await db.execute(NEW_MIGRATION.read_text())
        assert await db.fetch("""
            select tablename, policyname, cmd, roles
            from pg_policies where schemaname = 'tcg'
              and policyname in (
                'own_action_required_access', 'own_enrichment_access',
                'own_asset_writes', 'readable_assets'
              ) order by tablename, policyname
        """) == old_policy_metadata
        assert [await visible_for(user) for user in (*users, None)] == before

        for table in POLICIES:
            async with db.transaction():
                await db.execute("set local role tcg_api")
                await db.execute(
                    "select set_config('tcg.user_id', $1, true)", str(users[0])
                )
                assert await db.execute(
                    f"update tcg.{table} set id=id where id=$1", rows[table][0]
                ) == "UPDATE 1"
                assert await db.execute(
                    f"update tcg.{table} set id=id where id=$1", rows[table][1]
                ) == "UPDATE 0"
                if table == "media_assets":
                    assert await db.execute(
                        "update tcg.media_assets set id=id where id=$1", shared_media
                    ) == "UPDATE 0"  # Readable canonical art is not writable.

            for statement, args in (
                (f"insert into tcg.{table}(id,owner_id) values($1,$2)", (uuid4(), owners[1])),
                (f"update tcg.{table} set owner_id=$1 where id=$2", (owners[1], rows[table][0])),
            ):
                try:
                    async with db.transaction():
                        await db.execute("set local role tcg_api")
                        await db.execute(
                            "select set_config('tcg.user_id', $1, true)",
                            str(users[0]),
                        )
                        await db.execute(statement, *args)
                except asyncpg.InsufficientPrivilegeError:
                    pass
                else:
                    raise AssertionError(f"Cross-owner write accepted on {table}")

        print("Owner RLS InitPlan: policy roles and read/write isolation preserved.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
