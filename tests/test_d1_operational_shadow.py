"""SQLite shadow integration tests: no live data, money movement or D1 token."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

SQL = Path("database/cloudflare_d1/0001_operational_shadow.sql").read_text()
H = "a" * 64


def execute(db, sql, *params):
    return db.execute(sql, params)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SQL)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    execute(conn, """INSERT INTO ops_shadow_generations
      (generation_id,source_manifest_sha256,source_captured_at,source_schema_sha256)
      VALUES(?,?,?,?)""", "g1", H, "2026-11-06T00:00:00Z", "b"*64)
    for slot, owner in [(1, "owner1"), (2, "owner2")]:
        execute(conn, """INSERT INTO ops_shadow_identity_map
          (generation_id,legacy_user_id) VALUES('g1',?)""", "user"+str(slot))
        execute(conn, """INSERT INTO ops_shadow_owners
          (generation_id,id,display_name,owner_type,founder_slot,active,
           commission_bps,source_row_sha256,source_row_json)
          VALUES('g1',?,?,'FOUNDER',?,1,1000,?,'{}')""", owner, owner, slot, H)
        execute(conn, """INSERT INTO ops_shadow_memberships
          (generation_id,id,legacy_user_id,owner_id,role,active,
           source_row_sha256,source_row_json)
          VALUES('g1',?,?,?,'OWNER',1,?,'{}')""",
          "member"+str(slot), "user"+str(slot), owner, H)
        execute(conn, """INSERT INTO ops_shadow_catalogue_links
          (generation_id,catalogue_id,reference_manifest_sha256)
          VALUES('g1',?,?)""", "card"+str(slot), H)
        execute(conn, """INSERT INTO ops_shadow_inventory
          (generation_id,id,inventory_code,catalogue_id,owner_id,currency,
           status,sale_intent,version,source_row_sha256,source_row_json)
          VALUES('g1',?,?,?,?,'GBP','FOR_SALE','FOR_SALE',1,?,'{}')""",
          "inv"+str(slot), "INV-000"+str(slot), "card"+str(slot), owner, H)
    execute(conn, """INSERT INTO ops_shadow_orders
      (generation_id,id,source,source_reference,currency,status,placed_at,
       source_row_sha256,source_row_json)
      VALUES('g1','order1','SHOPIFY','shopify-order-1','GBP','PAID',
             '2026-11-06T00:00:00Z',?,'{}')""", H)
    yield conn
    conn.close()


def sale(db, name, inventory, owner, price, discount, fee):
    execute(db, """INSERT INTO ops_shadow_order_items
      (generation_id,id,order_id,inventory_id,owner_id,sale_price_minor,
       discount_minor,net_sale_minor,commission_bps_snapshot,commission_minor,
       sold_at,source_row_sha256,source_row_json)
      VALUES('g1',?,'order1',?,?,?,?,?,1000,?,
       '2026-11-06T00:00:00Z',?,'{}')""",
       name, inventory, owner, price, discount, price-discount, fee, H)


def ledger(db, name, owner, item, amount, source_key):
    execute(db, """INSERT INTO ops_shadow_ledger
      (generation_id,id,owner_id,order_id,order_item_id,entry_type,
       amount_minor,currency,funds_status,source_key,occurred_at,
       source_row_sha256,source_row_json)
       VALUES('g1',?,?,'order1',?,'SALE',?,'GBP','AVAILABLE',?,
        '2026-11-06T00:00:00Z',?,'{}')""",
       name, owner, item, amount, source_key, H)


def test_two_founders_single_shopify_order_and_ledger(db):
    sale(db, "item1", "inv1", "owner1", 1000, 100, 90)
    sale(db, "item2", "inv2", "owner2", 2000, 0, 200)
    ledger(db, "l1", "owner1", "item1", 810, "order1:item1:sale")
    ledger(db, "l2", "owner2", "item2", 1800, "order1:item2:sale")
    expected = [("owner1", 810), ("owner2", 1800)]
    actual = db.execute("""SELECT owner_id,sum(amount_minor)
        FROM ops_shadow_ledger GROUP BY owner_id ORDER BY owner_id""").fetchall()
    assert actual == expected


def test_duplicate_webhook_and_ledger_are_idempotent(db):
    sale(db, "item1", "inv1", "owner1", 1000, 0, 100)
    for _ in range(100):
        execute(db, """INSERT OR IGNORE INTO ops_shadow_webhook_inbox
          (generation_id,id,webhook_id,topic,shop_domain,payload_sha256,
           status,received_at,source_row_sha256,source_row_json)
          VALUES('g1','event1','webhook-abc','orders/paid','drop-rate',
          ?,'PROCESSED','2026-11-06T00:00:00Z',?,'{}')""", H, H)
        execute(db, """INSERT OR IGNORE INTO ops_shadow_ledger
          (generation_id,id,owner_id,order_id,order_item_id,entry_type,
           amount_minor,currency,funds_status,source_key,occurred_at,
           source_row_sha256,source_row_json)
           VALUES('g1','ledger1','owner1','order1','item1','SALE',900,
           'GBP','AVAILABLE','order1:item1:sale','2026-11-06T00:00:00Z',?,'{}')""", H)
    assert db.execute("SELECT count(*) FROM ops_shadow_webhook_inbox").fetchone() == (1,)
    assert db.execute("SELECT count(*) FROM ops_shadow_ledger").fetchone() == (1,)


def test_exact_refund_and_negative_ledger_reversal(db):
    sale(db, "item1", "inv1", "owner1", 1000, 0, 100)
    ledger(db, "original", "owner1", "item1", 900, "sale:1")
    execute(db, """INSERT INTO ops_shadow_refunds
       (generation_id,id,owner_id,order_id,order_item_id,inventory_id,
        source_reference,amount_minor,currency,occurred_at,
        source_row_sha256,source_row_json)
       VALUES('g1','refund1','owner1','order1','item1','inv1',
       'shopify-refund1',200,'GBP','2026-11-06T00:10:00Z',?,'{}')""", H)
    ledger(db, "reversal", "owner1", "item1", -200, "refund:1")
    assert db.execute("SELECT sum(amount_minor) FROM ops_shadow_ledger").fetchone()[0] == 700
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, """INSERT INTO ops_shadow_refunds
           (generation_id,id,owner_id,order_id,order_item_id,inventory_id,
            source_reference,amount_minor,currency,occurred_at,
            source_row_sha256,source_row_json)
           VALUES('g1','refund2','owner2','order1','item1','inv1',
           'shopify-refund2',200,'GBP','2026-11-06T00:10:00Z',?,'{}')""", H)


def test_wrong_owner_sale_refused_even_with_existing_owner(db):
    with pytest.raises(sqlite3.IntegrityError, match="sale owner"):
        sale(db, "item1", "inv1", "owner2", 1000, 0, 100)


def test_owner_lineage_locked_after_sale(db):
    sale(db, "item1", "inv1", "owner1", 1000, 0, 100)
    with pytest.raises(sqlite3.IntegrityError, match="sold inventory"):
        execute(db, """UPDATE ops_shadow_inventory
          SET owner_id='owner2' WHERE id='inv1'""")
    with pytest.raises(sqlite3.IntegrityError, match="lineage"):
        execute(db, """UPDATE ops_shadow_order_items
          SET owner_id='owner2' WHERE id='item1'""")


def test_ledger_immutable_and_source_key_unique(db):
    sale(db, "item1", "inv1", "owner1", 1000, 0, 100)
    ledger(db, "l1", "owner1", "item1", 900, "sale:1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute(db, "UPDATE ops_shadow_ledger SET amount_minor=1 WHERE id='l1'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute(db, "DELETE FROM ops_shadow_ledger WHERE id='l1'")
    with pytest.raises(sqlite3.IntegrityError):
        ledger(db, "l2", "owner1", "item1", 900, "sale:1")


def test_optional_purchase_cost_is_null_not_zero(db):
    row = db.execute("SELECT acquisition_cost_minor FROM ops_shadow_inventory WHERE id='inv1'").fetchone()
    assert row == (None,)


def test_different_founder_cannot_reserve_other_founders_copy(db):
    with pytest.raises(sqlite3.IntegrityError, match="reservation owner"):
        execute(db, """INSERT INTO ops_shadow_reservations
          (generation_id,id,reservation_code,inventory_id,owner_id,status,
          source,source_reference,allocation_index,sale_price_minor_snapshot,
          source_row_sha256,source_row_json)
          VALUES('g1','r1','reserve1','inv1','owner2','ACTIVE','SHOPIFY',
          'order1',1,1000,?,'{}')""", H)


def test_one_active_inventory_reservation_at_a_time(db):
    def reserve(id):
        execute(db, """INSERT INTO ops_shadow_reservations
          (generation_id,id,reservation_code,inventory_id,owner_id,status,
           source,source_reference,allocation_index,sale_price_minor_snapshot,
           source_row_sha256,source_row_json)
           VALUES('g1',?,?,'inv1','owner1','ACTIVE','SHOPIFY','order1',
           1,1000,?,'{}')""", id, id, H)
    reserve("r1")
    with pytest.raises(sqlite3.IntegrityError):
        reserve("r2")


def test_no_production_activation_pointer_or_authoritative_reads(db):
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ops_shadow_generations" in tables
    assert all(name.startswith("ops_shadow_") for name in tables)
    assert "ops_active_generation" not in tables


def test_audit_immutable_and_no_auth_secret_columns(db):
    execute(db, """INSERT INTO ops_shadow_audit_events
      (generation_id,id,occurred_at,actor,action,entity_type,entity_id,
       old_values_json,new_values_json,source_row_sha256)
      VALUES('g1',1,'2026-11-06','admin','CREATE','OWNER','owner1',
       NULL,'{}',?)""", H)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute(db, "DELETE FROM ops_shadow_audit_events WHERE id=1")
    identity_columns = [x[1] for x in db.execute(
        "PRAGMA table_info(ops_shadow_identity_map)").fetchall()]
    assert "refresh_token" not in identity_columns
    assert "password" not in identity_columns
    assert "password_hash" not in identity_columns
    assert "session_token" not in identity_columns
