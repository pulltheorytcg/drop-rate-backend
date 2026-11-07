"""Exercise the real eBay audit INSERTs against the deployed PostgreSQL contract."""
import ast
import inspect
import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app import ebay_sales
from app.ebay_sales import _load_listing_plan, _publish_inventory_to_ebay
from test_book_connector_import import run_sql
from test_ebay_cross_channel import _settings


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/migrations/20261104122307_ebay_marketplace_audit_entity.sql"
OWNER = "11111111-1111-1111-1111-111111111111"
OTHER_OWNER = "22222222-2222-2222-2222-222222222222"
ACTOR = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ACTOR = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
LINK = "33333333-3333-3333-3333-333333333333"


def audit_insert(function, *, owner=OWNER, actor=ACTOR):
    statements = [node.value for node in ast.walk(ast.parse(inspect.getsource(function)))
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and "insert into tcg.marketplace_audit_events(" in node.value]
    assert len(statements) == 1
    arguments = [owner, actor, LINK, '{"fixture":true}', "Isolated regression fixture"]
    return re.sub(r"\$(\d+)", lambda m: "'" + arguments[int(m[1]) - 1] + "'", statements[0])


def owner_step(sql):
    return (f"begin; set local role tcg_api; set local tcg.user_id='{ACTOR}';\n"
            + sql + "; commit;")


def setup_sql():
    # Use the original table, grants and policies, not a permissive test facsimile.
    original = (ROOT / "migrations/007_listing_reservation_engine.sql").read_text()
    audit_schema = original[original.index("create table if not exists tcg.marketplace_audit_events ("):]
    return f"""
        create role anon; create role authenticated; create role tcg_api;
        grant usage on schema tcg to tcg_api;
        create table tcg.owners(id uuid primary key, user_id uuid not null);
        insert into tcg.owners values ('{OWNER}','{ACTOR}'),('{OTHER_OWNER}','{OTHER_ACTOR}');
        create function tcg.current_user_id() returns uuid language sql stable as
          $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
        alter table tcg.owners enable row level security;
        alter table tcg.owners force row level security;
        grant select on tcg.owners to tcg_api;
        create policy fixture_owner_read on tcg.owners for select to tcg_api
          using (user_id=tcg.current_user_id());
        {audit_schema}
    """


def migration_step():
    return "begin;\n" + MIGRATION.read_text() + "\ncommit;"


def test_actual_started_and_published_writes_fail_before_repair_and_pass_after(tmp_path):
    started = audit_insert(_load_listing_plan)
    published = audit_insert(_publish_inventory_to_ebay)
    legacy = started.replace("'EBAY_INVENTORY_LINK'", "'LISTING'")
    steps = [owner_step(legacy), owner_step(started), owner_step(published), migration_step(),
             owner_step(started), owner_step(published), migration_step()]
    result = run_sql(tmp_path, steps, setup=setup_sql(), inspect="""
        select action,entity_type,count(*)::int as n from tcg.marketplace_audit_events
        group by action,entity_type order by entity_type,action
    """)
    assert result["results"][0]["ok"], result
    for index in (1, 2):
        assert not result["results"][index]["ok"]
        assert "marketplace_audit_events_entity_type_check" in result["results"][index]["error"]
    assert all(row["ok"] for row in result["results"][3:]), result
    assert result["inspected"] == [
        {"action": "EBAY_PUBLISHED", "entity_type": "EBAY_INVENTORY_LINK", "n": 1},
        {"action": "EBAY_PUBLISH_STARTED", "entity_type": "EBAY_INVENTORY_LINK", "n": 1},
        {"action": "EBAY_PUBLISH_STARTED", "entity_type": "LISTING", "n": 1},
    ]


def test_repair_retains_owner_actor_and_append_only_security(tmp_path):
    started = audit_insert(_load_listing_plan)
    steps = [migration_step(), owner_step(started),
             owner_step(audit_insert(_load_listing_plan, owner=OTHER_OWNER)),
             owner_step(audit_insert(_load_listing_plan, actor=OTHER_ACTOR)),
             owner_step("update tcg.marketplace_audit_events set notes='tampered'"),
             owner_step("delete from tcg.marketplace_audit_events"),
             owner_step(started.replace("'EBAY_INVENTORY_LINK'", "'UNKNOWN_ENTITY'")),
             f"begin; set local role tcg_api; set local tcg.user_id='{OTHER_ACTOR}'; "
             "select count(*)::int as n from tcg.marketplace_audit_events; commit;"]
    result = run_sql(tmp_path, steps, setup=setup_sql(),
                     inspect="select count(*)::int as n from tcg.marketplace_audit_events")
    assert all(row["ok"] for row in result["results"][:2]), result
    for index in (2, 3):
        assert "row-level security" in result["results"][index]["error"], result
    for index in (4, 5):
        assert "permission denied" in result["results"][index]["error"], result
    assert "marketplace_audit_events_entity_type_check" in result["results"][6]["error"]
    assert result["results"][7] == {"ok": True, "rows": [{"n": 0}]}
    assert result["inspected"] == [{"n": 1}]


def test_all_previous_audit_entity_types_remain_supported(tmp_path):
    started = audit_insert(_load_listing_plan)
    result = run_sql(tmp_path, [migration_step(), *[
        owner_step(started.replace("'EBAY_INVENTORY_LINK'", f"'{entity}'"))
        for entity in ("LISTING", "MEMBERSHIP", "RESERVATION")
    ]], setup=setup_sql(), inspect="select count(*)::int as n from tcg.marketplace_audit_events")
    assert all(row["ok"] for row in result["results"]), result
    assert result["inspected"] == [{"n": 3}]


@pytest.mark.asyncio
async def test_repeat_publish_of_live_copy_does_not_call_ebay(monkeypatch):
    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield object()

    effective = SimpleNamespace(
        refresh_token="fixture", payment_policy_id="payment", fulfillment_policy_id="delivery",
        return_policy_id="returns", merchant_location_key="fixture-location",
        notification_destination_id="destination", notification_subscription_id="subscription",
        status="READY",
    )
    remote = AsyncMock(side_effect=AssertionError("A LIVE retry must not call eBay"))
    monkeypatch.setattr(ebay_sales, "get_settings", _settings)
    monkeypatch.setattr(ebay_sales, "user_connection", connection)
    monkeypatch.setattr(ebay_sales, "_owner", AsyncMock(return_value={"id": UUID(OWNER)}))
    monkeypatch.setattr(ebay_sales, "load_effective_seller_config", AsyncMock(return_value=effective))
    monkeypatch.setattr(ebay_sales, "_load_listing_plan", AsyncMock(return_value={
        "already_live": True,
        "link": {"id": UUID(LINK), "state": "LIVE", "listing_id": "fixture-existing-listing"},
    }))
    monkeypatch.setattr(ebay_sales, "seller_client", remote)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id="fixture-retry"))
    user = SimpleNamespace(user_id=UUID(ACTOR))
    results = [await _publish_inventory_to_ebay(UUID(LINK), SimpleNamespace(version=2), request, user)
               for _ in range(2)]
    assert results[0] == results[1]
    assert results[0]["idempotent"] is True
    assert results[0]["listing_id"] == "fixture-existing-listing"
    remote.assert_not_awaited()
