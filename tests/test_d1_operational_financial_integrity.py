"""No-network production-shaped financial cutover blockers; zero money movement."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_operational_financial_integrity as finance
from d1_operational_source_stage import TARGETS, _map_row


def make_raw(items):
    """Construct source_capture's immutable (id, JSON, raw, original_SHA) tuples."""
    capture={}
    for name,rows in items.items():
        converted=[]
        for record in rows:
            raw=json.dumps(record,separators=(",",":"),sort_keys=True)
            converted.append((record["id"],record,raw,hashlib.sha256(raw.encode()).hexdigest()))
        capture[name]=sorted(converted,key=lambda x:x[0])
    return capture


def source_records():
    common={"currency":"GBP"}
    owners=[
        {"id":"owner-a","display_name":"Founder A","owner_type":"FOUNDER",
         "founder_slot":1,"active":True,"commission_bps":0},
        {"id":"owner-b","display_name":"Consignor","owner_type":"CONSIGNOR",
         "founder_slot":None,"active":True,"commission_bps":1000},
    ]
    members=[
        {"id":"membership-a","owner_id":"owner-a","user_id":"user-a","role":"OWNER","active":True},
        {"id":"membership-b","owner_id":"owner-b","user_id":"user-b","role":"OWNER","active":True},
    ]
    inventory=[]
    for suffix,owner in [("a","owner-a"),("b","owner-b")]:
        inventory.append({
            "id":"inventory-"+suffix,"inventory_code":"INV-"+suffix,
            "catalogue_id":"card-"+suffix,"owner_id":owner,"currency":"GBP",
            "acquisition_cost_minor":None,"market_value_minor":1000,
            "store_price_minor":1200,"condition":"Near Mint",
            "grading_company":None,"grade":None,"certificate_number":None,
            "language":"English","location":"BOX-A","status":"SOLD",
            "sale_intent":"FOR_SALE","version":2,
        })
    orders=[{"id":"order-1","source":"SHOPIFY","source_reference":"external-order-1",
             "status":"PARTIALLY_REFUNDED","currency":"GBP",
             "placed_at":"2026-11-09T00:00:00Z"}]
    items=[]
    for suffix,owner,price,fee,rate in [
        ("a","owner-a",1000,0,0),("b","owner-b",2000,200,1000)
    ]:
        items.append({
            "id":"line-"+suffix,"order_id":"order-1",
            "inventory_id":"inventory-"+suffix,"owner_id":owner,
            "sale_price_minor":price,"discount_minor":0,
            "net_sale_minor":price,"cost_basis_minor":0,
            "commission_bps_snapshot":rate,"commission_minor":fee,
            "sold_at":"2026-11-09T00:00:00Z",
        })
    refunds=[{
        "id":"refund-b","order_id":"order-1","order_item_id":"line-b",
        "inventory_id":"inventory-b","owner_id":"owner-b",
        "amount_minor":500,"currency":"GBP","source_reference":"refund-external-b",
        "occurred_at":"2026-11-09T00:10:00Z",
    }]
    def entry(key,owner,line,typ,amount):
        return {"id":"ledger-"+key,"owner_id":owner,"order_id":"order-1",
                "order_item_id":line,"payout_request_id":None,
                "entry_type":typ,"amount_minor":amount,
                "currency":"GBP","funds_status":"PENDING",
                "source_key":"source-"+key,
                "occurred_at":"2026-11-09T00:00:00Z","available_at":None}
    ledger=[
        entry("sale-a","owner-a","line-a","SALE_REVENUE",1000),
        entry("sale-b","owner-b","line-b","SALE_REVENUE",2000),
        entry("commission-b","owner-b","line-b","COMMISSION",-200),
        entry("refund-b","owner-b","line-b","REFUND",-500),
        entry("commission-reversal-b","owner-b","line-b","COMMISSION_REVERSAL",50),
        entry("shipping-a","owner-a","line-a","SHIPPING_REVENUE",150),
        entry("shipping-refund-a","owner-a","line-a","SHIPPING_REFUND",-100),
        entry("payment-fee-a","owner-a","line-a","PAYMENT_FEE",-30),
    ]
    hooks=[{"id":"hook-1","webhook_id":"external-123",
            "topic":"orders/paid","shop_domain":"drop-rate",
            "payload_sha256":"a"*64,"status":"PROCESSED",
            "received_at":"2026-11-09T00:00:00Z"}]
    return {
        "owners":owners,"owner_memberships":members,
        "inventory_items":inventory,"orders":orders,"order_items":items,
        "refund_events":refunds,"financial_ledger_entries":ledger,
        "shopify_webhook_events":hooks,
    }


