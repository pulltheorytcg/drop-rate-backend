"""Remote D1 operational provisioning contract via in-memory fake Cloudflare API."""
import importlib.util
from pathlib import Path
import sqlite3
from uuid import UUID

import pytest

TOOL=Path(__file__).resolve().parents[1]/"tools"/"d1_operational_shadow_provision.py"
spec=importlib.util.spec_from_file_location("d1_operational_shadow_provision",TOOL)
assert spec and spec.loader
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SOURCE=Path("database/cloudflare_d1/0001_operational_shadow.sql").read_text()


class FakeD1:
    account_id=m.ACCOUNT
    path=f"/accounts/{m.ACCOUNT}/d1/database"

    def __init__(self, existing=5):
        self.existing=[
            {"name":f"legacy-reference-shadow-{i}",
             "uuid":str(UUID(int=i+1))}
            for i in range(existing)
        ]
        self.objects={}
        self.create_calls=0
        self.query_calls=0

    def list_databases(self):
        return list(self.existing)

    def call(self,method,path,data=None):
        assert method=="POST" and path==self.path
        assert data=={"name":m.DB_NAME}
        self.create_calls+=1
        uuid=str(UUID(int=987))
        self.existing.append({"name":m.DB_NAME,"uuid":uuid})
        self.objects[uuid]=sqlite3.connect(":memory:")
        return {"name":m.DB_NAME,"uuid":uuid},0.1

    def query(self,uuid,sql,params=()):
        self.query_calls+=1
        conn=self.objects[uuid]
        cursor=conn.execute(sql,params)
        if sql.lstrip().lower().startswith("select "):
            keys=[column[0] for column in cursor.description]
            rows=[dict(zip(keys,r)) for r in cursor.fetchall()]
        else:
            rows=[]
        return {"results":rows},1.0


def test_schema_parse_contains_d1_triggers_and_stable_financial_objects():
    statements,names=m.parse_schema(SOURCE)
    assert len(statements)==len(names)
    assert ("table","ops_shadow_ledger") in names
    assert ("trigger","ops_shadow_ledger_no_update") in names
    assert ("trigger","ops_shadow_refund_lineage_match") in names
    assert ("index","ops_shadow_one_active_reservation") in names
    assert not any(x.startswith("DROP ") or x.startswith("DELETE ")
                   for x in statements)


def test_real_sqlite_ddl_and_remote_schema_readback_in_one_isolated_db():
    client=FakeD1()
    report=m.provision(client,SOURCE,account_id=m.ACCOUNT)
    assert report["status"]=="PRIVATE_OPERATIONAL_D1_SCHEMA_PROVISIONED_NO_DATA"
    assert report["source_schema_sha256"]
    assert report["postgres_writes"]==0
    assert report["market_value_writes"]==0
    assert report["customer_data_imported"] is False
    assert report["production_finance_cutover"] is False
    assert client.create_calls==1
    uuid=next(x["uuid"] for x in client.existing if x["name"]==m.DB_NAME)
    count=client.objects[uuid].execute("SELECT COUNT(*) FROM ops_shadow_owners").fetchone()[0]
    assert count==0
    # Running again verifies the already-created schema without any write.
    again=m.provision(client,SOURCE,account_id=m.ACCOUNT)
    assert not again["new_database_created"]
    assert client.create_calls==1


def test_unknown_existing_schema_blocks_reuse():
    client=FakeD1()
    m.provision(client,SOURCE,account_id=m.ACCOUNT)
    uuid=next(x["uuid"] for x in client.existing if x["name"]==m.DB_NAME)
    client.objects[uuid].execute("DROP TABLE ops_shadow_table_receipts")
    with pytest.raises(m.ProvisionGuard,match="drift"):
        m.provision(client,SOURCE,account_id=m.ACCOUNT)
    assert client.create_calls==1


def test_reserved_slots_protected():
    client=FakeD1(existing=8)
    with pytest.raises(m.ProvisionGuard,match="slots"):
        m.provision(client,SOURCE,account_id=m.ACCOUNT)
    assert client.create_calls==0


def test_wrong_cloudflare_account_blocks_all_changes():
    client=FakeD1()
    with pytest.raises(m.ProvisionGuard,match="account"):
        m.provision(client,SOURCE,account_id="f"*32)
    assert client.create_calls==0


def test_destructive_second_statement_blocked_before_remote_contact():
    client=FakeD1()
    with pytest.raises(m.ProvisionGuard,match="CREATE"):
        m.provision(client,SOURCE+"\nDELETE FROM ops_shadow_owners;\n",account_id=m.ACCOUNT)
    assert client.create_calls==0


def test_unrelated_service_table_does_not_pass_prefix_validator():
    changed=SOURCE+"\nCREATE TABLE IF NOT EXISTS real_shopify_orders(id TEXT);"
    with pytest.raises(m.ProvisionGuard,match="Unscoped"):
        m.parse_schema(changed)


def test_incomplete_create_not_retried_or_deleted():
    client=FakeD1()
    original_query=client.query
    calls=[0]
    def fail_after_three(uuid,sql,params=()):
        calls[0]+=1
        if calls[0]>3:
            raise m.ProvisionGuard("Injected Cloudflare API error")
        return original_query(uuid,sql,params)
    client.query=fail_after_three
    with pytest.raises(m.ProvisionGuard,match="Injected"):
        m.provision(client,SOURCE,account_id=m.ACCOUNT)
    client.query=original_query
    with pytest.raises(m.ProvisionGuard,match="drift"):
        m.provision(client,SOURCE,account_id=m.ACCOUNT)
    assert client.create_calls==1
