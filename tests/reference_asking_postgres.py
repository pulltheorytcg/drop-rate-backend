"""Disposable PostgreSQL contract test; refuses remote or nonempty databases.

Run with ASKING_TEST_DSN=postgresql://...@127.0.0.1:5432/asking_test.
This test makes no provider requests and never connects to production.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
ADMIN = UUID("00000000-0000-0000-0000-000000000001")
SECOND_ADMIN = UUID("00000000-0000-0000-0000-000000000003")
OWNER = UUID("00000000-0000-0000-0000-000000000002")
FIELDS = (
    "provider", "system_code", "language", "provider_id", "snapshot_id",
    "reference_identity", "estimate_minor", "estimate_high_minor", "currency",
    "listing_count", "seller_count", "observed_at", "checked_at", "expires_at",
    "method_version", "evidence",
)
INSERT_HISTORY = (
    "insert into tcg.reference_asking_history(" + ",".join(FIELDS) + ",run_id,actor_user_id) "
    "values(" + ",".join(f"${i}" for i in range(1, len(FIELDS) + 3)) + ")"
)
UPSERT_CACHE = (
    "insert into tcg.reference_asking_prices(" + ",".join(FIELDS) + ") "
    "select " + ",".join(FIELDS) + " from tcg.reference_asking_history where snapshot_id=$1 "
    "on conflict(provider,system_code,language,provider_id) do update set "
    + ",".join(f"{field}=excluded.{field}" for field in FIELDS[4:])
)


async def codec(db):
    await db.set_type_codec("jsonb", schema="pg_catalog", encoder=json.dumps,
                            decoder=json.loads, format="text")


async def actor(db, who=ADMIN):
    await db.execute("set role tcg_api")
    await db.execute("select set_config('tcg.user_id',$1,false)", str(who))


async def rejected(db, sql, args=(), errors=(asyncpg.PostgresError,), message=None):
    try:
        async with db.transaction():
            await db.execute(sql, *args)
    except errors as exc:
        if message:
            assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError("Unexpectedly accepted invalid database operation")


def evidence(run_id, *, snapshot_id=None, amount=1000, observed=None, **changes):
    observed = observed or datetime.now(timezone.utc) - timedelta(minutes=2)
    values = {
        "provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "English",
        "provider_id": "fixture-001", "snapshot_id": snapshot_id or uuid4(),
        "reference_identity": {"name": "Pineco", "set_id": "fixture", "card_number": "001",
                               "set_name": "Fixture", "finish": "Normal", "rarity": "Common"},
        "estimate_minor": amount, "estimate_high_minor": amount + 200, "currency": "GBP",
        "listing_count": 3, "seller_count": 3, "observed_at": observed,
        "checked_at": observed + timedelta(seconds=1), "expires_at": observed + timedelta(days=3),
        "method_version": "EBAY_UK_RAW_ASK_V1",
        "evidence": {"source": "EBAY_OFFICIAL_BROWSE", "shipping_basis": "ITEM_PLUS_SHIPPING",
                     "shipping_context": "CONFIGURED_SHOP_POSTCODE_BENCHMARK",
                     "condition": "Near Mint", "finish": "Normal", "confidence": "LOW",
                     "physical_valuation_eligible": False},
        "run_id": run_id, "actor_user_id": ADMIN,
    }
    values.update(changes)
    return values


async def history(db, item):
    await db.execute(INSERT_HISTORY, *(item[field] for field in FIELDS),
                     item["run_id"], item["actor_user_id"])


async def main():
    dsn = os.environ["ASKING_TEST_DSN"]
    target = urlsplit(dsn)
    assert target.hostname in {"127.0.0.1", "localhost"} and target.path == "/asking_test", \
        "Only a disposable local asking_test database is allowed"
    db = await asyncpg.connect(dsn)
    await codec(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), \
            "Refusing to alter a nonempty application database"
        await db.execute("""
          create schema tcg;
          do $$ declare r text; begin
            foreach r in array array['tcg_api','anon','authenticated','service_role'] loop
              if not exists(select 1 from pg_roles where rolname=r) then
                execute format('create role %I nologin nobypassrls',r);
              end if;
            end loop;
          end $$;
          create function tcg.current_user_id() returns uuid language sql stable as
            $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean language sql stable as
            $$select tcg.current_user_id() in
                ('00000000-0000-0000-0000-000000000001'::uuid,
                 '00000000-0000-0000-0000-000000000003'::uuid)$$;
          create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,
            primary key(provider,system_code,language,set_id));
          create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,
            set_id text,name text,card_number text,finish text,rarity text,
            primary key(provider,system_code,language,provider_id));
          create table tcg.audit_events(id bigint generated always as identity primary key,
            occurred_at timestamptz not null default clock_timestamp(),actor text not null,
            request_id text,action text not null,entity_type text not null,entity_id uuid not null,
            old_values jsonb,new_values jsonb);
          insert into tcg.reference_sets values('TCGdex','POKEMON_TCG','English','fixture','Fixture');
          insert into tcg.reference_cards values
            ('TCGdex','POKEMON_TCG','English','fixture-001','fixture','Pineco','001','Normal','Common');
          grant usage on schema tcg to tcg_api;
          grant select on tcg.reference_cards,tcg.reference_sets to tcg_api;
        """)
        migrations = sorted((ROOT / "database/migrations").glob("*_reference_asking_prices.sql"))
        assert len(migrations) <= 1, "Ambiguous asking-price migration"
        sql_path = migrations[0] if migrations else ROOT / "database/proposals/reference_asking_prices.sql"
        await db.execute(sql_path.read_text(encoding="utf-8"))

        for table in ("reference_asking_runs", "reference_asking_history", "reference_asking_prices"):
            assert await db.fetchval("select relrowsecurity and relforcerowsecurity from pg_class where oid=$1::regclass",
                                     "tcg." + table)
            for role in ("anon", "authenticated", "service_role"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await db.fetchval("select has_table_privilege($1,$2,$3)", role, "tcg." + table, privilege)
        assert not await db.fetchval("select has_table_privilege('tcg_api','tcg.audit_events','INSERT')")

        await actor(db)
        run_id = await db.fetchval("insert into tcg.reference_asking_runs(actor_user_id) values($1) returning id", ADMIN)
        assert await db.fetchval("select tcg.reserve_reference_asking_request($1)", run_id) == 1
        other = await asyncpg.connect(dsn)
        try:
            await actor(other)
            assert await other.fetchval("select requests from tcg.reference_asking_runs where id=$1", run_id) == 1, \
                "Reservation was not durably committed before provider I/O"
        finally:
            await other.close()

        first = evidence(run_id)
        async with db.transaction():
            await history(db, first)
            await db.execute(UPSERT_CACHE, first["snapshot_id"])
        assert await db.fetchval("select estimate_minor from tcg.reference_asking_prices") == 1000
        await db.execute("reset role")
        audit = await db.fetchrow("select actor,entity_id,new_values from tcg.audit_events")
        assert audit["actor"] == str(ADMIN) and audit["entity_id"] == first["snapshot_id"]
        assert audit["new_values"]["estimate_minor"] == 1000
        await actor(db)

        # Earlier committed history cannot justify a later cache-only change.
        orphan = evidence(run_id)
        await history(db, orphan)
        await rejected(db, UPSERT_CACHE, (orphan["snapshot_id"],),
                       message="ASKING_PRICE_REQUIRES_MATCHING_TRANSACTION_HISTORY")
        await rejected(db, "update tcg.reference_asking_prices set estimate_minor=999",
                       message="ASKING_PRICE_REQUIRES_MATCHING_TRANSACTION_HISTORY")
        await rejected(db, "delete from tcg.reference_asking_history", errors=(asyncpg.InsufficientPrivilegeError,))
        await rejected(db, "update tcg.reference_asking_history set estimate_minor=999", errors=(asyncpg.InsufficientPrivilegeError,))

        # Even a different platform admin cannot claim another actor's snapshot.
        async with db.transaction():
            cross_actor = evidence(run_id)
            await history(db, cross_actor)
            await actor(db, SECOND_ADMIN)
            await rejected(db, UPSERT_CACHE, (cross_actor["snapshot_id"],),
                           message="ASKING_PRICE_REQUIRES_MATCHING_TRANSACTION_HISTORY")
            await actor(db)
        other_run = await db.fetchval("insert into tcg.reference_asking_runs(actor_user_id) values($1) returning id", ADMIN)
        unreserved = evidence(other_run)
        await rejected(db, INSERT_HISTORY,
                       tuple(unreserved[field] for field in FIELDS) + (other_run, ADMIN),
                       message="ASKING_HISTORY_ACTIVE_ADMIN_RUN_REQUIRED")

        # Invalid sample counts, basis, future/stale timestamps and changed
        # identities fail in the database rather than becoming visible prices.
        invalids = [
            {"listing_count": 2}, {"seller_count": 2}, {"seller_count": 4},
            {"estimate_minor": 0}, {"estimate_high_minor": 999}, {"currency": "USD"},
            {"expires_at": first["observed_at"] + timedelta(days=4)},
            {"expires_at": first["observed_at"]},
            {"observed_at": datetime.now(timezone.utc) + timedelta(hours=1)},
            {"reference_identity": {**first["reference_identity"], "name": "Changed"}},
            {"evidence": {**first["evidence"], "source": "EBAY_SOLD"}},
            {"evidence": {**first["evidence"], "shipping_context": "EXACT_CUSTOMER_QUOTE"}},
            {"evidence": {k: v for k, v in first["evidence"].items() if k != "shipping_context"}},
            {"evidence": {**first["evidence"], "physical_valuation_eligible": True}},
            {"evidence": {k: v for k, v in first["evidence"].items() if k != "confidence"}},
            {"evidence": {**first["evidence"], "unbounded": "x" * 32768}},
        ]
        for changes in invalids:
            item = evidence(run_id, **changes)
            await rejected(db, INSERT_HISTORY, tuple(item[field] for field in FIELDS) + (run_id, ADMIN))

        before_history = await db.fetchval("select count(*) from tcg.reference_asking_history")
        rolled = evidence(run_id, amount=2000, observed=first["observed_at"] + timedelta(seconds=20))
        transaction = db.transaction()
        await transaction.start()
        await history(db, rolled)
        await db.execute(UPSERT_CACHE, rolled["snapshot_id"])
        await transaction.rollback()
        assert await db.fetchval("select count(*) from tcg.reference_asking_history") == before_history
        assert await db.fetchval("select estimate_minor from tcg.reference_asking_prices") == 1000
        await db.execute("reset role")
        assert await db.fetchval("select count(*) from tcg.audit_events") == 1
        await actor(db)

        replacement = evidence(run_id, amount=2000, observed=first["observed_at"] + timedelta(seconds=30))
        async with db.transaction():
            await history(db, replacement)
            await db.execute(UPSERT_CACHE, replacement["snapshot_id"])
        assert await db.fetchval("select estimate_minor from tcg.reference_asking_prices") == 2000
        async with db.transaction():
            mismatched = evidence(run_id, amount=2100, observed=first["observed_at"] + timedelta(seconds=40))
            await history(db, mismatched)
            bad_upsert = UPSERT_CACHE.replace(
                "estimate_minor=excluded.estimate_minor", "estimate_minor=excluded.estimate_minor+1")
            await rejected(db, bad_upsert, (mismatched["snapshot_id"],),
                           message="ASKING_PRICE_REQUIRES_MATCHING_TRANSACTION_HISTORY")
        async with db.transaction():
            older = evidence(run_id, observed=first["observed_at"])
            await history(db, older)
            await rejected(db, UPSERT_CACHE, (older["snapshot_id"],),
                           message="ASKING_PRICE_IDENTITY_OR_FRESHNESS_REGRESSION")

        # Non-admin authenticated backend readers may see labelled estimates;
        # they cannot create runs/history, replace prices or reset request use.
        await actor(db, OWNER)
        assert await db.fetchval("select count(*) from tcg.reference_asking_prices") == 1
        assert await db.fetchval("select count(*) from tcg.reference_asking_runs") == 0
        await rejected(db, "insert into tcg.reference_asking_runs(actor_user_id) values($1)", (OWNER,),
                       errors=(asyncpg.InsufficientPrivilegeError,))
        await rejected(db, "select tcg.reserve_reference_asking_request($1)", (run_id,),
                       errors=(asyncpg.InsufficientPrivilegeError,))
        await db.execute("select set_config('tcg.user_id','',false)")
        assert await db.fetchval("select count(*) from tcg.reference_asking_prices") == 0
        await actor(db)
        await rejected(db, "update tcg.reference_asking_runs set requests=0 where id=$1", (run_id,),
                       message="ASKING_REQUEST_COUNTER_MUST_INCREMENT_BY_ONE")
        await rejected(db, "update tcg.reference_asking_runs set requests=requests+2 where id=$1", (run_id,),
                       message="ASKING_REQUEST_COUNTER_MUST_INCREMENT_BY_ONE")

        # Consume all but one request, then race two connections. Exactly one
        # reservation may commit; starting a fresh run cannot reset the day.
        await db.execute("""do $$ declare n integer; begin for n in 1..498 loop
          perform tcg.reserve_reference_asking_request('%s'::uuid); end loop; end $$""" % run_id)
        assert await db.fetchval("select sum(requests) from tcg.reference_asking_runs") == 499
        left, right = await asyncpg.connect(dsn), await asyncpg.connect(dsn)
        try:
            await actor(left)
            await actor(right)
            attempts = await asyncio.gather(
                left.fetchval("select tcg.reserve_reference_asking_request($1)", run_id),
                right.fetchval("select tcg.reserve_reference_asking_request($1)", other_run),
                return_exceptions=True,
            )
            assert sum(isinstance(value, int) for value in attempts) == 1, attempts
            assert any("ASKING_DAILY_REQUEST_BUDGET_EXHAUSTED" in str(value) for value in attempts), attempts
        finally:
            await left.close()
            await right.close()
        assert await db.fetchval("select sum(requests) from tcg.reference_asking_runs") == 500
        restarted = await db.fetchval("insert into tcg.reference_asking_runs(actor_user_id) values($1) returning id", ADMIN)
        await rejected(db, "select tcg.reserve_reference_asking_request($1)", (restarted,),
                       message="ASKING_DAILY_REQUEST_BUDGET_EXHAUSTED")
        await db.execute("update tcg.reference_asking_runs set status='COMPLETE',finished_at=clock_timestamp() where id=$1", run_id)
        await rejected(db, "select tcg.reserve_reference_asking_request($1)", (run_id,),
                       errors=(asyncpg.InsufficientPrivilegeError,))
        await rejected(db, "update tcg.reference_asking_runs set status='RUNNING',finished_at=null where id=$1", (run_id,),
                       message="ASKING_RUN_IDENTITY_OR_FINAL_STATE_IMMUTABLE")

        # History is append-only even for its database owner, not merely an
        # application-role privilege convention.
        await db.execute("reset role")
        await rejected(db, "update tcg.reference_asking_history set estimate_minor=1",
                       errors=(asyncpg.InsufficientPrivilegeError,), message="ASKING_HISTORY_IS_APPEND_ONLY")
        await rejected(db, "delete from tcg.reference_asking_history",
                       errors=(asyncpg.InsufficientPrivilegeError,), message="ASKING_HISTORY_IS_APPEND_ONLY")
    finally:
        await db.close()
    print("PASS: asking cache/history atomicity, identity/basis guards, audit, RLS, UTC durable budget and concurrency")


if __name__ == "__main__":
    asyncio.run(main())
