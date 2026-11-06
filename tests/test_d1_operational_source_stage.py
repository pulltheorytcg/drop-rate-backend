"""Full-owner D1 shadow import contract: synthetic fixtures only, no production."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools import d1_operational_source_stage as job

SQL=Path("database/cloudflare_d1/0001_operational_shadow.sql").read_text()
H="a"*64


class FakeCloudflareD1:
    account_id=job.ACCOUNT
    def __init__(self):
        self.con=sqlite3.connect(":memory:")
        self.con.row_factory=sqlite3.Row
        self.con.executescript(SQL)
    def list_databases(self):
        return [{"name":job.DB_NAME,"uuid":"11111111-1111-4111-8111-111111111111"}]
    def query(self,dbid,sql,params=()):
        assert dbid=="11111111-1111-4111-8111-111111111111"
        cur=self.con.execute(sql,params)
        return {"results":[dict(x) for x in cur.fetchall()]},0.1
    def batch(self,dbid,queries):
        assert len(queries)<=8
        for entry in queries:
            assert len(entry["params"])<=72
            self.con.execute(entry["sql"],entry["params"])


def fixtures():
    owner={"id":"o1","display_name":"Founder","owner_type":"FOUNDER",
           "founder_slot":1,"active":True,"commission_bps":1000}
    member={"id":"m1","user_id":"u1","owner_id":"o1",
            "role":"PLATFORM_ADMIN","active":True}
    item={"id":"i1","inventory_code":"INV-000001","catalogue_id":"c1",
          "owner_id":"o1","acquisition_cost_minor":100,
          "market_value_minor":400,"store_price_minor":500,"currency":"GBP",
          "condition":"NM","grading_company":None,"grade":None,
          "certificate_number":None,"language":"English","location":"A1",
          "status":"SOLD","sale_intent":"FOR_SALE","version":1}
    order={"id":"order1","source":"SHOPIFY","source_reference":"shopify_1",
           "currency":"GBP","status":"PAID","placed_at":"2026-11-06T18:00:00Z"}
    line={"id":"line1","order_id":"order1","inventory_id":"i1",
          "owner_id":"o1","sale_price_minor":500,"discount_minor":0,
          "net_sale_minor":500,"cost_basis_minor":100,
          "commission_bps_snapshot":1000,"commission_minor":50,
          "sold_at":"2026-11-06T18:00:00Z"}
    refund={"id":"r1","owner_id":"o1","order_id":"order1",
            "order_item_id":"line1","inventory_id":"i1",
            "source_reference":"refund-1","amount_minor":100,
            "currency":"GBP","occurred_at":"2026-11-06T18:01:00Z"}
    ledger={"id":"l1","owner_id":"o1","order_id":"order1",
            "order_item_id":"line1","payout_request_id":None,
            "entry_type":"SALE","amount_minor":450,"currency":"GBP",
            "funds_status":"AVAILABLE","source_key":"order1:line1:sale",
            "occurred_at":"2026-11-06T18:00:00Z","available_at":None}
    webhook={"id":"w1","webhook_id":"shopify-webhook-1",
             "topic":"orders/paid","shop_domain":"store.myshopify.com",
             "payload_sha256":H,"status":"PROCESSED",
             "received_at":"2026-11-06T18:00:00Z"}
    media={"id":"media1","owner_id":"o1","inventory_id":"i1",
           "media_kind":"IMAGE","scope":"INVENTORY_ITEM","media_variant":"SLAB",
           "rights_status":"VERIFIED","approval_status":"APPROVED",
           "content_sha256":H}
    mirror={"id":"mirror1","media_asset_id":"media1",
            "object_key":"private/images/content","content_sha256":H}
    data={
       "owners":owner,"owner_memberships":member,"inventory_items":item,
       "orders":order,"order_items":line,"financial_ledger_entries":ledger,
       "refund_events":refund,"shopify_webhook_events":webhook,
       "media_assets":media,"media_object_mirrors":mirror
    }
    records={}
    for name,obj in data.items():
        payload=json.dumps(obj,separators=(",",":"))
        records[name]=job.capture_table([payload],name)
    return records


@pytest.fixture(autouse=True)
def small_floors(monkeypatch):
    monkeypatch.setattr(job,"FLOORS",{t:1 for t in job.TABLES})


def test_complete_real_table_destination_mapping_is_exhaustive():
    assert len(job.TABLES)==10
    assert len(job.ORDER)==9
    assert set(job.ORDER)==set(job.TARGETS)
    assert "financial_ledger_entries" in job.TARGETS
    assert "owner_memberships" in job.TARGETS
    assert "audit_events" not in job.TABLES
    assert "auth.users" not in job.TABLES
    assert job.MAX_D1_ROWS<=2500


def test_full_two_way_d1_parity_with_penny_balances():
    db=FakeCloudflareD1()
    result=job.stage(db,fixtures(),{"tables":["synthetic"]},{"c1":H})
    assert result["status"]=="PRIVATE_OPERATIONAL_D1_SOURCE_STAGED_NOT_LIVE"
    assert result["counts"]["inventory_items"]==1
    assert result["verified_table_receipts"]==9
    assert result["market_value_published"] is False
    assert result["production_read_switch"] is False
    assert result["r2_source_upload_verified_by_this_job"] is False
    assert db.con.execute("SELECT count(*) FROM ops_shadow_identity_map").fetchone()[0]==1
    assert db.con.execute("SELECT count(*) FROM ops_shadow_table_receipts").fetchone()[0]==9
    assert db.con.execute("SELECT r2_private_object_key FROM ops_shadow_media_assets").fetchone()[0] is None
    assert db.con.execute("SELECT sum(amount_minor) FROM ops_shadow_ledger").fetchone()[0]==450
    # A reproducible source snapshot is idempotent, no doubled money.
    assert job.stage(db,fixtures(),{"tables":["synthetic"]},{"c1":H})["verified_table_receipts"]==9
    assert db.con.execute("SELECT count(*) FROM ops_shadow_ledger").fetchone()[0]==1


def test_snapshot_short_count_fails_closed():
    with pytest.raises(job.StageGuard,match="floor"):
        job.capture_table([],"owners")


def test_duplicate_owner_or_inventory_source_key_fails_closed():
    for name in ("owners","inventory_items"):
        same=json.dumps({"id":"one"})
        with pytest.raises(job.StageGuard,match="Duplicate"):
            job.capture_table([same,same],name)


def test_cross_owner_sale_is_rejected_by_d1_triggers():
    fixture=fixtures()
    line=fixture["order_items"][0]
    line[1]["owner_id"]="some-other-owner"
    line[2]=json.dumps(line[1],separators=(",",":"))
    line[3]=job.sha(line[2])
    db=FakeCloudflareD1()
    with pytest.raises(sqlite3.IntegrityError):
        job.stage(db,fixture,{"tables":["synthetic"]},{"c1":H})


def test_negative_or_duplicate_source_receipt_is_never_accepted():
    db=FakeCloudflareD1()
    result=job.stage(db,fixtures(),{"tables":["synthetic"]},{"c1":H})
    assert result["source_business_writes"]==0
    with pytest.raises(sqlite3.IntegrityError):
        db.con.execute("""UPDATE ops_shadow_ledger SET amount_minor=0""")