def capture(**changes):
    records=source_records()
    for k,v in changes.items():
        records[k]=v
    return make_raw(records)


def test_multi_owner_sale_net_commission_refund_and_shipping_reconcile():
    result=finance.audit_source_finance(capture())
    assert result["financial_invariants_verified"] is True
    assert result["owner_rows"]==2
    assert result["order_rows"]==1 and result["order_item_rows"]==2
    assert result["ledger_rows"]==8 and result["refund_rows"]==1
    assert finance._bps_round(1,5000)==1  # PG numeric half-away-from-zero.
    assert finance._bps_round(5,1000)==1


@pytest.mark.parametrize("field,value",[
    ("owner_id","owner-b"),
    ("inventory_id","inventory-b"),
    ("order_id","nonexistent-order"),
])
def test_wrong_sale_lineage_fails_closed(field,value):
    records=source_records()
    records["order_items"][0][field]=value
    with pytest.raises(finance.FinancialGuard):
        finance.audit_source_finance(make_raw(records))


def test_founder_cannot_charge_marketplace_commission():
    records=source_records()
    records["order_items"][0]["commission_bps_snapshot"]=1000
    records["order_items"][0]["commission_minor"]=100
    with pytest.raises(finance.FinancialGuard,match="Commission snapshot"):
        finance.audit_source_finance(make_raw(records))


def test_commission_rounding_is_exact_integer_and_nonnegative():
    records=source_records()
    records["order_items"][1]["commission_minor"]=201
    with pytest.raises(finance.FinancialGuard,match="Commission snapshot"):
        finance.audit_source_finance(make_raw(records))


def test_refund_above_sale_net_is_rejected_even_when_shipping_exists():
    records=source_records()
    records["refund_events"][0]["amount_minor"]=2001
    records["financial_ledger_entries"][3]["amount_minor"]=-2001
    with pytest.raises(finance.FinancialGuard,match="Refund events and ledger"):
        finance.audit_source_finance(make_raw(records))


def test_refund_idempotency_reference_collision_fails_closed():
    records=source_records()
    dup=deepcopy(records["refund_events"][0])
    dup["id"]="refund-second"
    records["refund_events"].append(dup)
    with pytest.raises(finance.FinancialGuard,match="refund idempotency"):
        finance.audit_source_finance(make_raw(records))


def test_duplicate_ledger_source_key_cannot_double_pay():
    records=source_records()
    records["financial_ledger_entries"][1]["source_key"]=records["financial_ledger_entries"][0]["source_key"]
    with pytest.raises(finance.FinancialGuard,match="ledger identity"):
        finance.audit_source_finance(make_raw(records))


def test_wrong_owner_ledger_entry_fails_closed():
    records=source_records()
    records["financial_ledger_entries"][1]["owner_id"]="owner-a"
    with pytest.raises(finance.FinancialGuard,match="Ledger item/owner"):
        finance.audit_source_finance(make_raw(records))


def test_commission_reversal_must_match_postgres_calculation():
    records=source_records()
    records["financial_ledger_entries"][4]["amount_minor"]=51
    with pytest.raises(finance.FinancialGuard,match="Commission reversal"):
        finance.audit_source_finance(make_raw(records))


