"""No external D1/Cloudflare calls. Synthetic immutable R2 catalogue fixtures."""
from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from app import d1_shadow_catalogue as bridge
from app import r2_first_catalogue as r2

SOURCE_URL = "https://mtgjson.com/api/v5/AllPrintings.json.xz"
SCOPE = ("mtgjson", "MAGIC_THE_GATHERING", "English")


def row(idx, *, finish="nonfoil", name=None, details=None):
    return {
        "provider": SCOPE[0], "system_code": SCOPE[1], "language": SCOPE[2],
        "provider_id": f"mtgjson:11111111-1111-5111-8111-{idx:012d}:{finish}",
        "product_type": "CARD", "name": name or f"Synthetic Test Card {idx}",
        "set_id": "TMP", "set_name": "Test Set", "card_number": str(idx),
        "rarity": "common", "finish": finish,
        "release_date": "2027-01-01" if idx == 0 else "2026-01-01",
        "source_url": SOURCE_URL,
        "details": details if details is not None else {"cardmarket_product_id": str(1000 + idx)},
    }


def snapshot(rows=None, *, revision="synthetic-v1"):
    records = rows if rows is not None else [row(i) for i in range(15)]
    bundle = r2.prepare_catalogue(records, provider=SCOPE[0],
        system_code=SCOPE[1], language=SCOPE[2], source_url=SOURCE_URL,
        source_revision=revision, permission_ref="https://mtgjson.com/license/")
    snap = r2.Snapshot(bundle.manifest)
    for raw, part in zip(bundle.parts, bundle.manifest["parts"], strict=True):
        snap._append(r2._parse_part(raw, part, SCOPE))
    snap._finish()
    return snap


def execute_schema(db):
    db.executescript(bridge.SCHEMA)


def submit(db, statements):
    for item in statements:
        db.execute(item["sql"], item["params"])


def test_exact_ids_and_all_future_records_preserved_without_market_values():
    with snapshot() as snap:
        result = bridge.from_verified_snapshot(snap)
        assert result.expected_rows == 15
        assert result.manifest_sha == snap.manifest_digest
        assert result.scope == SCOPE
        assert len(result.rows) == 15
        assert any(row[14] == "2027-01-01" for row in result.rows)
        assert len(set(row[1] for row in result.rows)) == 15
        assert "market_value_minor" not in bridge.SCHEMA
        assert "retail" not in bridge.SCHEMA.lower()
        assert "shopify" not in bridge.SCHEMA.lower()
        assert all(len(statement["params"]) <= 100 for statement in bridge.insert_statements(result))
        assert "insert into shadow_cards" in next(iter(bridge.insert_statements(result)))["sql"]


def test_stage_complete_then_activate_and_revert_without_any_production_dependency():
    with sqlite3.connect(":memory:") as db, snapshot() as first:
        execute_schema(db)
        p1 = bridge.from_verified_snapshot(first)
        submit(db, [bridge.generation_statement(p1)])
        batches = list(bridge.insert_statements(p1))
        assert len(batches) == 3  # 6 rows/SQL at 16 columns
        submit(db, batches[:1])
        submit(db, [bridge.activation_statement(p1)])
        assert db.execute("select count(*) from shadow_live_cards").fetchone()[0] == 0
        submit(db, batches[1:])
        submit(db, [bridge.activation_statement(p1)])
        assert db.execute("select count(*) from shadow_live_cards").fetchone()[0] == 15
        assert db.execute("select count(*) from shadow_active_partitions").fetchone()[0] == 1

        # Changing the immutable R2 revision produces a different generation.
        with snapshot([row(i, name="Changed " + str(i)) for i in range(15)], revision="synthetic-v2") as newer:
            p2 = bridge.from_verified_snapshot(newer)
            assert p2.manifest_sha != p1.manifest_sha
            submit(db, [bridge.generation_statement(p2)])
            b2 = list(bridge.insert_statements(p2))
            submit(db, b2[:1])
            submit(db, [bridge.activation_statement(p2)])
            assert db.execute("select count(*) from shadow_live_cards where name like 'Changed%'").fetchone()[0] == 0
            assert db.execute("select count(*) from shadow_live_cards").fetchone()[0] == 15
            submit(db, b2[1:])
            submit(db, [bridge.activation_statement(p2)])
            assert db.execute("select count(*) from shadow_live_cards where name like 'Changed%'").fetchone()[0] == 15
            submit(db, [bridge.activation_statement(p1)])
            assert db.execute("select count(*) from shadow_live_cards where name like 'Changed%'").fetchone()[0] == 0


def test_duplicate_source_id_or_invalid_source_scope_never_publishes():
    with snapshot() as snap:
        p = bridge.from_verified_snapshot(snap)
        bad = replace(p, rows=p.rows[:3] + (p.rows[0],) + p.rows[4:])
        with sqlite3.connect(":memory:") as db:
            execute_schema(db)
            submit(db, [bridge.generation_statement(p)])
            with pytest.raises(sqlite3.IntegrityError):
                submit(db, bridge.insert_statements(bad))
    with snapshot([row(0)]) as snap:
        source = snap.search
        snap.search = lambda **kw: {"total": 1, "items": [dict(source(**kw)["items"][0], provider="wrong")]}
        with pytest.raises(bridge.ProjectionError, match="R2 source"):
            bridge.from_verified_snapshot(snap)


def test_failed_pagination_does_not_create_partial_projection():
    with snapshot([row(0)]) as snap:
        snap.search = lambda **kw: {"total": 1, "items": []}
        with pytest.raises(bridge.ProjectionError, match="Incomplete"):
            bridge.from_verified_snapshot(snap)


def test_invalid_cardmarket_source_id_is_rejected_not_mapped_by_name():
    with snapshot([row(0, details={"cardmarket_product_id":"000031"})]) as snap:
        with pytest.raises(bridge.ProjectionError, match="Cardmarket"):
            bridge.from_verified_snapshot(snap)


def test_source_scoped_exact_keys_and_64_character_manifest_guard():
    with snapshot([row(0), row(1, finish="foil")]) as snap:
        p = bridge.from_verified_snapshot(snap)
        assert all(len(r[1]) == 66 and r[1].startswith("x:") for r in p.rows)
        assert len(p.source_content_sha) == 64
        with sqlite3.connect(":memory:") as db:
            execute_schema(db)
            submit(db, [bridge.generation_statement(p)])
            submit(db, bridge.insert_statements(p))
            submit(db, [bridge.activation_statement(p)])
            rows = db.execute(bridge.LIVE_CARD_SQL, (*SCOPE, 25, 0)).fetchall()
            assert len(rows) == 2


def test_reject_fake_snapshot_and_source_count_overflow(monkeypatch):
    with pytest.raises(bridge.ProjectionError, match="Snapshot"):
        bridge.from_verified_snapshot({"rows":[]})
    with snapshot([row(0),row(1)]) as snap:
        monkeypatch.setattr(bridge, "MAX_SOURCE_ROWS", 1)
        with pytest.raises(bridge.ProjectionError, match="Unverified"):
            bridge.from_verified_snapshot(snap)
