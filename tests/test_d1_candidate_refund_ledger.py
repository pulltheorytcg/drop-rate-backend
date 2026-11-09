"""Offline real-SQLite tests for inactive D1 card-refund transactions.

No Cloudflare D1, Shopify, Supabase, customer identities, payouts or HTTP.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
from uuid import UUID

import pytest

from app.d1_candidate_sale import SaleEvent,SaleLine,build_paid_sale_batch,CandidateSaleGuard
from app.d1_candidate_refund_ledger import (
    CandidateCardRefundEvent,build_card_refund_batch,classify_card_refund_replay,
)
from app.d1_candidate_refund_math import (
    OriginalSale,RefundProgress,RequestedRefund,calculate_refund_ledger_delta,
)

ROOT=Path(__file__).resolve().parents[1]/"database/cloudflare_d1/candidate"
ORIGINAL=(ROOT/"0001_atomic_sale.sql").read_text()
REFUNDS=(ROOT/"0002_atomic_card_refunds.sql").read_text()
U=lambda n:str(UUID(int=n))
OWNER_F,OWNER_C=U(11),U(12)
ITEM_F,ITEM_C=U(21),U(22)
STOCK_F,STOCK_C=U(31),U(32)
ORDER=U(41)
NOW="2026-11-09T10:00:00Z"
HASH="b"*64


@pytest.fixture
def db():
    conn=sqlite3.connect(":memory:",isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ORIGINAL)
    conn.executescript(REFUNDS)
    conn.execute("INSERT INTO candidate_owners VALUES(?,'FOUNDER',1,1,0)",(OWNER_F,))
    conn.execute("INSERT INTO candidate_owners VALUES(?,'CONSIGNOR',NULL,1,1000)",(OWNER_C,))
    for inv,owner,cost in ((STOCK_F,OWNER_F,100),(STOCK_C,OWNER_C,500)):
        conn.execute(
            "INSERT INTO candidate_inventory "
            "(id,inventory_code,catalogue_id,owner_id,status,sale_intent,"
            "version,acquisition_cost_minor,currency)"
            " VALUES(?,?,?,?, 'APPROVED','FOR_SALE',1,?,'GBP')",
            (inv,"INV-"+inv,U(100),owner,cost),
        )
    yield conn
    conn.close()


def _sale(db,*,order=ORDER,item=ITEM_C,stock=STOCK_C,owner=OWNER_C,
          version=1,price=2000,cost=500,rate=1000,reference="paid-1000"):
    line=SaleLine(id=item,inventory_id=stock,owner_id=owner,
                  expected_inventory_version=version,sale_price_minor=price,
                  discount_minor=0,cost_basis_minor=cost,
                  commission_bps_snapshot=rate)
    event=SaleEvent(order_id=order,source="SHOPIFY",source_reference=reference,
          webhook_id="hook-"+reference,shop_domain="droprate.myshopify.com",
          payload_sha256=HASH,placed_at=NOW,lines=(line,))
    _run(db,build_paid_sale_batch(event))
    return event


def _refund(*,n=301,amount=500,returned=False,item=ITEM_C,stock=STOCK_C,
            owner=OWNER_C,order=ORDER,source_reference=None,payload=HASH):
    return CandidateCardRefundEvent(
        id=U(n),source="SHOPIFY",
        source_reference=source_reference or "refund-"+str(n),
        order_id=order,order_item_id=item,inventory_id=stock,
        owner_id=owner,card_amount_minor=amount,
        return_to_inspection=returned,payload_sha256=payload,
        occurred_at=NOW,
    )


def _run(db,statements):
    db.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            db.execute(statement.sql,statement.params)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def _money(db,item=ITEM_C):
    return dict((r["entry_type"],r["total"]) for r in db.execute(
        "SELECT entry_type,sum(amount_minor) AS total "
        "FROM candidate_ledger WHERE order_item_id=? GROUP BY entry_type",(item,)))


def _version(db,stock=STOCK_C):
    return tuple(db.execute(
        "SELECT status,version,current_sale_item_id FROM candidate_inventory WHERE id=?",
        (stock,)).fetchone())


def test_partial_to_full_refund_is_atomic_and_matches_pure_penny_math(db):
    _sale(db)
    assert _version(db)==("SOLD",2,ITEM_C)
    original=OriginalSale(net_sale_minor=2000,shipping_revenue_minor=0,
                          commission_bps_snapshot=1000,original_commission_minor=200)
    old=RefundProgress(card_refunded_minor=0,shipping_refunded_minor=0,
                       commission_reversed_minor=0)
    for n,amount,ret in ((301,500,False),(302,700,False),(303,800,True)):
        delta=calculate_refund_ledger_delta(
            original,old,RequestedRefund(card_refund_minor=amount,
                                         return_to_inspection=ret))
        _run(db,build_card_refund_batch(_refund(n=n,amount=amount,returned=ret)))
        m=_money(db)
        assert m["REFUND"]==-delta.cumulative_card_refunded_minor
        assert m["COMMISSION_REVERSAL"]==delta.cumulative_commission_reversed_minor
        assert m["SALE_REVENUE"]==2000
        assert m["COMMISSION"]==-200
        old=RefundProgress(card_refunded_minor=delta.cumulative_card_refunded_minor,
                           shipping_refunded_minor=0,
                           commission_reversed_minor=delta.cumulative_commission_reversed_minor,
                           already_returned=ret,
                           inventory_status="INSPECTION" if ret else "SOLD")
    assert _version(db)==("INSPECTION",3,ITEM_C)
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==3
    assert db.execute("SELECT count(*) FROM candidate_outbox").fetchone()[0]==4
    assert set(r[0] for r in db.execute(
        "SELECT DISTINCT funds_status FROM candidate_ledger"))=={"PENDING"}


def test_full_refund_and_inspection_does_not_permanently_ban_resale(db):
    _sale(db)
    _run(db,build_card_refund_batch(_refund(amount=2000,returned=True)))
    assert _version(db)==("INSPECTION",3,ITEM_C)
    # This manual update is a TEST FIXTURE simulating future audited review.
    # No candidate production Worker exposes an unreviewed reapproval route.
    db.execute("UPDATE candidate_inventory SET status='APPROVED',version=version+1 "
               "WHERE id=? AND status='INSPECTION'",(STOCK_C,))
    _sale(db,order=U(42),item=U(23),version=4,reference="paid-1001")
    assert _version(db)==("SOLD",5,U(23))
    assert db.execute("SELECT count(*) FROM candidate_order_items").fetchone()[0]==2
    assert db.execute("SELECT count(*) FROM candidate_ledger WHERE entry_type='SALE_REVENUE'").fetchone()[0]==2
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(
            _refund(n=305,amount=1,returned=True,item=ITEM_C,order=ORDER)))
    assert _version(db)==("SOLD",5,U(23))


def test_founder_refund_never_creates_any_commission_reversal(db):
    _sale(db,item=ITEM_F,stock=STOCK_F,owner=OWNER_F,cost=100,rate=0,price=1000)
    _run(db,build_card_refund_batch(
        _refund(item=ITEM_F,stock=STOCK_F,owner=OWNER_F,amount=1000,
                returned=True)))
    assert _money(db,ITEM_F)=={"SALE_REVENUE":1000,"REFUND":-1000}
    assert _version(db,STOCK_F)==("INSPECTION",3,ITEM_F)


def test_cumulative_half_penny_rounding_and_no_zero_commission_rows(db):
    _sale(db,price=5)
    for n,amount in ((301,1),(302,1),(303,3)):
        _run(db,build_card_refund_batch(_refund(n=n,amount=amount)))
    assert _money(db)=={
        "SALE_REVENUE":5,"COMMISSION":-1,"REFUND":-5,
        "COMMISSION_REVERSAL":1,
    }
    assert db.execute(
        "SELECT count(*) FROM candidate_ledger WHERE entry_type='COMMISSION_REVERSAL'"
        ).fetchone()[0]==1


def test_source_replay_and_changed_payload_cannot_post_twice(db):
    _sale(db)
    e=_refund()
    _run(db,build_card_refund_batch(e))
    previous=dict(db.execute("SELECT * FROM candidate_card_refunds WHERE id=?",(e.id,)).fetchone())
    assert classify_card_refund_replay(previous,e)=="REPLAY"
    assert classify_card_refund_replay(previous,replace(e,payload_sha256="c"*64))=="CONFLICT"
    assert classify_card_refund_replay(previous,replace(e,card_amount_minor=999))=="CONFLICT"
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(e))
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(
            replace(e,id=U(309),card_amount_minor=999)))
    assert _money(db)["REFUND"]==-500
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==1


@pytest.mark.parametrize("changed",[
    {"owner_id":OWNER_F},{"inventory_id":STOCK_F},{"order_id":U(88)},
    {"order_item_id":U(77)},{"source":"EBAY"},{"card_amount_minor":2001},
])
def test_wrong_owner_lineage_source_and_over_refund_fail_closed(db,changed):
    _sale(db)
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(replace(_refund(),**changed)))
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==0
    assert _money(db)=={"SALE_REVENUE":2000,"COMMISSION":-200}
    assert _version(db)==("SOLD",2,ITEM_C)


def test_full_card_refund_requires_explicit_full_amount_for_restocks(db):
    _sale(db)
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(
            _refund(amount=1999,returned=True)))
    assert _version(db)==("SOLD",2,ITEM_C)
    _run(db,build_card_refund_batch(_refund(amount=1999)))
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(_refund(n=302,amount=2,returned=True)))
    _run(db,build_card_refund_batch(_refund(n=303,amount=1,returned=True)))
    assert _version(db)==("INSPECTION",3,ITEM_C)


def test_late_outbox_failure_rolls_back_refund_ledger_stock_and_history(db):
    _sale(db)
    refund=_refund(amount=2000,returned=True)
    db.execute(
        "INSERT INTO candidate_outbox "
        "(id,order_id,event_type,payload_sha256,status,created_at) "
        "VALUES(?,?,'REFUND_POSTED',?,'PENDING',?)",
        ("refund:"+refund.id,ORDER,HASH,NOW))
    with pytest.raises(sqlite3.IntegrityError):
        _run(db,build_card_refund_batch(refund))
    assert _version(db)==("SOLD",2,ITEM_C)
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==0
    assert _money(db)=={"SALE_REVENUE":2000,"COMMISSION":-200}


def test_old_ledger_tampering_blocks_new_refund(db):
    _sale(db)
    # Candidate lacks a public direct-ledger writer, but test an invalid
    # append-only source row from hypothetical damaged migration data.
    db.execute("INSERT INTO candidate_ledger "
      "(id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,"
      " funds_status,source_key,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
      ("forged",OWNER_C,ORDER,ITEM_C,"COMMISSION_REVERSAL",1,"GBP",
       "PENDING","forged",NOW))
    with pytest.raises(sqlite3.IntegrityError,match="prior ledger"):
        _run(db,build_card_refund_batch(_refund()))
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==0


def test_missing_historical_refund_debit_blocks_followup(db):
    _sale(db)
    first=_refund(amount=500)
    _run(db,build_card_refund_batch(first))
    # Simulate historical ledger corruption by withholding one expected
    # source debit in an isolated fixture. No production deletion route exists.
    db.execute("DROP TRIGGER candidate_ledger_no_delete")
    db.execute(
        "DELETE FROM candidate_ledger WHERE source_key=?",
        ("refund:"+first.id,))
    with pytest.raises(sqlite3.IntegrityError,match="prior ledger"):
        _run(db,build_card_refund_batch(_refund(n=302,amount=100)))
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==1
    assert _version(db)==("SOLD",2,ITEM_C)


def test_refund_events_and_finance_ledger_are_immutable(db):
    _sale(db)
    _run(db,build_card_refund_batch(_refund()))
    for sql in (
        "UPDATE candidate_card_refunds SET card_amount_minor=1",
        "DELETE FROM candidate_card_refunds",
        "UPDATE candidate_ledger SET amount_minor=99 WHERE entry_type='REFUND'",
        "DELETE FROM candidate_ledger WHERE entry_type='COMMISSION_REVERSAL'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)


@pytest.mark.parametrize("changes",[
    {"card_amount_minor":0},{"card_amount_minor":True},
    {"card_amount_minor":-10},{"return_to_inspection":1},
    {"payload_sha256":"not-a-hash"},{"source_reference":"x'; DROP TABLE; --"},
    {"source":"UNKNOWN"},{"occurred_at":"2026-11-09 10:00:00"},
])
def test_invalid_external_refund_inputs_generate_no_statement(changes):
    with pytest.raises(CandidateSaleGuard):
        build_card_refund_batch(replace(_refund(),**changes))


def test_only_card_amount_posted_and_cannot_guess_shipping_refund(db):
    _sale(db)
    refunds=build_card_refund_batch(_refund())
    assert len(refunds)==1
    assert refunds[0].sql.startswith("INSERT INTO candidate_card_refunds")
    assert "shipping" not in refunds[0].sql.lower()
    assert refunds[0].sql.count("?")==len(refunds[0].params)
    assert "DROP" not in refunds[0].sql
    assert db.execute("SELECT count(*) FROM candidate_card_refunds").fetchone()[0]==0
    assert db.execute("SELECT count(*) FROM candidate_ledger").fetchone()[0]==2
