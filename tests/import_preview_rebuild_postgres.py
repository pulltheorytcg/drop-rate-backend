"""Real PG17, restricted role and production handlers; synthetic imports only.

IMPORT_REBUILD_TEST_DSN must target loopback/import_preview_rebuild_test. This
reuses the existing import fixture's relevant tables/grants, applies the real
founder-authority, intake and rebuild migrations, and uses the production SQL
audit trigger. It does not connect to Supabase or replay unrelated migrations.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app import imports, import_review
from app.db import _init_connection, user_connection
from app.import_inventory import lock_import_owner
from owner_auto_import_postgres import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = "tcg_private.replace_import_preview(uuid,uuid,uuid,integer,text,text,integer,integer,jsonb,jsonb)"
REPLACE_SQL = "select tcg_private.replace_import_preview($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)"


def csv_payload(marker, *, corrected=False):
    return imports.ImportPreviewRequest(
        filename="original.csv", adapter="GENERIC_CSV",
        content=("Name,CorrectName,Game,Set,Number,Language,Quantity,AlternateQty,Condition,Marker\n"
                 f"Wrong Name,Known Card,,Synthetic Set,001,,2,3,Near Mint,{marker}\n"),
        default_game="Pokemon" if corrected else "Wrong Game",
        default_language="English" if corrected else "Japanese",
        column_mapping={"name": "CorrectName", "quantity": "AlternateQty"} if corrected else {},
    )


def corrected(payload, version, **changes):
    return imports.ImportPreviewRebuildRequest(**{
        **payload.model_dump(), "version": version, "default_game": "Pokemon",
        "default_language": "English", "column_mapping": {"name": "CorrectName", "quantity": "AlternateQty"},
        **changes,
    })


def collectr_payload(marker, quantity, *, other=True):
    content = ("Portfolio Name,Category,Product Name,Set,Card Number,Rarity,Variance,Quantity,Card Condition,Language,Grade,Average Cost Paid\n"
               f"{marker},Pokemon,Known Card,Synthetic Set,001,C,Normal,{quantity},Near Mint,English,Ungraded,\n")
    if other:
        content += f"{marker},Pokemon,Other Card,Synthetic Set,002,C,Normal,1,Near Mint,English,Ungraded,\n"
    return imports.ImportPreviewRequest(filename="collection.csv", adapter="COLLECTR", content=content)


async def expect_http(awaitable, status):
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status, (status, error.status_code, error.detail)
    else:
        raise AssertionError(f"Expected HTTP {status}")


async def expect_sql(awaitable, codes):
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert error.sqlstate in set(codes), (error.sqlstate, type(error).__name__, str(error))
    else:
        raise AssertionError(f"Expected SQL rejection {codes}")


async def main():
    dsn = os.environ["IMPORT_REBUILD_TEST_DSN"]
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1"} and parsed.path == "/import_preview_rebuild_test", "Disposable local database only"
    db = await asyncpg.connect(dsn)
    await _init_connection(db)
    pool = None
    assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), "Refusing a nonempty application database"
    assert 170000 <= int(await db.fetchval("show server_version_num")) < 180000, "This suite requires real PostgreSQL 17"
    version = await db.fetchval("select version()")
    try:
        await db.execute(SCHEMA)
        await db.execute("create schema auth; create table auth.users(id uuid primary key,email_confirmed_at timestamptz)")
        owner_a, owner_b, owner_c, seller_owner = [uuid4() for _ in range(4)]
        actor_a, actor_b, actor_c, seller_actor = [uuid4() for _ in range(4)]
        for slot, (owner, actor) in enumerate(((owner_a, actor_a), (owner_b, actor_b), (owner_c, actor_c)), 1):
            await db.execute("insert into tcg.owners(id,display_name,owner_type,founder_slot,commission_bps) values($1,'Synthetic Founder','FOUNDER',$2,0)", owner, slot)
            await db.execute("insert into auth.users values($1,now())", actor)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'PLATFORM_ADMIN')", actor, owner)
        await db.execute("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,'Synthetic Seller','CONSIGNOR',1000)", seller_owner)
        await db.execute("insert into auth.users values($1,now())", seller_actor)
        await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')", seller_actor, seller_owner)
        for name in ("20261011154138_owner_incremental_import_intake.sql", "20261002024856_unified_founder_app_access.sql"):
            await db.execute((ROOT / "database/migrations" / name).read_text())
        audit = (ROOT / "database/migrations/202609230006_import_framework.sql").read_text()
        audit = audit[audit.index("create function tcg.audit_import_candidate_change()"):audit.rindex("commit;")]
        await db.execute("drop trigger candidate_audit on tcg.import_candidates")
        await db.execute(audit)
        card_a, card_b = uuid4(), uuid4()
        await db.executemany("""insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
            values($1,$2,'CARD','Pokemon',$3,'Synthetic Set',$4,'Normal','C','English')""", [
            (card_a, "rebuild:known", "Known Card", "001"), (card_b, "rebuild:other", "Other Card", "002")])
        async def setup(connection):
            await connection.execute("set role tcg_api")
        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=6, init=_init_connection, setup=setup, command_timeout=10)
        settings = SimpleNamespace(import_preview_rebuild_enabled=True)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool, settings=settings)),
                                  state=SimpleNamespace(request_id="synthetic-preview-rebuild"))
        a, b, c, seller = [SimpleNamespace(user_id=actor) for actor in (actor_a, actor_b, actor_c, seller_actor)]
        source = csv_payload("primary")
        initial = await imports.preview_import(source, request, a)
        batch_id = UUID(initial["batch_id"])

        async def snapshot(batch_id):
            return (await db.fetchrow("select * from tcg.import_batches where id=$1", batch_id),
                    await db.fetch("select * from tcg.import_candidates where batch_id=$1 order by source_row", batch_id))
        original = await snapshot(batch_id)
        migration = next((ROOT / "database/migrations").glob("*_founder_import_preview_rebuild.sql")).read_text()
        await db.execute(migration)
        await db.execute(migration)
        assert original == await snapshot(batch_id), "Migration rewrote a pre-existing preview"
        assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.import_candidates','DELETE')")
        assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.import_batches','UPDATE')")
        for column in ("adapter", "warnings", "physical_units", "source", "filename", "source_sha256", "owner_id"):
            assert not await db.fetchval("select has_column_privilege('tcg_api','tcg.import_batches',$1,'UPDATE')", column)
        for role in ("anon", "authenticated"):
            assert not await db.fetchval("select has_function_privilege($1,$2,'EXECUTE')", role, FUNCTION)
        capability = await db.fetchrow("select prosecdef,proconfig,pg_get_userbyid(proowner) as owner from pg_proc where oid=$1::regprocedure", FUNCTION)
        assert capability["prosecdef"] and capability["owner"] == "postgres" and "search_path=pg_catalog" in capability["proconfig"]
        async def restricted(statement, *args, actor=actor_a):
            async with user_connection(pool, actor, "synthetic-direct-capability") as conn:
                return await conn.fetchval(statement, *args)
        await expect_sql(restricted("delete from tcg.import_candidates where batch_id=$1", batch_id), {"42501"})
        await expect_sql(restricted("update tcg.import_batches set adapter='HOLODEX' where id=$1", batch_id), {"42501"})

        # Reproduce the actual dead end, then correct it without a new batch.
        await expect_http(imports.preview_import(source, request, a), 409)
        row_id = original[1][0]["id"]
        skipped = await import_review.skip_import_candidate(batch_id, row_id,
                    import_review.ImportCandidateSkipRequest(version=1), request, a)
        current_version = skipped["version"]
        corrected_source = corrected(source, current_version, filename="renamed-copy.tsv")
        result = await imports.rebuild_import_preview(batch_id, corrected_source, request, a)
        rebuilt = await snapshot(batch_id)
        assert result["version"] == current_version + 1 and result["created_count"] == 0
        assert result["rebuilt"] and result["review_edits_reset"] and result["rebuild_enabled"]
        assert result["ready_units"] == 3 and result["review_rows"] == 0 and result["skipped_rows"] == 0
        assert rebuilt[0]["physical_units"] == 3 and rebuilt[0]["filename"] == "original.csv"
        for key in ("id", "owner_id", "source", "source_sha256", "source_rows", "filename", "created_at"):
            assert rebuilt[0][key] == original[0][key], key
        assert rebuilt[1][0]["id"] != row_id and rebuilt[1][0]["status"] == "READY"
        assert rebuilt[1][0]["raw_record"] == original[1][0]["raw_record"]
        normalized = rebuilt[1][0]["normalized_record"]
        assert (normalized["name"], normalized["game"], normalized["language"], normalized["quantity"]) == ("Known Card", "Pokemon", "English", 3)
        assert await db.fetchval("select count(*) from tcg.inventory_items") == 0
        assert await db.fetchval("select count(*) from tcg.catalogue_products") == 2
        assert await db.fetchval("select count(*) from tcg.fixture_committed_events") == 0
        assert await db.fetchval("select count(*) from tcg.audit_events where action='DELETE' and entity_id=$1 and actor=$2 and request_id='synthetic-preview-rebuild'", row_id, str(actor_a)) == 1
        await expect_http(imports.rebuild_import_preview(batch_id, corrected_source, request, a), 409)
        await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"], content=source.content + "\n"), request, a), 409)
        await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"]), request, b), 404)
        await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"]), request, seller), 403)
        assert rebuilt == await snapshot(batch_id)

        # Direct callers cannot use the definer capability to cross owner/actor
        # boundaries, replace source evidence, add committed rows or omit rows.
        async def call_args(target, payload, actor=actor_a, owner=owner_a):
            async with user_connection(pool, actor, "synthetic-build") as conn:
                own = await imports._owner(conn)
                preview = await imports._build_preview(conn, own, payload, imports._parse_preview_source(payload))
            batch = await db.fetchrow("select * from tcg.import_batches where id=$1", target)
            return [actor, owner, target, batch["version"], batch["source_sha256"], preview["adapter"],
                    preview["source_rows"], preview["physical_units"], preview["warnings"], jsonable_encoder(preview["candidates"])]
        args = await call_args(batch_id, corrected(source, result["version"]))
        async def capability_call(values, actor=actor_a):
            return await restricted(REPLACE_SQL, *values, actor=actor)
        for index, value, code in ((0, actor_b, "42501"), (1, owner_b, "42501"),
                                   (2, uuid4(), "P0002"), (3, 1, "55000"), (4, "b" * 64, "55000"),
                                   (6, 2, "22023"), (7, 5, "22023")):
            invalid = copy.deepcopy(args); invalid[index] = value
            await expect_sql(capability_call(invalid), {code})
        for change in ("raw", "committed", "duplicate", "unknown_key", "missing_source"):
            invalid = copy.deepcopy(args)
            if change == "raw": invalid[9][0]["raw_record"]["Name"] = "Rewritten source"
            if change == "committed": invalid[9][0]["status"] = "COMMITTED"
            if change == "duplicate": invalid[9].append(copy.deepcopy(invalid[9][0]))
            if change == "unknown_key": invalid[9][0]["owner_id"] = str(owner_b)
            if change == "missing_source": invalid[9][0]["source_row"] = 3
            await expect_sql(capability_call(invalid), {"22023"})
        await db.execute("update tcg.founder_app_accounts set active=false where user_id=$1", actor_a)
        await expect_sql(capability_call(args), {"42501"})
        await db.execute("update tcg.founder_app_accounts set active=true where user_id=$1", actor_a)
        await expect_sql(capability_call(args, actor=seller_actor), {"42501"})
        assert rebuilt == await snapshot(batch_id)

        # The failing FK is checked during INSERT, after DELETE has run. Both
        # replacement and audit writes must roll back as one SQL statement.
        audit_before = await db.fetchval("select count(*) from tcg.audit_events")
        invalid = copy.deepcopy(args); invalid[9][0]["catalogue_id"] = str(uuid4())
        await expect_sql(capability_call(invalid), {"23503"})
        assert rebuilt == await snapshot(batch_id)
        assert audit_before == await db.fetchval("select count(*) from tcg.audit_events")
        try:
            async with user_connection(pool, actor_a, "synthetic-rollback") as conn:
                await conn.fetchval(REPLACE_SQL, *args)
                raise RuntimeError("Deliberate outer transaction rollback")
        except RuntimeError:
            pass
        assert rebuilt == await snapshot(batch_id)

        # Every historical/automatic state is independently blocked in SQL,
        # including a manually reset flag after partial automatic processing.
        for field, value in (("status", "CANCELLED"), ("status", "COMMITTED"),
                             ("automatic_intake", True), ("last_auto_apply_version", 1),
                             ("committed_at", "2026-10-27T12:00:00Z")):
            if field == "committed_at":
                await db.execute("update tcg.import_batches set committed_at='2026-10-27T12:00:00Z' where id=$1", batch_id)
            else:
                await db.execute(f"update tcg.import_batches set {field}=$2 where id=$1", batch_id, value)
            await expect_sql(capability_call(args), {"55000"})
            await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"]), request, a), 409)
            await db.execute(f"update tcg.import_batches set {field}=$2 where id=$1", batch_id, rebuilt[0][field])
        await db.execute("update tcg.import_candidates set status='COMMITTED' where batch_id=$1", batch_id)
        await expect_sql(capability_call(args), {"55000"})
        await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"]), request, a), 409)
        await db.execute("update tcg.import_candidates set status='READY' where batch_id=$1", batch_id)
        fake_copy = uuid4()
        await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,import_batch_id) values($1,$2,$3,$4,$5)",
                         fake_copy, "FIXTURE-LEGACY-COPY", owner_a, card_a, batch_id)
        await expect_sql(capability_call(args), {"55000"})
        await expect_http(imports.rebuild_import_preview(batch_id, corrected(source, result["version"]), request, a), 409)
        await db.execute("delete from tcg.inventory_items where id=$1", fake_copy)

        # Collectr recalculates against the latest committed baseline while the
        # owner lock is held. Changing adapter can remove synthetic missing rows.
        base = await imports.preview_import(collectr_payload("base", 2), request, c)
        await imports.commit_import_batch(UUID(base["batch_id"]), imports.ImportCommitRequest(version=1), request, c)
        target_source = collectr_payload("target", 4, other=False)
        target = await imports.preview_import(target_source, request, c)
        target_id = UUID(target["batch_id"])
        assert len(target["candidates"]) == 2 and target["candidates"][0]["quantity"] == 2
        newer = await imports.preview_import(collectr_payload("newer", 3), request, c)
        await imports.commit_import_batch(UUID(newer["batch_id"]), imports.ImportCommitRequest(version=1), request, c)
        stock_before = await db.fetch("select * from tcg.inventory_items order by id")
        refreshed = await imports.rebuild_import_preview(target_id,
            imports.ImportPreviewRebuildRequest(**target_source.model_dump(), version=1), request, c)
        assert refreshed["candidates"][0]["quantity"] == 1
        assert refreshed["candidates"][0]["normalized_record"]["collectr_baseline_batch_id"] == newer["batch_id"]
        changed_adapter = await imports.rebuild_import_preview(target_id,
            imports.ImportPreviewRebuildRequest(**{**target_source.model_dump(), "adapter": "GENERIC_CSV"}, version=2), request, c)
        after_adapter = await snapshot(target_id)
        assert len(changed_adapter["candidates"]) == len(after_adapter[1]) == 1
        assert after_adapter[0]["source"] == "COLLECTR" and after_adapter[0]["adapter"] == "GENERIC_CSV"
        assert stock_before == await db.fetch("select * from tcg.inventory_items order by id")
        assert await db.fetchval("select count(*) from tcg.catalogue_products") == 2

        # A real Collectr-sized stored preview can have missing-source rows
        # beyond the 5,000-row display cap. Reopening must expose full totals,
        # even when every displayed row is READY or SKIPPED.
        large_id = uuid4()
        await db.execute("""insert into tcg.import_batches(
            id,owner_id,source,source_sha256,source_rows,physical_units,filename,adapter,status)
            values($1,$2,'COLLECTR',$3,5000,5006,'large-synthetic.csv','COLLECTR','PREVIEW')""",
            large_id, owner_b, "f" * 64)
        await db.execute("""insert into tcg.import_candidates(
            batch_id,owner_id,source_row,quantity,raw_record,normalized_record,catalogue_id,status,issues)
            select $1,$2,n,case when n=2 then 7 else 1 end,'{}'::jsonb,
                   jsonb_build_object('name','Synthetic summary row','quantity',case when n=2 then 7 else 1 end),
                   $3,case when n=2 then 'READY' when n>5001 then 'REVIEW' else 'SKIPPED' end,
                   case when n>5001 then '["collectr_identity_missing_from_snapshot"]'::jsonb else '[]'::jsonb end
            from generate_series(2,5003) n""", large_id, owner_b, card_b)
        reopened = await imports.get_import_batch(large_id, request, b)
        assert len(reopened["candidates"]) == 5000 and reopened["preview_truncated"]
        assert not any(row["status"] == "REVIEW" for row in reopened["candidates"])
        assert reopened["summary"] == {"candidate_count": 5002, "ready_units": 7, "review_rows": 2, "skipped_rows": 4999}
        await expect_http(imports.get_import_batch(large_id, request, a), 404)

        # Two sessions with the same version serialize on the established owner
        # advisory lock; only one rebuild succeeds. The loser sees the new version.
        race_source = csv_payload("two-rebuilds", corrected=True)
        race = await imports.preview_import(race_source, request, a)
        race_id = UUID(race["batch_id"])
        outcomes = await asyncio.gather(*[
            imports.rebuild_import_preview(race_id, corrected(race_source, 1), request, a) for _ in range(2)
        ], return_exceptions=True)
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1, outcomes
        loser = next(outcome for outcome in outcomes if isinstance(outcome, Exception))
        assert isinstance(loser, HTTPException) and loser.status_code == 409
        assert (await snapshot(race_id))[0]["version"] == 2
        assert await db.fetchval("select count(*) from tcg.inventory_items where import_batch_id=$1", race_id) == 0

        # Commit and rebuild use the same serialization boundary. Whichever wins
        # consumes version 1; the other is stale, and copies are added at most once.
        commit_source = csv_payload("commit-race", corrected=True)
        commit_preview = await imports.preview_import(commit_source, request, a)
        commit_id = UUID(commit_preview["batch_id"])
        outcomes = await asyncio.gather(
            imports.commit_import_batch(commit_id, imports.ImportCommitRequest(version=1), request, a),
            imports.rebuild_import_preview(commit_id, corrected(commit_source, 1), request, a),
            return_exceptions=True,
        )
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1, outcomes
        loser = next(outcome for outcome in outcomes if isinstance(outcome, Exception))
        assert isinstance(loser, HTTPException) and loser.status_code == 409
        current = (await snapshot(commit_id))[0]
        if current["status"] == "PREVIEW":
            committed = await imports.commit_import_batch(commit_id, imports.ImportCommitRequest(version=current["version"]), request, a)
            assert committed["created_count"] == 3
        assert await db.fetchval("select count(*) from tcg.inventory_items where import_batch_id=$1", commit_id) == 3
        current = (await snapshot(commit_id))[0]
        retry = await imports.commit_import_batch(commit_id, imports.ImportCommitRequest(version=current["version"]), request, a)
        assert retry["created_count"] == 0 and retry["replayed"]
        await expect_http(imports.rebuild_import_preview(commit_id, corrected(commit_source, current["version"]), request, a), 409)

        # The capability itself also acquires the owner lock; a direct caller
        # cannot skip coordination by avoiding the HTTP handler.
        async with user_connection(pool, actor_a, "synthetic-lock-holder") as held:
            await lock_import_owner(held, owner_a)
            await expect_sql(capability_call(args), {"55P03"})
        assert rebuilt == await snapshot(batch_id)
        print(json.dumps({
            "status": "PASS", "postgres": version.split(",")[0],
            "proofs": ["restricted grants preserved", "real founder authority", "owner isolation",
                       "same-file rebuild and review reset", "source evidence immutable", "fresh Collectr baseline",
                       "synthetic row removal", "full persisted totals beyond 5000 display rows",
                       "no inventory/catalogue writes during rebuild",
                       "FK and outer-transaction rollback", "two-session stale-version race",
                       "commit/rebuild serialization", "automatic/committed rejection", "private capability lock timeout"],
        }))
    finally:
        if pool is not None:
            await pool.close()
        await db.execute("drop schema if exists tcg_private cascade; drop schema if exists tcg cascade; drop schema if exists auth cascade")
        for role in ("tcg_api", "anon", "authenticated"):
            await db.execute(f"drop role if exists {role}")
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