def test_wrong_shipping_refund_and_payment_fee_signs_fail():
    records=source_records()
    records["financial_ledger_entries"][6]["amount_minor"]=-151
    with pytest.raises(finance.FinancialGuard,match="Shipping refund"):
        finance.audit_source_finance(make_raw(records))
    records=source_records()
    records["financial_ledger_entries"][7]["amount_minor"]=30
    with pytest.raises(finance.FinancialGuard,match="global financial ledger"):
        finance.audit_source_finance(make_raw(records))
    # Fee records may be attached to an order but not to an individual item.
    records=source_records()
    records["financial_ledger_entries"][7]["order_item_id"]=None
    records["financial_ledger_entries"][7]["amount_minor"]=30
    with pytest.raises(finance.FinancialGuard,match="global financial ledger"):
        finance.audit_source_finance(make_raw(records))


def test_webhook_event_idempotency_collision_is_rejected():
    records=source_records()
    new=deepcopy(records["shopify_webhook_events"][0])
    new["id"]="hook-2"
    records["shopify_webhook_events"].append(new)
    with pytest.raises(finance.FinancialGuard,match="webhook"):
        finance.audit_source_finance(make_raw(records))


class FakeCloud:
    account_id=finance.ACCOUNT
    dbid="12345678-1234-1234-1234-1234567890ab"
    def __init__(self,captured,*,tamper=None):
        self.data=captured
        self.tamper=tamper
    def list_databases(self):
        return [{"name":finance.DB_NAME,"uuid":self.dbid}]
    def query(self,dbid,sql,params=()):
        assert dbid==self.dbid
        if "FROM ops_shadow_generations" in sql:
            return ({"results":[{
                "generation_id":"src-test-finance",
                "state":"PARITY_VERIFIED",
                "source_manifest_sha256":"a"*64
            }]},0)
        table=re.search(r'FROM "(ops_shadow_[a-z_]+)"',sql)
        assert table,sql
        name=next(n for n in finance.FINANCE_TABLES
                  if TARGETS[n][0]==table.group(1))
        _,columns=TARGETS[name]
        rows=[]
        for key,data,raw,digest in self.data[name]:
            vals=_map_row(name,"src-test-finance",data,raw,digest,{})
            record=dict(zip(columns,vals))
            if self.tamper is not None and name==self.tamper[0] and key==self.tamper[1]:
                record[self.tamper[2]]=self.tamper[3]
            rows.append(record)
        return ({"results":rows},0)


def test_d1_typed_finance_matches_source_even_when_json_hashes_match():
    src=capture()
    assert finance.audit_typed_d1(FakeCloud(src),src)==(
        len(src["owners"])+len(src["owner_memberships"])+
        len(src["inventory_items"])+len(src["orders"])+
        len(src["order_items"])+len(src["refund_events"])+
        len(src["financial_ledger_entries"])+len(src["shopify_webhook_events"])
    )


def test_tampered_d1_typed_owner_amount_and_commission_caught():
    src=capture()
    for table,key,field,value in [
        ("financial_ledger_entries","ledger-sale-b","amount_minor",999999),
        ("financial_ledger_entries","ledger-sale-a","owner_id","owner-b"),
        ("order_items","line-b","commission_minor",0),
        ("inventory_items","inventory-b","owner_id","owner-a"),
    ]:
        with pytest.raises(finance.FinancialGuard,match="typed financial column"):
            finance.audit_typed_d1(FakeCloud(src,tamper=(table,key,field,value)),src)


def test_missing_or_duplicate_d1_typed_rows_fail_closed():
    src=capture()
    bad=deepcopy(src)
    bad["financial_ledger_entries"]=bad["financial_ledger_entries"][:-1]
    with pytest.raises(finance.FinancialGuard):
        finance.audit_typed_d1(FakeCloud(bad),src)


def test_wrong_cloudflare_account_refused_before_read():
    src=capture()
    class WrongCloud(FakeCloud):
        account_id="wrong"
    with pytest.raises(finance.FinancialGuard,match="account"):
        finance.audit_typed_d1(WrongCloud(src),src)
