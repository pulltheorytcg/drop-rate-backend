"""No data or price publication when creating private D1 market schema."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sqlite3
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
spec=importlib.util.spec_from_file_location("d1_market_shadow_provision",
                                          ROOT/"tools"/"d1_market_shadow_provision.py")
assert spec and spec.loader
job=importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
SQL=(ROOT/"database/cloudflare_d1/0002_market_value_shadow.sql").read_text()


class FakeD1:
    account_id=job.ACCOUNT
    def __init__(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        self.dbid="11111111-1111-4111-8111-111111111111"
        self.mutations=0
    def list_databases(self):
        return [{"name":job.DB_NAME,"uuid":self.dbid}]
    def query(self,dbid,sql,params=()):
        assert dbid==self.dbid
        if sql.strip().upper().startswith("CREATE "):
            self.mutations+=1
        cursor=self.db.execute(sql,params)
        return {"results":[dict(x) for x in cursor.fetchall()]},0.1


def test_real_schema_is_create_only_and_has_market_source_gates():
    statements,names=job.parse_schema(SQL)
    assert statements and len(names)>10
    assert ("view","market_shadow_eligible_values") in names
    assert ("trigger","market_shadow_market_value_source_gate") in names
    assert all(x.strip().upper().startswith("CREATE ") for x in statements)


def test_private_schema_deploy_is_idempotent_zero_data_and_zero_live_price():
    api=FakeD1()
    first=job.provision(api,SQL)
    assert first["status"]=="PRIVATE_MARKET_D1_SCHEMA_CREATED_NO_DATA"
    assert first["expected_schema_objects"]==first["actual_schema_objects"]
    assert first["eligible_market_value_published"]==0
    assert first["guide_or_asking_prices_promoted"]==0
    assert first["production_reads_switched"] is False
    assert first["new_database_created"] is False
    assert api.db.execute("SELECT COUNT(*) FROM market_shadow_current_values").fetchone()[0]==0
    writes=api.mutations
    second=job.provision(api,SQL)
    assert second["status"]=="EXISTING_PRIVATE_MARKET_D1_SCHEMA_VERIFIED"
    assert api.mutations==writes


def test_missing_or_drifted_private_d1_fails_before_any_change():
    api=FakeD1()
    api.list_databases=lambda: []
    with pytest.raises(job.MarketShadowGuard,match="existing"):
        job.provision(api,SQL)
    assert api.mutations==0
    other=FakeD1()
    other.db.execute("CREATE TABLE market_shadow_unreviewed (id TEXT)")
    with pytest.raises(job.MarketShadowGuard,match="drift"):
        job.provision(other,SQL)
    assert other.mutations==0


def test_no_delete_insert_alter_or_unknown_name_in_source():
    for text in ("INSERT INTO market_shadow_generations VALUES('g')",
                 "DROP TABLE market_shadow_current_values",
                 "CREATE TABLE IF NOT EXISTS existing_live_prices(x INTEGER)",
                 "ALTER TABLE market_shadow_current_values DROP COLUMN price_status"):
        with pytest.raises(job.MarketShadowGuard):
            job.parse_schema(SQL+"\n"+text+";\n")


def test_wrong_cloudflare_account_fails():
    api=FakeD1()
    api.account_id="0"*32
    with pytest.raises(job.MarketShadowGuard,match="Wrong"):
        job.provision(api,SQL)
