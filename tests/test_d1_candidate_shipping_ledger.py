"""Actual-source-shaped synthetic financial ledger replay in isolated SQLite.

The live Supabase source (9 Nov) has 3 per-item card/refund pairs, 3 per-item
shipping/return pairs and 1 owner-linked payment fee. This test uses only
counts/penny totals, NEVER real owner identifiers or customer data.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
from uuid import UUID

import pytest

from app.d1_candidate_sale import SaleEvent,SaleLine,build_paid_sale_batch,CandidateSaleGuard
from app.d1_candidate_refund_ledger import CandidateCardRefundEvent,build_card_refund_batch
from app.d1_candidate_shipping_ledger import (
    CandidateFinancialEvidence,build_financial_evidence_batch,
    classify_financial_evidence_replay,
)

ROOT=Path(__file__).resolve().parents[1]/"database/cloudflare_d1/candidate"
SCHEMA=[(ROOT/file).read_text() for file in
        ("0001_atomic_sale.sql","0002_atomic_card_refunds.sql","0003_shipping_payment.sql")]
U=lambda n:str(UUID(int=n))
OWNER_F,OWNER_C=U(11),U(12)
NOW="2026-11-09T10:00:00Z"
HASH="a"*64


def apply(db,statements):
    db.execute("BEGIN IMMEDIATE")
    try:
        for stmt in statements:
            db.execute(stmt.sql,stmt.params)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


@pytest.fixture
def db():
    con=sqlite3.connect(":memory:",isolation_level=None)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    for schema in SCHEMA:
        con.executescript(schema)
    con.execute("INSERT INTO candidate_owners VALUES(?,'FOUNDER',1,1,0)",(OWNER_F,))
    con.execute("INSERT INTO candidate_owners VALUES(?,'CONSIGNOR',NULL,1,1000)",(OWNER_C,))
    yield con
    con.close()


def sale(db,n,*,owner=OWNER_F,price=83,rate=0):
    order,item,stock=U(1000+n),U(2000+n),U(3000+n)
    db.execute(
        "INSERT INTO candidate_inventory "
        "(id,inventory_code,catalogue_id,owner_id,status,sale_intent,"
        "version,acquisition_cost_minor,currency) "
        "VALUES(?,?,?,?, 'APPROVED','FOR_SALE',1,0,'GBP')",
        (stock,"INV-"+str(n),U(4000+n),owner))
    event=SaleEvent(order_id=order,source="SHOPIFY",source_reference="paid-"+str(n),
         webhook_id="hook-"+str(n),shop_domain="droprate.myshopify.com",
         payload_sha256=HASH,placed_at=NOW,
         lines=(SaleLine(id=item,inventory_id=stock,owner_id=owner,
                    expected_inventory_version=1,sale_price_minor=price,
                    discount_minor=0,cost_basis_minor=0,
                    commission_bps_snapshot=rate),))
    apply(db,build_paid_sale_batch(event))
    return order,item,stock


def evidence(kind,n,order,item,owner=OWNER_F,*,amount=499,source="SHOPIFY",
             reference=None,payload=HASH):
    return CandidateFinancialEvidence(
        id=U(5000+n),kind=kind,source=source,
        source_reference=reference or "evidence-"+str(n),
        order_id=order,order_item_id=item,owner_id=owner,
        amount_minor=amount,payload_sha256=payload,occurred_at=NOW,
    )


def cardrefund(n,order,item,stock,owner=OWNER_F):
    return CandidateCardRefundEvent(
        id=U(9000+n),source="SHOPIFY",source_reference="card-refund-"+str(n),
        order_id=order,order_item_id=item,inventory_id=stock,
        owner_id=owner,card_amount_minor=83,return_to_inspection=True,
        payload_sha256=HASH,occurred_at=NOW,
    )


def totals(db):
    return {r["entry_type"]:int(r["amount"]) for r in db.execute(
        "SELECT entry_type,sum(amount_minor) AS amount "
        "FROM candidate_ledger GROUP BY entry_type")}


def test_actual_source_totals_can_be_replayed_without_guessing_owner_data(db):
    # Live source aggregate, 9 Nov: +249/-249 card, +1497/-1497 shipping,
    # -36 payment fee, all pending. Synthetic IDs only.
    for n in (1,2,3):
        order,item,stock=sale(db,n)
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_ALLOCATION",n,order,item,amount=499)))
        apply(db,build_card_refund_batch(cardrefund(n,order,item,stock)))
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_REFUND",100+n,order,item,amount=499)))
        assert db.execute(
            "SELECT status FROM candidate_inventory WHERE id=?",(stock,)
            ).fetchone()[0]=="INSPECTION"
        if n==1:
            apply(db,build_financial_evidence_batch(
                evidence("PAYMENT_FEE",200+n,order,item,amount=36)))
    assert totals(db)=={
        "SALE_REVENUE":249,"REFUND":-249,
        "SHIPPING_REVENUE":1497,"SHIPPING_REFUND":-1497,
        "PAYMENT_FEE":-36,
    }
    assert db.execute("SELECT count(*) FROM candidate_ledger").fetchone()[0]==13
    assert set(r[0] for r in db.execute(
        "SELECT distinct funds_status FROM candidate_ledger"))=={"PENDING"}
    assert db.execute("SELECT count(*) FROM candidate_outbox").fetchone()[0]==13


def test_mixed_founder_consignor_shipping_and_fee_owner_isolation(db):
    a= sale(db,1)
    b= sale(db,2,owner=OWNER_C,price=2000,rate=1000)
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_ALLOCATION",1,a[0],a[1],amount=499)))
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_ALLOCATION",2,b[0],b[1],OWNER_C,amount=499)))
    apply(db,build_financial_evidence_batch(
        evidence("PAYMENT_FEE",3,b[0],b[1],OWNER_C,amount=36)))
    entries=[tuple(r) for r in db.execute(
        "SELECT owner_id,entry_type,amount_minor FROM candidate_ledger "
        "WHERE entry_type IN ('SHIPPING_REVENUE','PAYMENT_FEE') "
        "ORDER BY owner_id,entry_type")]
    assert entries==[
        (OWNER_F,"SHIPPING_REVENUE",499),
        (OWNER_C,"PAYMENT_FEE",-36),
        (OWNER_C,"SHIPPING_REVENUE",499),
    ]


def test_shipping_refund_can_be_partial_but_never_exceed_original(db):
    order,item,_=sale(db,1)
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_ALLOCATION",1,order,item)))
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_REFUND",2,order,item,amount=250)))
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_REFUND",3,order,item,amount=249)))
    assert totals(db)["SHIPPING_REFUND"]==-499
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_REFUND",4,order,item,amount=1)))
    assert totals(db)["SHIPPING_REFUND"]==-499


def test_shipping_refund_with_no_source_allocation_fails_closed(db):
    order,item,_=sale(db,1)
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_REFUND",5,order,item,amount=499)))
    assert "SHIPPING_REFUND" not in totals(db)


@pytest.mark.parametrize("kind",["SHIPPING_ALLOCATION","SHIPPING_REFUND","PAYMENT_FEE"])
def test_cross_owner_source_and_original_lineage_are_not_trusted(db,kind):
    order,item,_=sale(db,1)
    if kind=="SHIPPING_REFUND":
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_ALLOCATION",1,order,item)))
    bad=evidence(kind,2,order,item,owner=OWNER_C,amount=100)
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(bad))
    assert db.execute("SELECT count(*) FROM candidate_outbox").fetchone()[0] in (1,2)


def test_source_replay_and_changed_amount_payload_are_conflicts(db):
    order,item,_=sale(db,1)
    e=evidence("SHIPPING_ALLOCATION",1,order,item)
    apply(db,build_financial_evidence_batch(e))
    row=dict(db.execute(
        "SELECT * FROM candidate_shipping_allocations WHERE id=?",(e.id,)).fetchone())
    assert classify_financial_evidence_replay(row,e)=="REPLAY"
    assert classify_financial_evidence_replay(row,replace(e,payload_sha256="b"*64))=="CONFLICT"
    assert classify_financial_evidence_replay(row,replace(e,amount_minor=999))=="CONFLICT"
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(
            replace(e,id=U(5011),amount_minor=999)))
    assert totals(db)["SHIPPING_REVENUE"]==499


def test_late_outbox_collision_rolls_back_shipping_ledger_and_allocation(db):
    order,item,_=sale(db,1)
    e=evidence("SHIPPING_ALLOCATION",1,order,item)
    db.execute("INSERT INTO candidate_outbox "
        "(id,order_id,event_type,payload_sha256,status,created_at) "
        "VALUES(?,?,'SHIPPING_ALLOCATED',?,'PENDING',?)",
        ("shipping:"+e.id,order,HASH,NOW))
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(e))
    assert db.execute("SELECT count(*) FROM candidate_shipping_allocations").fetchone()[0]==0
    assert "SHIPPING_REVENUE" not in totals(db)


def test_existing_shipping_ledger_tampering_blocks_future_shipping_refund(db):
    order,item,_=sale(db,1)
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_ALLOCATION",1,order,item)))
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_REFUND",2,order,item,amount=100)))
    db.execute("INSERT INTO candidate_ledger "
      "(id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,"
      " funds_status,source_key,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
      ("forged",OWNER_F,order,item,"SHIPPING_REFUND",-1,"GBP","PENDING",
       "forged",NOW))
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_REFUND",3,order,item,amount=100)))
    assert db.execute("SELECT count(*) FROM candidate_shipping_refunds").fetchone()[0]==1


def test_payment_fees_require_source_amount_and_original_owner(db):
    order,item,_=sale(db,1)
    with pytest.raises(sqlite3.IntegrityError):
        apply(db,build_financial_evidence_batch(
            evidence("PAYMENT_FEE",1,order,item,amount=600)))
    apply(db,build_financial_evidence_batch(
        evidence("PAYMENT_FEE",2,order,item,amount=36)))
    assert totals(db)["PAYMENT_FEE"]==-36
    assert db.execute("SELECT count(*) FROM candidate_payment_fees").fetchone()[0]==1


@pytest.mark.parametrize("table",[
    "candidate_shipping_allocations",
    "candidate_shipping_refunds",
    "candidate_payment_fees",
])
def test_all_financial_evidence_is_append_only(db,table):
    order,item,_=sale(db,1)
    apply(db,build_financial_evidence_batch(
        evidence("SHIPPING_ALLOCATION",1,order,item)))
    if table=="candidate_shipping_refunds":
        apply(db,build_financial_evidence_batch(
            evidence("SHIPPING_REFUND",2,order,item,amount=1)))
    if table=="candidate_payment_fees":
        apply(db,build_financial_evidence_batch(
            evidence("PAYMENT_FEE",3,order,item,amount=1)))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"UPDATE {table} SET amount_minor=1")


@pytest.mark.parametrize("changed",[
    {"kind":"RAW_SQL"},{"source":"OTHER"},
    {"amount_minor":0},{"amount_minor":-1},{"amount_minor":True},
    {"amount_minor":10000000000001},{"source_reference":"'; DROP TABLE candidate_ledger;--"},
    {"payload_sha256":"invalid"},{"occurred_at":"2026-11-09 10:00"},
])
def test_invalid_unverified_inputs_do_not_generate_sql(changed):
    event=evidence("SHIPPING_ALLOCATION",1,U(4),U(5))
    with pytest.raises(CandidateSaleGuard):
        build_financial_evidence_batch(replace(event,**changed))
