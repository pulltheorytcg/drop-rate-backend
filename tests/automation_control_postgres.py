"""Native PG17 control-plane regression; synthetic, disposable loopback DB only.

The early automation_runs baseline is ledger-only in this repository. Its
columns/checks mirror the captured live metadata, with an explicit owner-scoped
fixture policy and a deliberately different unique-index name/order. Owner
visibility, action-required schema/audit, and heartbeat functions use committed
production migrations. No production credentials or records are used.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
import httpx
from fastapi import FastAPI

from app import automation_control as control
from app.automation_dispatcher import signature_headers
from app.db import _init_connection


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
REPAIR = MIGRATIONS / "20261027164716_automation_control_runtime_repair.sql"
FUNCTION = "tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamp with time zone,uuid,uuid,text,text)"
CALL = "select * from tcg_private.record_automation_execution_receipt($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)"
SECRET = "synthetic-native-control-secret-" + "x" * 32
RUNTIME_PASSWORD = "disposable-control-ci-only"
FOUNDER_A = UUID("10000000-0000-4000-8000-000000000001")
FOUNDER_B = UUID("10000000-0000-4000-8000-000000000002")
INACTIVE = UUID("10000000-0000-4000-8000-000000000003")
CONSIGNOR = UUID("10000000-0000-4000-8000-000000000004")
USER_A = UUID("20000000-0000-4000-8000-000000000001")
EXISTING_ALERT = UUID("30000000-0000-4000-8000-000000000001")

SCHEMA = """
create role tcg_api login password 'disposable-control-ci-only';
create role anon; create role authenticated; create role service_role; create role tcg_auditor;
create schema tcg authorization postgres; create schema auth authorization postgres;
create schema tcg_private authorization postgres;
revoke all on schema tcg_private from public,anon,authenticated;
grant usage on schema tcg_private to tcg_api;
grant usage on schema tcg to tcg_api;
create table auth.users(id uuid primary key);
create table tcg.owners(
 id uuid primary key,display_name text not null,owner_type text not null
 check(owner_type in ('FOUNDER','CONSIGNOR')),active boolean not null,
 created_at timestamptz not null default now()
);
create table tcg.owner_memberships(
 id uuid primary key default gen_random_uuid(),owner_id uuid references tcg.owners(id),
 user_id uuid references auth.users(id),active boolean not null,role text not null,
 created_at timestamptz not null default now()
);
create function tcg.current_user_id() returns uuid language sql stable
 as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
grant select on tcg.owners,tcg.owner_memberships to tcg_api;
alter table tcg.owners enable row level security;
alter table tcg.owners force row level security;
create table tcg.automation_runs(
 id uuid primary key default gen_random_uuid(),owner_id uuid not null references tcg.owners(id),
 job_type text not null constraint automation_runs_job_type_check check(job_type='INVENTORY_REVIEW'),
 run_key text not null constraint automation_runs_run_key_check check(length(run_key) between 1 and 255),
 initiated_by text not null default 'AUTOMATION_SERVICE'
 constraint automation_runs_initiated_by_check check(initiated_by='AUTOMATION_SERVICE'),
 result jsonb not null,created_at timestamptz not null default now(),
 constraint fixture_runs_unique unique(owner_id,job_type,run_key)
);
alter table tcg.automation_runs enable row level security;
alter table tcg.automation_runs force row level security;
create policy automation_runs_fixture_admin on tcg.automation_runs for all to postgres
 using(true) with check(true);
create policy automation_runs_fixture_owner on tcg.automation_runs for all to tcg_api
 using(owner_id in (select owner_id from tcg.owner_memberships
   where user_id=tcg.current_user_id() and active))
 with check(owner_id in (select owner_id from tcg.owner_memberships
   where user_id=tcg.current_user_id() and active));
