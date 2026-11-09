"""Fail-closed, READ-ONLY finance reconciliation for the private operational D1 shadow.

This is not a D1 financial writer, a payment system, or cutover approval.
Read a consistent PostgreSQL snapshot, require exact old-source hash parity
in D1, then prove D1's *typed* finance projections preserve all amounts/owners.
Neither row identifiers, owner balances nor raw financial values are emitted.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
import json
import os
import re

from d1_operational_source_stage import (
    ACCOUNT, DB_NAME, TARGETS, D1Client, source_capture, _d1_query, _map_row,
    StageGuard,
)
from d1_operational_source_delta_watch import (
    verify_shadow, SnapshotDriftGuard, UUID_RE,
)
from d1_remote_catalogue_pilot import PilotError

FINANCE_TABLES = (
    "owners", "owner_memberships", "inventory_items", "orders",
    "order_items", "refund_events", "financial_ledger_entries",
    "shopify_webhook_events",
)

class FinancialGuard(ValueError):
    pass


class ClassifiedReadOnlyD1(D1Client):
    """Return a fixed schema-table label on remote D1 query failure.

    Cloudflare HTTP 400 can mean a query error, not only a token-scope error.
    Do not print SQL, parameters, source rows, identifiers or provider messages.
    """
    def query(self, database_id, statement, params=()):
        try:
            return super().query(database_id, statement, params)
        except PilotError as exc:
            # The shared D1 client exposes only allowlisted HTTP categories.
            # Never propagate provider messages or user/ledger identifiers.
            category_match = re.search(r"category=([A-Z_]+)\\Z",str(exc))
            category = (category_match.group(1)
                        if category_match and category_match.group(1) in {
                            "DAILY_ROW_READ_LIMIT", "DAILY_ROW_WRITE_LIMIT",
                            "SCHEMA_TABLE_MISSING", "SCHEMA_COLUMN_MISSING",
                            "D1_OVERLOADED", "ACCOUNT_STORAGE_LIMIT",
                            "UNCLASSIFIED",
                        } else "UNCLASSIFIED")
            known = {
                *[target for target,_ in TARGETS.values()],
                "ops_shadow_generations",
                "ops_shadow_table_receipts",
                "ops_shadow_catalogue_links",
            }
            names = re.findall(r"\bops_shadow_[a-z_]+\b",
                               statement if isinstance(statement,str) else "")
            label = next((name for name in names if name in known),
                         "UNKNOWN_SCHEMA_QUERY")
            raise FinancialGuard(
                "Private D1 read-only query rejected at "+label
                +"; category="+category) from None


def _minor(value, *, zero=True):
    if type(value) is not int or value < (0 if zero else 1) or value > 9_000_000_000_000_000:
        raise FinancialGuard("Invalid minor-unit amount")
    return value


def _bps_round(minor: int, bps: int) -> int:
    _minor(minor)
    if type(bps) is not int or not 0 <= bps <= 10000:
        raise FinancialGuard("Invalid commission basis points")
    # PostgreSQL round(numeric) rounds positive 0.5 away from zero.
    return (minor * bps + 5000) // 10000


def _indexed(captured: dict, name: str) -> dict:
    rows = captured.get(name)
    if not isinstance(rows, list):
        raise FinancialGuard("Financial source table missing")
    result = {}
    for entry in rows:
        if (not isinstance(entry, tuple) or len(entry) != 4
                or not isinstance(entry[1], dict) or entry[0] != entry[1].get("id")
                or not isinstance(entry[0], str) or not entry[0]
                or entry[0] in result):
            raise FinancialGuard("Malformed or duplicate financial source row")
        result[entry[0]] = entry[1]
    return result


def audit_source_finance(captured: dict) -> dict:
    """Cross-table financial invariants over one repeatable-read source snapshot.

    The *same* source is independently hash- and typed-column-checked in D1.
    All calculations are integers; no prices, names, IDs or balances are logged.
    """
    owners = _indexed(captured, "owners")
    memberships = _indexed(captured, "owner_memberships")
    inventory = _indexed(captured, "inventory_items")
    orders = _indexed(captured, "orders")
    items = _indexed(captured, "order_items")
    refunds = _indexed(captured, "refund_events")
    ledger = _indexed(captured, "financial_ledger_entries")
    webhooks = _indexed(captured, "shopify_webhook_events")

    for owner in owners.values():
        rate = owner.get("commission_bps")
        if (owner.get("owner_type") not in ("FOUNDER", "CONSIGNOR")
                or type(rate) is not int or not 0 <= rate <= 10000
                or (owner["owner_type"] == "FOUNDER" and rate != 0)):
            raise FinancialGuard("Owner commission configuration inconsistent")
    for member in memberships.values():
        if member.get("owner_id") not in owners:
            raise FinancialGuard("Membership owner lineage missing")
    for card in inventory.values():
        if card.get("owner_id") not in owners or card.get("currency") != "GBP":
            raise FinancialGuard("Inventory owner/currency lineage inconsistent")
    seen_orders = set()
    for order in orders.values():
        key = (order.get("source"), order.get("source_reference"))
        if (not all(isinstance(x,str) and x for x in key)
                or key in seen_orders or order.get("currency") != "GBP"):
            raise FinancialGuard("Duplicate/invalid external order key or currency")
        seen_orders.add(key)

    seen_pairs = set()
    for item in items.values():
        order_id, inventory_id, owner_id = (
            item.get("order_id"), item.get("inventory_id"), item.get("owner_id"))
        if (order_id not in orders or inventory_id not in inventory
                or owner_id not in owners
                or inventory[inventory_id].get("owner_id") != owner_id):
            raise FinancialGuard("Sale references wrong owner/inventory/order")
        pair = (order_id, inventory_id)
        if pair in seen_pairs:
            raise FinancialGuard("Physical unit allocated twice in one order")
        seen_pairs.add(pair)
        price = _minor(item.get("sale_price_minor"))
        discount = _minor(item.get("discount_minor"))
        net = _minor(item.get("net_sale_minor"))
        if discount > price or net != price - discount:
            raise FinancialGuard("Sale net does not match original price less discount")
        rate = item.get("commission_bps_snapshot")
        if (type(rate) is not int or not 0 <= rate <= 10000
                or (owners[owner_id]["owner_type"] == "FOUNDER" and rate != 0)
                or _bps_round(net, rate) != item.get("commission_minor")):
            raise FinancialGuard("Commission snapshot/rounding inconsistent")
    refund_totals = defaultdict(int)
    refund_keys = set()
    for refund in refunds.values():
        item_id = refund.get("order_item_id")
        if item_id not in items:
            raise FinancialGuard("Refund references missing original sale")
        original = items[item_id]
        if (refund.get("owner_id") != original["owner_id"]
                or refund.get("inventory_id") != original["inventory_id"]
                or refund.get("order_id") != original["order_id"]
                or refund.get("currency") != "GBP"):
            raise FinancialGuard("Refund owner or sale lineage mismatch")
        amount = _minor(refund.get("amount_minor"),zero=False)
        key = (item_id,refund.get("source_reference"))
        if not isinstance(key[1],str) or not key[1] or key in refund_keys:
            raise FinancialGuard("Duplicate or invalid refund idempotency key")
        refund_keys.add(key)
        refund_totals[item_id] += amount

    ledger_keys = set()
    by_type = defaultdict(lambda: defaultdict(list))
    shipping_by_item = defaultdict(int)
    balance_by_owner = defaultdict(int)
    for entry in ledger.values():
        owner_id, order_id, item_id = (
            entry.get("owner_id"),entry.get("order_id"),entry.get("order_item_id"))
        key = entry.get("source_key")
        amount = entry.get("amount_minor")
        typ = entry.get("entry_type")
        if (owner_id not in owners or type(amount) is not int or amount == 0
                or abs(amount) > 9_000_000_000_000_000
                or not isinstance(key,str) or not key or key in ledger_keys
                or entry.get("currency") != "GBP"
                or entry.get("funds_status") not in ("PENDING","AVAILABLE")):
            raise FinancialGuard("Financial ledger identity/value invalid")
        ledger_keys.add(key)
        # Order-level payment/fulfilment fees may have no order_item_id.
        # Validate debit/credit sign regardless of the line-link shape.
        positive = {"SALE_REVENUE","SHIPPING_REVENUE","COMMISSION_REVERSAL"}
        negative = {"COMMISSION","REFUND","SHIPPING_REFUND","PLATFORM_FEE",
                    "PAYMENT_FEE","SHIPPING_COST","FULFILMENT_MATERIAL_COST",
                    "PAYOUT"}
        if ((typ in positive and amount <= 0)
                or (typ in negative and amount >= 0)
                or (typ not in positive | negative | {"ADJUSTMENT"})):
            raise FinancialGuard("Invalid global financial ledger entry type or sign")
        if order_id is not None and order_id not in orders:
            raise FinancialGuard("Financial ledger order missing")
        if item_id is not None:
            if (item_id not in items or items[item_id]["owner_id"] != owner_id
                    or items[item_id]["order_id"] != order_id):
                raise FinancialGuard("Ledger item/owner/order lineage mismatch")
            by_type[item_id][typ].append(amount)
            if typ == "SHIPPING_REVENUE":
                if amount <= 0:
                    raise FinancialGuard("Invalid shipping revenue sign")
                shipping_by_item[item_id] += amount
        balance_by_owner[owner_id] += amount
    for item_id,item in items.items():
        entries = by_type[item_id]
        net = item["net_sale_minor"]
        sale = entries.get("SALE_REVENUE",[])
        # Original PG ledger rejects zero amounts; a zero-net item cannot
        # generate a sale-revenue entry and requires human review at cutover.
        if net <= 0 or sale != [net]:
            raise FinancialGuard("Missing/duplicate/nonmatching sale revenue")
        original_fee = item["commission_minor"]
        commissions = entries.get("COMMISSION",[])
        if commissions != ([-original_fee] if original_fee else []):
            raise FinancialGuard("Sale commission ledger does not match snapshot")
        refund_amounts = entries.get("REFUND",[])
        if any(x >= 0 for x in refund_amounts):
            raise FinancialGuard("Refund ledger has invalid sign")
        item_refunded = -sum(refund_amounts)
        if item_refunded != refund_totals[item_id] or item_refunded > net:
            raise FinancialGuard("Refund events and ledger exceed/mismatch item net")
        shipping_refunds = entries.get("SHIPPING_REFUND",[])
        if any(x >= 0 for x in shipping_refunds) or -sum(shipping_refunds) > shipping_by_item[item_id]:
            raise FinancialGuard("Shipping refund exceeds original shipping revenue")
        target_retained = _bps_round(net - item_refunded,
                                      item["commission_bps_snapshot"])
        expected_reversal = original_fee - target_retained
        reversals = entries.get("COMMISSION_REVERSAL",[])
        if any(x <= 0 for x in reversals) or sum(reversals) != expected_reversal:
            raise FinancialGuard("Commission reversal does not reconcile to refunds")
        for fee_type in ("PLATFORM_FEE","PAYMENT_FEE","SHIPPING_COST",
                         "FULFILMENT_MATERIAL_COST"):
            if any(x >= 0 for x in entries.get(fee_type,[])):
                raise FinancialGuard("Financial expense has wrong sign")
    seen_webhooks = set()
    for hook in webhooks.values():
        key = hook.get("webhook_id")
        if not isinstance(key,str) or not key or key in seen_webhooks:
            raise FinancialGuard("Duplicated Shopify webhook event identity")
        seen_webhooks.add(key)

    # This scope excludes payout requests, full event history, identity, and
    # complete financial relations. Zero drift does not imply cutover readiness.
    return {
        "owner_rows":len(owners),"membership_rows":len(memberships),
        "inventory_rows":len(inventory),"order_rows":len(orders),
        "order_item_rows":len(items),"refund_rows":len(refunds),
        "ledger_rows":len(ledger),"webhook_rows":len(webhooks),
        "distinct_owner_balances":len(balance_by_owner),
        "financial_invariants_verified":True,
    }


def audit_typed_d1(client, captured: dict) -> int:
    """Verify ALL finance-relevant typed D1 columns, not just original JSON SHA.

    Source original JSON and row hashes were independently checked first by
    verify_shadow. Catch e.g. a changed typed commission_minor or owner_id
    that would otherwise be invisible to the old source-hash-only gate.
    """
    if client.account_id != ACCOUNT:
        raise FinancialGuard("Unexpected Cloudflare D1 account")
    databases = [x for x in client.list_databases() if x.get("name")==DB_NAME]
    if len(databases)!=1 or not UUID_RE.fullmatch(databases[0].get("uuid","")):
        raise FinancialGuard("Unique private D1 operational database required")
    dbid = databases[0]["uuid"]
    generations = _d1_query(client,dbid,
        "SELECT g.generation_id,g.state,g.source_manifest_sha256 FROM ops_shadow_generations g "
        "WHERE g.state IN ('STAGING','PARITY_VERIFIED') AND "
        "(SELECT COUNT(*) FROM ops_shadow_table_receipts r WHERE r.generation_id=g.generation_id)=9 "
        "ORDER BY g.created_at DESC,g.generation_id DESC LIMIT 2")
    if not generations or len(generations)>2:
        raise FinancialGuard("Private verified D1 generation unavailable")
    generation = generations[0].get("generation_id")
    if not isinstance(generation,str) or not generation.startswith("src-"):
        raise FinancialGuard("Invalid private source generation")
    checked = 0
    for name in FINANCE_TABLES:
        target,columns = TARGETS[name]  # fixed internal whitelist, never caller SQL.
        observed = _d1_query(client,dbid,
            "SELECT "+",".join(columns)+f' FROM "{target}" '
            "WHERE generation_id=? ORDER BY id",[generation])
        by_id = {}
        for row in observed:
            if (not isinstance(row,dict) or set(row) != set(columns)
                    or not isinstance(row.get("id"),str) or row["id"] in by_id):
                raise FinancialGuard("D1 typed source row shape or identity invalid")
            by_id[row["id"]] = row
        source_rows = captured[name]
        if len(by_id) != len(source_rows):
            raise FinancialGuard("D1 typed financial row count differs from source")
        for key,record,raw,digest in source_rows:
            row = by_id.get(key)
            expected = _map_row(name,generation,record,raw,digest,{})
            if row is None or tuple(row[column] for column in columns)!=expected:
                raise FinancialGuard("D1 typed financial column differs from original source")
            checked += 1
    return checked


async def main() -> dict:
    dsn=os.environ.get("FULL_EXIT_PG_READONLY_DSN","").strip()
    account=os.environ.get("CLOUDFLARE_ACCOUNT_ID","").strip()
    token=os.environ.get("CLOUDFARE_D1_PILOT_TOKEN","").strip()
    if not dsn or account!=ACCOUNT or not token:
        raise FinancialGuard("Protected finance audit configuration missing")
    captured,_,catalogue = await source_capture(dsn)
    source = audit_source_finance(captured)
    client = ClassifiedReadOnlyD1(account,token)
    drift = verify_shadow(client,captured,catalogue)
    if drift.get("status")!="READ_ONLY_OPERATIONAL_D1_SNAPSHOT_PARITY" or drift.get("changed_or_missing_record_count")!=0:
        raise FinancialGuard("Existing private D1 source SHA or catalogue parity is stale")
    typed_count = audit_typed_d1(client,captured)
    # Recheck original SHA after typed-column scan to detect head/source race.
    after = verify_shadow(client,captured,catalogue)
    if after.get("status")!="READ_ONLY_OPERATIONAL_D1_SNAPSHOT_PARITY" or after.get("changed_or_missing_record_count")!=0:
        raise FinancialGuard("Financial source/D1 changed during independent audit")
    return {
        "status":"READ_ONLY_D1_FINANCE_TYPED_AND_SOURCE_PENNY_PARITY",
        **source,
        "private_d1_typed_rows_verified":typed_count,
        "source_original_sha_parity":True,
        "financial_scope_tables":len(FINANCE_TABLES),
        "full_financial_relation_coverage":False,
        "external_identity_replacement_verified":False,
        "production_finance_writer_switched":False,
        "payouts_or_payments_executed":0,
        "source_postgres_writes":0,
        "private_d1_writes":0,
        "supabase_retirement_authorized":False,
    }


if __name__=="__main__":
    try:
        print(json.dumps(asyncio.run(main()),sort_keys=True))
    except FinancialGuard as exc:
        # Messages are written solely from fixed internal table labels and
        # constant error classes; no dynamic record keys or SQL parameters.
        raise SystemExit("Protected finance parity blocked: "+str(exc)+"; NO CUTOVER") from None
    except (StageGuard,SnapshotDriftGuard,PilotError,ValueError,TypeError):
        raise SystemExit("Protected financial source/D1 parity unavailable; NO CUTOVER") from None
