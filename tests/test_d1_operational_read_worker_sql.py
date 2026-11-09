"""Prove the Worker SQL against actual private operational D1 SQLite schema.

The Worker remains undeployed. Synthetic owners and inventory only; no DB
tokens, real source data, network, Supabase writes or payment processing.
"""
from __future__ import annotations
from pathlib import Path
import re
import sqlite3
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "database/cloudflare_d1/0001_operational_shadow.sql").read_text()
WORKER = (ROOT / "cloudflare/operational-readonly/worker.mjs").read_text()
GEN = "src-" + "b"*32
SHA = "a"*64
U = lambda n: str(UUID(int=n))
USER, OWNER1, OWNER2 = U(1), U(2), U(3)
CARD1, CARD2, CARD3 = U(100), U(101), U(102)
CATALOGUE = U(200)


def sql_from_worker(name):
    m = re.search(r"const " + name + r" = `(.*?)`;", WORKER, re.S)
    assert m, f"Fixed Worker SQL was removed: {name}"
    sql = m.group(1).strip()
    assert sql.upper().startswith("SELECT")
    for forbidden in ("INSERT", "DELETE", "UPDATE", "DROP", "ALTER", "PRAGMA"):
        assert not re.search(r"\b" + forbidden + r"\b", sql, re.I)
    return sql


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("""INSERT INTO ops_shadow_generations
      (generation_id,source_manifest_sha256,source_captured_at,
       source_schema_sha256,state) VALUES(?,?,?,?,'PARITY_VERIFIED')""",
       (GEN,SHA,"2026-11-09T10:00:00Z",SHA))
    con.execute("""INSERT INTO ops_shadow_identity_map
      (legacy_user_id,generation_id) VALUES(?,?)""", (USER,GEN))
    con.execute("""INSERT INTO ops_shadow_catalogue_links
      (generation_id,catalogue_id,reference_manifest_sha256) VALUES(?,?,?)""",
      (GEN,CATALOGUE,SHA))
    for owner,slot in ((OWNER1,1),(OWNER2,2)):
        con.execute("""INSERT INTO ops_shadow_owners
          (generation_id,id,display_name,owner_type,founder_slot,active,
           commission_bps,source_row_sha256,source_row_json)
          VALUES(?,?,'Synthetic','FOUNDER',?,1,0,?,'{}')""",
          (GEN,owner,slot,SHA))
    con.execute("""INSERT INTO ops_shadow_memberships
        (generation_id,id,legacy_user_id,owner_id,role,active,
         source_row_sha256,source_row_json)
        VALUES(?,?,?,?, 'OWNER',1,?,'{}')""",
        (GEN,U(7),USER,OWNER1,SHA))
    for card,owner in ((CARD1,OWNER1),(CARD2,OWNER1),(CARD3,OWNER2)):
        con.execute("""INSERT INTO ops_shadow_inventory
          (generation_id,id,inventory_code,catalogue_id,owner_id,currency,
           status,sale_intent,version,source_row_sha256,source_row_json)
          VALUES(?,?,?,?,?,'GBP','APPROVED','FOR_SALE',1,?,'{}')""",
          (GEN,card,"INV-"+card,CATALOGUE,owner,SHA))
    for i in range(9):
        con.execute("""INSERT INTO ops_shadow_table_receipts
            (generation_id,source_schema,source_table,exact_source_rows,
             exact_staged_rows,source_sha256,staged_sha256,verified_at)
            VALUES(?,'tcg',?,1,1,?,?,'2026-11-09T10:00:00Z')""",
            (GEN,f"source-{i}",SHA,SHA))
    yield con
    con.close()


def owner_rows(db):
    return [dict(x) for x in db.execute(
        sql_from_worker("OWNER_SQL"),(GEN,USER))]


def inventory_rows(db, owner, cursor="", limit=2):
    return [dict(x) for x in db.execute(
        sql_from_worker("INVENTORY_SQL"),(GEN,owner,cursor,limit))]


def test_exact_real_schema_owner_join_returns_unique_active_owner(db):
    assert owner_rows(db)==[{"owner_id":OWNER1,"owner_type":"FOUNDER"}]
    received=inventory_rows(db,OWNER1)
    assert [x["id"] for x in received]==[CARD1,CARD2]
    assert all(x["owner_id"]==OWNER1 for x in received)
    assert inventory_rows(db,OWNER1,CARD1,1)[0]["id"]==CARD2
    assert inventory_rows(db,OWNER2)[0]["id"]==CARD3
    assert all(x["currency"]=="GBP" for x in received)


def test_verified_generation_and_nine_receipts_are_mandatory(db):
    assert len(owner_rows(db))==1
    db.execute("UPDATE ops_shadow_generations SET state='STAGING' WHERE generation_id=?",(GEN,))
    assert owner_rows(db)==[]
    db.execute("UPDATE ops_shadow_generations SET state='PARITY_VERIFIED' WHERE generation_id=?",(GEN,))
    db.execute("DELETE FROM ops_shadow_table_receipts WHERE source_table='source-8'")
    assert owner_rows(db)==[]


def test_inactive_owner_or_membership_denies_all_read_access(db):
    db.execute("UPDATE ops_shadow_owners SET active=0 WHERE id=?",(OWNER1,))
    assert owner_rows(db)==[]
    db.execute("UPDATE ops_shadow_owners SET active=1 WHERE id=?",(OWNER1,))
    db.execute("UPDATE ops_shadow_memberships SET active=0 WHERE legacy_user_id=?",(USER,))
    assert owner_rows(db)==[]


def test_two_active_owner_memberships_cannot_be_accepted_as_unique(db):
    db.execute("""INSERT INTO ops_shadow_memberships
        (generation_id,id,legacy_user_id,owner_id,role,active,
         source_row_sha256,source_row_json)
        VALUES(?,?,?,?, 'OWNER',1,?,'{}')""",
        (GEN,U(8),USER,OWNER2,SHA))
    result=owner_rows(db)
    assert len(result)==2
    assert {x["owner_id"] for x in result}=={OWNER1,OWNER2}
    # The Worker MUST deny this ambiguity with HTTP 409, never merge items.


def test_removed_identity_mapping_cannot_authorize_any_membership(db):
    # SQLite correctly protects FK links; deletion is impossible without
    # explicit, prohibited migration of both identity and membership.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM ops_shadow_identity_map WHERE legacy_user_id=?",(USER,))


def test_sql_is_bound_and_uses_generation_and_owner_on_every_inventory_read(db):
    owner=sql_from_worker("OWNER_SQL")
    inventory=sql_from_worker("INVENTORY_SQL")
    assert owner.count("?")==2
    assert inventory.count("?")==4
    assert "owner_id=?" in inventory
    assert "generation_id=?" in inventory
    assert "LIMIT ?" in inventory
    assert "ORDER BY id" in inventory
    plan=[str(x[-1]) for x in db.execute(
        "EXPLAIN QUERY PLAN "+inventory,(GEN,OWNER1,"",2))]
    assert any("INDEX" in item.upper() for item in plan)