grant select,insert on tcg.automation_runs to tcg_api;
create table tcg.audit_events(
 id uuid primary key default gen_random_uuid(),actor text,request_id text,action text,
 entity_type text,entity_id uuid,old_values jsonb,new_values jsonb,
 created_at timestamptz not null default now()
);
"""


async def expect_sql(awaitable, code: str):
    try:
        await awaitable
    except asyncpg.PostgresError as exc:
        assert exc.sqlstate == code, (type(exc).__name__, exc.sqlstate, code)
        return
    raise AssertionError("Expected SQLSTATE " + code)


def receipt(workflow="runtime-heartbeat", execution="native-1", **changes):
    value = {
        "workflow_key": workflow,
        "workflow_version": "v1",
        "execution_id": execution,
        "status": "FAILED",
        "idempotency_key": f"n8n-error:{workflow}:{execution}",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "owner_id": None,
        "event_id": None,
        "error_code": "SYNTHETIC_FAILURE",
        "error_message": "Synthetic native regression only",
    }
    value.update(changes)
    return value


def receipt_args(value):
    return (
        value["workflow_key"], value["workflow_version"], value["execution_id"],
        value["status"], value["idempotency_key"], datetime.fromisoformat(value["occurred_at"]),
        UUID(value["owner_id"]) if value.get("owner_id") else None,
        UUID(value["event_id"]) if value.get("event_id") else None,
        value.get("error_code"), value.get("error_message"),
    )


async def main():
    dsn = os.environ["AUTOMATION_CONTROL_TEST_DSN"]
    parsed = urlsplit(dsn)
    assert os.environ.get("AUTOMATION_CONTROL_TEST_ISOLATED") == "true"
    assert parsed.hostname in {"localhost", "127.0.0.1"}
    assert parsed.path == "/automation_control_test", "Disposable local database only"
    db = await asyncpg.connect(dsn, command_timeout=15)
    pool = None
    old_settings = control.get_settings
    try:
        assert await db.fetchval("select current_database()") == "automation_control_test"
        version = await db.fetchval("show server_version")
        assert version.startswith("17."), "Native PostgreSQL 17 is required"
        assert not await db.fetchval("select to_regnamespace('tcg') is not null"), "Fresh fixture DB required"
        await db.execute(SCHEMA)
        foundation = (MIGRATIONS / "20260926213000_access_control_foundation.sql").read_text()
        await db.execute(foundation[
            foundation.index("create or replace function tcg.current_access_role()"):
            foundation.index("create or replace function tcg.create_founder_invite(")
        ])
        action = (MIGRATIONS / "20260928211713_import_enrichment_action_queue.sql").read_text()
        await db.execute(action[
            action.index("create table tcg.action_required_items ("):
            action.index("create or replace function tcg.emit_import_committed_event()")
        ])
        for filename in (
            "20260930050000_automation_runs_n8n_contract.sql",
            "20260930163000_action_required_automation_category.sql",
            "20260930054500_n8n_runtime_heartbeat.sql",
        ):
            await db.execute((MIGRATIONS / filename).read_text())
        await db.execute("insert into auth.users(id) values($1)", USER_A)
        for position, (owner, kind, active) in enumerate((
            (FOUNDER_A, "FOUNDER", True), (FOUNDER_B, "FOUNDER", True),
            (INACTIVE, "FOUNDER", False), (CONSIGNOR, "CONSIGNOR", True),
        )):
            await db.execute(
                "insert into tcg.owners values($1,$2,$3,$4,$5)", owner, "Synthetic owner",
                kind, active, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=position),
            )
        await db.execute(
            "insert into tcg.owner_memberships(owner_id,user_id,active,role) values($1,$2,true,'OWNER')",
            FOUNDER_A, USER_A,
        )
        pool = await asyncpg.create_pool(
            dsn, user="tcg_api", password=RUNTIME_PASSWORD, min_size=1, max_size=8,
            command_timeout=15, init=_init_connection,
        )
        app = FastAPI()
        app.state.db_pool = pool
        app.include_router(control.router)
        control.get_settings = lambda: SimpleNamespace(automation_command_secret=SECRET)

        async def post(operation, value):
            raw = json.dumps(value, separators=(",", ":")).encode()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://fixture"
            ) as client:
                return await client.post(
                    "/api/v1/automation/control/" + operation, content=raw,
                    headers=signature_headers(secret=SECRET, body=raw),
                )

        async def restricted(query, *args):
            async with pool.acquire() as conn:
                return await conn.fetch(query, *args)

        # Retain all three original defects as actual SQL regressions.
        await expect_sql(restricted(
            "select * from tcg.record_automation_heartbeat($1,$2,$3,$4)",
            "n8n-runtime", "v1", "old-native", datetime.now(timezone.utc),
        ), "42702")
        assert await restricted("select id from tcg.owners where active and owner_type='FOUNDER'") == []
        await expect_sql(db.execute("""insert into tcg.action_required_items(
            owner_id,category,code,severity,entity_type,entity_id,dedupe_key,title)
            values($1,'AUTOMATION','N8N_WORKFLOW_FAILED','HIGH','N8N_WORKFLOW',$1,'old-invalid','Old invalid entity')""",
            FOUNDER_A), "23514")
        absent = await post("receipt", receipt("missing-capability"))
        assert absent.status_code == 503 and absent.json() == {
            "detail": "Automation control storage is unavailable"
        }

        async def blocked_migration():
            try:
                await expect_sql(db.execute(REPAIR.read_text()), "P0001")
            finally:
                if db.is_in_transaction():
                    await db.execute("rollback")
            assert not await db.fetchval("select to_regprocedure($1) is not null", FUNCTION)

        # Unknown/broadened privilege state or missing arbiters must block DDL.
        await db.execute("alter role tcg_api bypassrls")
        await blocked_migration()
        await db.execute("alter role tcg_api nobypassrls")
        await db.execute("alter table tcg.owners disable row level security")
        await blocked_migration()
        await db.execute("alter table tcg.owners enable row level security")
        await db.execute("grant update on tcg.automation_runs to tcg_api")
        await blocked_migration()
        await db.execute("revoke update on tcg.automation_runs from tcg_api")
        await db.execute("alter table tcg.automation_heartbeats rename constraint automation_heartbeats_pkey to wrong_fixture_key")
        await blocked_migration()
        await db.execute("alter table tcg.automation_heartbeats rename constraint wrong_fixture_key to automation_heartbeats_pkey")
        await db.execute("alter table tcg.automation_heartbeats drop constraint automation_heartbeats_pkey")
        await db.execute("alter table tcg.automation_heartbeats add primary key(heartbeat_key) deferrable initially immediate")
        await blocked_migration()
        await db.execute("alter table tcg.automation_heartbeats drop constraint automation_heartbeats_pkey")
        await db.execute("alter table tcg.automation_heartbeats add primary key(heartbeat_key)")
        await db.execute("alter table tcg.automation_runs drop constraint fixture_runs_unique")
        await blocked_migration()
        await db.execute("alter table tcg.automation_runs add constraint fixture_deferred unique(owner_id,job_type,run_key) deferrable initially immediate")
        await blocked_migration()
        await db.execute("alter table tcg.automation_runs drop constraint fixture_deferred")
        await db.execute("create unique index fixture_runs_reordered on tcg.automation_runs(run_key,owner_id,job_type) include(initiated_by)")
        await db.execute("alter table tcg.automation_runs add constraint fixture_deferred_also unique(owner_id,job_type,run_key) deferrable initially immediate")
        await expect_sql(db.execute("""insert into tcg.automation_runs(owner_id,job_type,run_key,result)
            values($1,'INVENTORY_REVIEW','mixed-arbiter','{}')
            on conflict(owner_id,job_type,run_key) do nothing""", FOUNDER_A), "55000")
        await blocked_migration()
        await db.execute("alter table tcg.automation_runs drop constraint fixture_deferred_also")
        await db.execute("alter table tcg.action_required_items drop constraint action_required_items_owner_id_dedupe_key_key")
        await blocked_migration()
        await db.execute("create unique index fixture_partial on tcg.action_required_items(owner_id,dedupe_key) where status='OPEN'")
        await blocked_migration()
        await db.execute("drop index tcg.fixture_partial")
        await db.execute("create unique index fixture_actions_reordered on tcg.action_required_items(dedupe_key,owner_id) include(status)")

        async def permission_state():
            return await db.fetch("""select c.relname,c.relrowsecurity,c.relforcerowsecurity,
                coalesce(c.relacl::text,'') acl,
                (select jsonb_agg(jsonb_build_array(a.attname,a.attacl::text) order by a.attnum)
                 from pg_attribute a where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped) columns
                from pg_class c join pg_namespace n on n.oid=c.relnamespace
                where n.nspname='tcg' and c.relname in
                 ('owners','automation_runs','action_required_items','automation_heartbeats') order by c.relname""")

        before_permissions = await permission_state()
        await db.execute(REPAIR.read_text())
        assert await permission_state() == before_permissions
        await db.execute("""create schema supabase_migrations;
            create table supabase_migrations.schema_migrations(version text primary key,name text);
            insert into supabase_migrations.schema_migrations values
              ('20260930044501','n8n_runtime_heartbeat'),('20261027164716','automation_control_runtime_repair');""")
        preflight = await db.fetchval((ROOT / "docs/evidence/automation-control-runtime-preflight-20261027.sql").read_text())
        preflight = json.loads(preflight) if isinstance(preflight, str) else preflight
        assert preflight["heartbeat_named_primary_key_matches"]
        assert preflight["migration_ledger"]["repair_version_present"]
        assert preflight["migration_ledger"]["repair_name_present"]
        assert all(key["usable_index_count"] > 0 for key in preflight["required_unique_keys"])
        assert all(fn["present"] for fn in preflight["functions"])
        await db.execute("update supabase_migrations.schema_migrations set version='20261027170000' where name='automation_control_runtime_repair'")
        later_ledger = json.loads(await db.fetchval((ROOT / "docs/evidence/automation-control-runtime-preflight-20261027.sql").read_text()))
        assert later_ledger["migration_ledger"]["repair_name_present"]
        assert not later_ledger["migration_ledger"]["repair_version_present"]
        capability = await db.fetchrow("""select p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner) as owner
            from pg_proc p where p.oid=$1::regprocedure""", FUNCTION)
        assert capability["prosecdef"] and capability["owner"] == "postgres"
        assert "search_path=pg_catalog" in capability["proconfig"]
        assert "lock_timeout=2s" in capability["proconfig"]
        for role in ("anon", "authenticated", "service_role", "tcg_auditor"):
            assert not await db.fetchval("select has_function_privilege($1,$2,'EXECUTE')", role, FUNCTION)
            async with db.transaction():
                await db.execute("set local role " + role)
                await expect_sql(db.fetch(CALL, *receipt_args(receipt())), "42501")
        assert await db.fetchval("select has_function_privilege('tcg_api',$1,'EXECUTE')", FUNCTION)
        role = (await restricted("select current_user as role,session_user as login,tcg.current_user_id() as actor"))[0]
        assert role["role"] == role["login"] == "tcg_api" and role["actor"] is None
        assert await restricted("select id from tcg.owners") == []
        await expect_sql(restricted("select * from tcg.automation_heartbeats"), "42501")
        await expect_sql(restricted("insert into tcg.automation_runs(owner_id,job_type,run_key,result) values($1,'INVENTORY_REVIEW','forbidden','{}')", FOUNDER_A), "42501")

        # Existing heartbeat signature: first beat, duplicate, stale, then newer.
        now = datetime.now(timezone.utc)
        heartbeat = {"heartbeat_key": "n8n-runtime", "workflow_version": "v1",
                     "execution_id": "native-heartbeat-1", "occurred_at": now.isoformat()}
        first = await post("heartbeat", heartbeat)
        assert first.status_code == 200 and first.json()["beat_count"] == 1
        original_beat = await db.fetchrow("select * from tcg.automation_heartbeats")
        duplicate = await post("heartbeat", heartbeat)
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
        stale = await post("heartbeat", {**heartbeat, "execution_id": "older",
                                        "occurred_at": (now - timedelta(minutes=1)).isoformat()})
        assert stale.status_code == 200 and stale.json()["duplicate"]
        assert await db.fetchrow("select * from tcg.automation_heartbeats") == original_beat
        newer = await post("heartbeat", {**heartbeat, "execution_id": "native-heartbeat-2",
                                        "occurred_at": (now + timedelta(seconds=1)).isoformat()})
        assert newer.status_code == 200 and newer.json()["beat_count"] == 2 and not newer.json()["duplicate"]
        expired = await post("heartbeat", {**heartbeat, "occurred_at": (now - timedelta(hours=1)).isoformat()})
        assert expired.status_code == 422

        # A prior fixed OWNER alert keeps its ID on a new failure and on retries.
        await db.execute("""insert into tcg.action_required_items(
            id,owner_id,category,code,severity,entity_type,entity_id,dedupe_key,title,
            status,resolved_at,resolved_by_user_id,version)
            values($1,$2,'AUTOMATION','N8N_WORKFLOW_FAILED','HIGH','OWNER',$2,
            'n8n-workflow-failed:runtime-heartbeat','Existing synthetic alert',
            'RESOLVED',now(),$3,5)""", EXISTING_ALERT, FOUNDER_A, USER_A)
        value = receipt()
        result = await post("receipt", value)
        assert result.status_code == 200
        assert result.json()["owner_receipts_inserted"] == 2 and result.json()["duplicate_owner_receipts"] == 0
        assert str(EXISTING_ALERT) in result.json()["action_required_ids"]
        alerts = await db.fetch("select * from tcg.action_required_items order by owner_id")
        assert {row["owner_id"] for row in alerts} == {FOUNDER_A, FOUNDER_B}
        assert all(row["entity_type"] == "OWNER" and row["entity_id"] == row["owner_id"] for row in alerts)
        assert alerts[0]["id"] == EXISTING_ALERT and alerts[0]["version"] == 6 and alerts[0]["status"] == "OPEN"
        assert all(row["category"] == "AUTOMATION" and row["code"] == "N8N_WORKFLOW_FAILED" and row["severity"] == "HIGH" for row in alerts)
        runs = await db.fetch("select * from tcg.automation_runs order by owner_id")
        audit_count = await db.fetchval("select count(*) from tcg.audit_events")
        retried = await post("receipt", value)
        assert retried.status_code == 200 and retried.json()["owner_receipts_inserted"] == 0
        assert retried.json()["duplicate_owner_receipts"] == 2 and retried.json()["action_required_ids"] == []
        assert await db.fetch("select * from tcg.automation_runs order by owner_id") == runs
        assert await db.fetch("select * from tcg.action_required_items order by owner_id") == alerts
        assert await db.fetchval("select count(*) from tcg.audit_events") == audit_count
        # A duplicate key keeps the first immutable outcome, even if retry fields differ.
        changed_retry = await post("receipt", {**value, "error_message": "Different retry detail"})
        assert changed_retry.status_code == 200 and changed_retry.json()["duplicate_owner_receipts"] == 2
        assert await db.fetch("select * from tcg.automation_runs order by owner_id") == runs
        assert await db.fetch("select * from tcg.action_required_items order by owner_id") == alerts
        succeeded = await post("receipt", receipt(execution="native-success", status="SUCCEEDED",
                                                  error_code=None, error_message=None))
        assert succeeded.status_code == 200 and succeeded.json()["action_required_ids"] == []
        assert await db.fetch("select * from tcg.action_required_items order by owner_id") == alerts

        # Eight simultaneous first writes produce one run and one alert per founder.
        competing = receipt("concurrent-fixture", "same-key")
        concurrent = await asyncio.gather(*(post("receipt", competing) for _ in range(8)))
        assert all(response.status_code == 200 for response in concurrent)
        assert sum(response.json()["owner_receipts_inserted"] for response in concurrent) == 2
        assert sum(response.json()["duplicate_owner_receipts"] for response in concurrent) == 14
        assert await db.fetchval("select count(*) from tcg.automation_runs where job_type='N8N:concurrent-fixture'") == 2
        concurrent_alerts = await db.fetch("select version from tcg.action_required_items where dedupe_key='n8n-workflow-failed:concurrent-fixture'")
        assert len(concurrent_alerts) == 2 and all(row["version"] == 1 for row in concurrent_alerts)

        # The second founder's alert failure rolls back both founders and audits.
        await db.execute("""create function tcg.fixture_fail_second_alert() returns trigger language plpgsql as $$
          begin if new.owner_id='10000000-0000-4000-8000-000000000002'::uuid
            and new.metadata->>'workflow_key'='rollback-fixture' then
            raise exception 'SYNTHETIC_PRIVATE_DETAIL' using errcode='23514'; end if; return new; end $$;
          create trigger fixture_fail_second_alert before insert or update on tcg.action_required_items
          for each row execute function tcg.fixture_fail_second_alert();""")
        prior_audits = await db.fetchval("select count(*) from tcg.audit_events")
        rollback = await post("receipt", receipt("rollback-fixture"))
        assert rollback.status_code == 503 and "SYNTHETIC_PRIVATE_DETAIL" not in rollback.text
        assert await db.fetchval("select count(*) from tcg.automation_runs where job_type='N8N:rollback-fixture'") == 0
        assert await db.fetchval("select count(*) from tcg.action_required_items where dedupe_key='n8n-workflow-failed:rollback-fixture'") == 0
        assert await db.fetchval("select count(*) from tcg.audit_events") == prior_audits
        await db.execute("drop trigger fixture_fail_second_alert on tcg.action_required_items; drop function tcg.fixture_fail_second_alert()")
        recovered = await post("receipt", receipt("rollback-fixture"))
        assert recovered.status_code == 200 and recovered.json()["owner_receipts_inserted"] == 2

        for owner in (INACTIVE, UUID("99999999-9999-4999-8999-999999999999")):
            invalid_owner = await post("receipt", receipt("owner-fixture", owner_id=str(owner)))
            assert invalid_owner.status_code == 422
        await db.execute("update tcg.owners set active=false where owner_type='FOUNDER'")
        no_founders = await post("receipt", receipt("no-founder-fixture"))
        assert no_founders.status_code == 503
        assert await db.fetchval("select count(*) from tcg.automation_runs where job_type='N8N:no-founder-fixture'") == 0
        explicit = await post("receipt", receipt("explicit-owner-fixture", owner_id=str(CONSIGNOR)))
        assert explicit.status_code == 200 and explicit.json()["owner_receipts_inserted"] == 1
        assert await db.fetchval("select owner_id from tcg.automation_runs where job_type='N8N:explicit-owner-fixture'") == CONSIGNOR
        await db.execute("update tcg.owners set active=true where id=any($1::uuid[])", [FOUNDER_A, FOUNDER_B])
        for changes in ({"workflow_key": "Invalid key"}, {"status": "OTHER"},
                        {"execution_id": ""}, {"workflow_version": "x" * 81},
                        {"idempotency_key": "x" * 256}, {"error_code": "x" * 121},
                        {"error_message": "x" * 1201}, {"error_code": None, "error_message": " "}):
            await expect_sql(restricted(CALL, *receipt_args(receipt("invalid-fixture", **changes))), "22023")
        assert await restricted("select * from tcg.automation_runs") == []
        assert await restricted("select * from tcg.action_required_items") == []
        assert await permission_state() == before_permissions
        actor = (await restricted("select tcg.current_user_id() as actor"))[0]
        assert actor["actor"] is None

        print(json.dumps({
            "status": "PASS", "postgres": version.split(",")[0],
            "original_failures_reproduced": ["heartbeat_42702", "owner_rls_empty", "alert_entity_23514"],
            "native_checks": ["migration_fail_closed", "unique_index_shapes", "catalogue_preflight",
                "ledger_name_and_version", "unchanged_acl_rls",
                "restricted_real_login", "no_actor_impersonation", "heartbeat_monotonic_replay",
                "signed_routes", "private_grants", "founder_fanout", "existing_alert_identity",
                "immutable_duplicate", "eight_concurrent_first_writes", "all_founder_atomic_rollback",
                "inactive_missing_owner", "no_founders", "explicit_active_owner"],
            "production_database_accessed": False,
        }, sort_keys=True))
    finally:
        control.get_settings = old_settings
        if pool is not None:
            await pool.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
