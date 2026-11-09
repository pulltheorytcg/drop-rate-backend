"""Real SQLite transaction rehearsal of an *inactive*, isolated D1 candidate.

No Cloudflare token, Supabase access, webhook call, R2 data or payment movement.
The Cloudflare Workers D1Database.batch transactional contract must be tested
separately on an isolated deployment before this model gains a live route.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from app.d1_candidate_sale import (
    CandidateSaleGuard, SaleLine, SaleEvent, build_paid_sale_batch,
    classify_webhook_replay, commission_minor,
)

DDL = (Path(__file__).resolve().parents[1]
       / "database/cloudflare_d1/candidate/0001_atomic_sale.sql").read_text()


def uid(number: int) -> str:
    return str(UUID(int=number))


OWNER_A,OWNER_B=uid(11),uid(12)
INV_A,INV_B=uid(101),uid(102)
ITEM_A,ITEM_B=uid(201),uid(202)
ORDER=uid(301)
NOW="2026-11-09T09:00:00Z"
SHA="a"*64


def connect(path=":memory:"):
    conn=sqlite3.connect(path,timeout=8,isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def seed(db):
    db.execute("INSERT INTO candidate_owners VALUES(?, 'FOUNDER', 1, 1, 0)",(OWNER_A,))
    db.execute("INSERT INTO candidate_owners VALUES(?, 'CONSIGNOR', NULL, 1, 1000)",(OWNER_B,))
    for name,owner,id,cost in (
        ("INV-A",OWNER_A,INV_A,None),
        ("INV-B",OWNER_B,INV_B,500),
    ):
        db.execute("""INSERT INTO candidate_inventory
          (id,inventory_code,catalogue_id,owner_id,status,sale_intent,
           version,acquisition_cost_minor,currency)
          VALUES (?,?,?,?, 'APPROVED','FOR_SALE',1,?,'GBP')""",
          (id,name,uid(500),owner,cost))


def sample(*, order_id=ORDER, webhook_id="orders-paid-1000", source_reference="1000",
           inventory_id=INV_A, item_id=ITEM_A, owner_id=OWNER_A,
           price=1000, discount=100, cost=None, commission=0, version=1,
           sha=SHA):
    line=SaleLine(
        id=item_id,inventory_id=inventory_id,owner_id=owner_id,
        expected_inventory_version=version,sale_price_minor=price,
        discount_minor=discount,cost_basis_minor=cost,
        commission_bps_snapshot=commission,
    )
    return SaleEvent(
        order_id=order_id,source="SHOPIFY",
        source_reference=source_reference,webhook_id=webhook_id,
        shop_domain="droprate.myshopify.com",payload_sha256=sha,
        placed_at=NOW,lines=(line,),
    )


def execute_atomic(db,event):
    # Cloudflare production plan MUST run via single Worker D1Database.batch,
    # not individually committed REST calls. BEGIN IMMEDIATE simulates that
    # batch's all-or-nothing SQLite transaction and serialized writer.
    statements=build_paid_sale_batch(event)
    try:
        db.execute("BEGIN IMMEDIATE")
        for stmt in statements:
            db.execute(stmt.sql,stmt.params)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return statements


@pytest.fixture
def db():
    conn=connect()
    conn.executescript(DDL)
    seed(conn)
    yield conn
    conn.close()


def count(db,table):
    assert table in {
        "candidate_orders","candidate_order_items","candidate_inventory",
        "candidate_ledger","candidate_webhook_inbox","candidate_outbox",
    }
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_two_owners_one_order_are_atomic_and_commission_is_penny_exact(db):
    a=sample()
    b=SaleLine(id=ITEM_B,inventory_id=INV_B,owner_id=OWNER_B,
               expected_inventory_version=1,sale_price_minor=2000,
               discount_minor=0,cost_basis_minor=500,
               commission_bps_snapshot=1000)
    execute_atomic(db,replace(a,lines=a.lines+(b,)))
    assert count(db,"candidate_orders")==1
    assert count(db,"candidate_order_items")==2
    assert count(db,"candidate_webhook_inbox")==1
    assert count(db,"candidate_outbox")==1
    assert db.execute("SELECT status FROM candidate_orders").fetchone()[0]=="RECONCILIATION_REQUIRED"
    assert db.execute("SELECT DISTINCT funds_status FROM candidate_ledger").fetchall()[0][0]=="PENDING"
    ledger=[tuple(r) for r in db.execute(
        "SELECT owner_id,entry_type,amount_minor FROM candidate_ledger "
        "ORDER BY owner_id,entry_type")]
    assert ledger==[
        (OWNER_A,"SALE_REVENUE",900),
        (OWNER_B,"COMMISSION",-200),
        (OWNER_B,"SALE_REVENUE",2000),
    ]
    stock={r["id"]:(r["status"],r["version"]) for r in
           db.execute("SELECT id,status,version FROM candidate_inventory")}
    assert stock=={INV_A:("SOLD",2),INV_B:("SOLD",2)}
    assert commission_minor(5,1000)==1
    assert commission_minor(1,5000)==1
    assert commission_minor(100,0)==0


def test_idempotent_replay_cannot_double_post_and_changed_payload_is_conflict(db):
    event=sample()
    execute_atomic(db,event)
    before={t:count(db,t) for t in
            ("candidate_orders","candidate_order_items","candidate_ledger","candidate_outbox")}
    for _ in range(8):
        with pytest.raises(sqlite3.IntegrityError):
            execute_atomic(db,event)
    assert before=={t:count(db,t) for t in before}
    existing=dict(db.execute("SELECT * FROM candidate_webhook_inbox").fetchone())
    assert classify_webhook_replay(existing,event)=="REPLAY"
    assert classify_webhook_replay(existing,replace(event,payload_sha256="b"*64))=="CONFLICT"
    assert classify_webhook_replay(existing,replace(event,order_id=uid(302)))=="CONFLICT"


def test_second_item_wrong_owner_rolls_back_first_item_and_its_ledger(db):
    a=sample()
    tampered=SaleLine(id=ITEM_B,inventory_id=INV_B,owner_id=OWNER_A,
                      expected_inventory_version=1,sale_price_minor=2000,
                      discount_minor=0,cost_basis_minor=500,
                      commission_bps_snapshot=0)
    with pytest.raises(sqlite3.IntegrityError,match="mismatch"):
        execute_atomic(db,replace(a,lines=a.lines+(tampered,)))
    for table in ("candidate_orders","candidate_order_items","candidate_ledger",
                  "candidate_webhook_inbox","candidate_outbox"):
        assert count(db,table)==0
    assert [tuple(r) for r in db.execute(
        "SELECT status,version FROM candidate_inventory ORDER BY id")]==[
        ("APPROVED",1),("APPROVED",1)]


@pytest.mark.parametrize("wrong_line",[
    {"expected_inventory_version":2},
    {"cost_basis_minor":10},
    {"commission_bps_snapshot":1000},
    {"owner_id":OWNER_B},
])
def test_stale_version_cost_commission_or_owner_rejected_before_sold(db,wrong_line):
    event=sample()
    with pytest.raises(sqlite3.IntegrityError):
        execute_atomic(db,replace(event,lines=(replace(event.lines[0],**wrong_line),)))
    assert count(db,"candidate_order_items")==count(db,"candidate_ledger")==0
    assert db.execute("SELECT status FROM candidate_inventory WHERE id=?",(INV_A,)).fetchone()[0]=="APPROVED"


def test_sold_inventory_cannot_be_resold_under_new_order_or_event(db):
    execute_atomic(db,sample())
    with pytest.raises(sqlite3.IntegrityError):
        execute_atomic(db,sample(order_id=uid(302),webhook_id="orders-paid-1001",
                                 source_reference="1001",item_id=uid(203)))
    assert count(db,"candidate_order_items")==1
    assert count(db,"candidate_orders")==1
    assert db.execute("SELECT version FROM candidate_inventory WHERE id=?",(INV_A,)).fetchone()[0]==2


def test_two_competing_shopify_sales_one_physical_unit_only(tmp_path):
    file=tmp_path/"candidate.sqlite3"
    db=connect(file)
    db.executescript(DDL)
    seed(db)
    db.close()
    def worker(index):
        db=connect(file)
        event=sample(order_id=uid(1000+index),
                     webhook_id=f"hook-{index}",source_reference=str(index),
                     item_id=uid(2000+index))
        try:
            execute_atomic(db,event)
            return "POSTED"
        except sqlite3.IntegrityError:
            return "REFUSED"
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,(1,2)))
    assert sorted(results)==["POSTED","REFUSED"]
    db=connect(file)
    assert count(db,"candidate_orders")==count(db,"candidate_order_items")==1
    assert count(db,"candidate_ledger")==1
    assert db.execute("SELECT version FROM candidate_inventory WHERE id=?",(INV_A,)).fetchone()[0]==2
    db.close()


def test_immutable_financial_rows_and_unaudited_owner_transfer_refused(db):
    execute_atomic(db,sample())
    for statement in (
        "UPDATE candidate_ledger SET amount_minor=100000 WHERE entry_type='SALE_REVENUE'",
        "DELETE FROM candidate_ledger",
        "UPDATE candidate_order_items SET owner_id='bad'",
        "DELETE FROM candidate_order_items",
        "UPDATE candidate_inventory SET owner_id='bad' WHERE id='"+INV_A+"'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement)
    assert db.execute("SELECT amount_minor FROM candidate_ledger").fetchone()[0]==900


def test_invalid_founder_marketplace_commission_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE candidate_owners SET commission_bps=1000 WHERE id=?",(OWNER_A,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO candidate_owners VALUES(?, 'FOUNDER', 2, 1, 1000)",(uid(17),))


def test_invalid_inputs_fail_before_generating_any_sql_or_side_effect(db):
    source=sample()
    bad=(
        replace(source,source_reference="external'; DROP TABLE candidate_owners;--"),
        replace(source,source="OTHER"),
        replace(source,shop_domain="bad host"),
        replace(source,payload_sha256="A"*64),
        replace(source,placed_at="2026-11-09T09:00:00"),
        replace(source,lines=()),
        replace(source,lines=source.lines*2),
        replace(source,lines=(replace(source.lines[0],sale_price_minor=True),)),
        replace(source,lines=(replace(source.lines[0],discount_minor=1000),)),
        replace(source,lines=(replace(source.lines[0],commission_bps_snapshot=10001),)),
        replace(source,lines=(replace(source.lines[0],expected_inventory_version=0),)),
    )
    for event in bad:
        with pytest.raises(CandidateSaleGuard):
            build_paid_sale_batch(event)
    assert count(db,"candidate_orders")==0
    assert count(db,"candidate_ledger")==0


def test_only_fixed_parameterized_sql_no_runtime_or_provider_credentials(db):
    event=sample()
    batch=build_paid_sale_batch(event)
    assert len(batch)==4
    assert all(statement.sql.count("?")==len(statement.params) for statement in batch)
    assert all(len(statement.params)<=100 for statement in batch)
    assert all("droprate.myshopify.com" not in statement.sql for statement in batch)
    assert all("orders-paid-1000" not in statement.sql for statement in batch)
    assert all("INSERT" in statement.sql for statement in batch)
    sql=DDL.lower()
    assert "drop table" not in sql and "attach database" not in sql
    assert "candidate_ledger_no_update" in sql
    assert "candidate_item_sale_guard" in sql
    assert "candidate_item_sale_post" in sql
