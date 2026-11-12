"""Live pricing health never confuses historic asks/guides with paid UK sales."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import pricing_health as health


NOW = datetime(2026, 11, 12, 19, 45, tzinfo=timezone.utc)
USER = UUID("11111111-1111-4111-8111-111111111111")

def inventory(**updates):
    result = dict(active_items=617, stored_value_items=244,
                  recently_updated_items=73,
                  latest_pricing_update_at=NOW-timedelta(hours=6))
    result.update(updates)
    return result

def history(**updates):
    row = dict(source="EBAY",observation_type="SOLD",
               total_observations=1083,ingested_24h=0,ingested_7d=0,
               normalized_uk_sold=0,normalized_uk_sold_ingested_24h=0,
               last_ingested_at=NOW-timedelta(days=11),
               last_sale_or_guide_at=NOW-timedelta(days=11),
               last_normalized_uk_sold_ingested_at=None)
    row.update(updates)
    return row

def guides(**updates):
    row=dict(source="CARDMARKET",observation_type="PRICE_GUIDE",
             total_observations=5238,ingested_24h=0,ingested_7d=0,
             normalized_uk_sold=0,normalized_uk_sold_ingested_24h=0,
             last_ingested_at=NOW-timedelta(days=4),
             last_sale_or_guide_at=NOW-timedelta(days=5))
    row.update(updates)
    return row

def run(**updates):
    row = dict(source="EBAY",status="FAILED",trigger_type="SCHEDULED",
               completed_at=NOW-timedelta(days=2),
               inserted_count=0,fetched_count=0,failed_mapping_count=1,
               errors=[{"password":"never leak secret"}],metadata={"seller":"private"})
    row.update(updates)
    return row

def summary(sold=None,guide=None,**settings):
    flags=dict(ingestion_enabled=False,ebay_legacy_refresh_enabled=False,
               catalogue_refresh_enabled=False,bulk_hold=True)
    flags.update(settings)
    return health.summarise_pricing_health(inventory(),
        [sold or history(),guide or guides()], [run()], now=NOW, **flags)


def test_real_live_baseline_reports_blocked_not_false_green():
    result = summary()
    assert result["overall_status"] == "BLOCKED"
    assert result["inventory"]["active_items"] == 617
    assert result["inventory"]["stored_value_items"] == 244
    assert result["inventory"]["missing_value_items"] == 373
    assert result["inventory"]["updated_last_7d"] == 73
    assert result["inventory"]["stored_coverage_pct"] == 39.5
    assert result["refresh_interval_seconds"] == 60
    sold = result["sources"][0]
    assert sold["stored_observations"] == 1083
    assert sold["normalized_uk_sold_observations"] == 0
    assert sold["status"] == "NOT_USED_BY_CURRENT_ASKING_MODEL"
    assert result["sources"][1]["role"] == "GUIDE_ONLY"
    assert result["sources"][1]["stored_observations"] == 5238
    assert result["sources"][1]["status"] == "STALE_CONTEXT"
    assert result["sources"][2]["role"] == "ASKING_DERIVED_MARKET_VALUE"
    assert result["sources"][3]["status"] == "NOT_USED_BY_CURRENT_ASKING_MODEL"
    assert result["automation"]["automatic_sold_value_publication_ready"] is False
    assert result["automation"]["unattended_product_research_verified"] is False
    assert {a["code"] for a in result["alerts"]} >= {
        "NO_CURRENT_ASKING_MARKET_VALUES", "CARDMARKET_GUIDES_STALE",
        "OPERATOR_BULK_HOLD",
    }
    assert "password" not in str(result)
    assert "'seller': 'private'" not in str(result)
    assert "'password': 'never leak secret'" not in str(result)


def test_fresh_unverified_legacy_sales_still_block_market_value():
    result = summary(sold=history(total_observations=3000,ingested_24h=3000,
               last_ingested_at=NOW-timedelta(hours=1),
               last_sale_or_guide_at=NOW-timedelta(hours=1)))
    assert result["overall_status"] == "BLOCKED"
    assert result["sources"][0]["new_observations_24h"] == 3000
    assert result["sources"][2]["status"] == "NO_CURRENT_ASKING_EVIDENCE"
    assert result["sources"][0]["new_normalized_24h"] == 0


def test_normalized_arrivals_are_distinguished_without_auto_publication():
    result = summary(sold=history(normalized_uk_sold=12,
                 normalized_uk_sold_ingested_24h=6,
                 last_normalized_uk_sold_ingested_at=NOW-timedelta(hours=2)),
                 ingestion_enabled=True,bulk_hold=False)
    assert result["sources"][0]["status"] == "NOT_USED_BY_CURRENT_ASKING_MODEL"
    assert result["overall_status"] == "BLOCKED"
    assert result["automation"]["automatic_sold_value_publication_ready"] is False
    assert any(a["code"]=="NO_CURRENT_ASKING_MARKET_VALUES" for a in result["alerts"])


def test_legacy_normalized_history_is_not_fresh():
    result = summary(sold=history(normalized_uk_sold=7,
              normalized_uk_sold_ingested_24h=0,
              last_normalized_uk_sold_ingested_at=NOW-timedelta(days=3)))
    assert result["sources"][0]["status"] == "NOT_USED_BY_CURRENT_ASKING_MODEL"
    assert result["overall_status"] == "BLOCKED"


def test_empty_stock_not_misrepresented_as_100_percent_coverage():
    result = health.summarise_pricing_health(
        inventory(active_items=0,stored_value_items=0,recently_updated_items=0),
        [],[],now=NOW,ingestion_enabled=False,
        ebay_legacy_refresh_enabled=False,catalogue_refresh_enabled=False,bulk_hold=False)
    assert result["inventory"]["stored_coverage_pct"] == 0
    assert result["inventory"]["missing_value_items"] == 0
    assert result["sources"][0]["stored_observations"] == 0


def test_query_sql_only_reads_real_source_data_and_metadata_revision():
    assert "tcg.inventory_items" in health.INVENTORY_SQL
    assert "tcg.market_observations" in health.SOURCES_SQL
    assert "provider_evidence" in health.SOURCES_SQL
    assert "source_country = 'GB'" in health.SOURCES_SQL
    assert "tcg.market_ingestion_runs" in health.RUNS_SQL
    assert "tcg.reference_asking_prices" in health.ASKING_SQL
    for sql in (health.INVENTORY_SQL,health.SOURCES_SQL,health.RUNS_SQL,health.ASKING_SQL):
        assert not any(term in sql.lower() for term in ("insert into","update tcg","delete from","create table"))
    assert "record" not in health._safe_run(run())


@pytest.mark.asyncio
async def test_founder_endpoint_uses_readonly_snapshot_roster_and_no_writes(monkeypatch):
    calls=[]
    class Connection:
        async def fetchrow(self,sql,*args):
            calls.append(("fetchrow",sql,args))
            if sql==health.ASKING_SQL:
                return {"historical_cache_records":4,"fresh_candidate_records":4,
                        "last_checked_at":NOW,"last_observed_at":NOW}
            assert sql==health.INVENTORY_SQL
            return inventory()
        async def fetch(self,sql,*args):
            calls.append(("fetch",sql,args))
            if sql==health.SOURCES_SQL:
                assert args==(health.VERIFIED_UK_NORMALIZATION_REVISION,)
                return [history(),guides()]
            assert sql==health.RUNS_SQL
            return [run()]
    @asynccontextmanager
    async def scoped(pool,user_id,request_id,*,readonly_snapshot=False):
        assert user_id==USER and readonly_snapshot is True
        calls.append(("readonly",request_id))
        yield Connection()
    async def founder(conn):
        calls.append(("founder_auth",))
        return {"business_allowed":True}
    monkeypatch.setattr(health,"user_connection",scoped)
    monkeypatch.setattr(health,"require_business_founder",founder)
    monkeypatch.setattr(health,"get_settings",lambda: SimpleNamespace(
        market_ingestion_enabled=False,ebay_market_refresh_enabled=False,
        catalogue_daily_refresh_enabled=False))
    monkeypatch.setattr(health,"operator_bulk_hold_requested",lambda:True)
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                        state=SimpleNamespace(request_id="price-health-test"))
    response=await health.live_pricing_health(req,SimpleNamespace(user_id=USER))
    assert response["overall_status"] == "DEGRADED"
    assert response["automation"]["asking_market_value_display_available"] is True
    assert calls[0][0]=="readonly"
    assert calls[1][0]=="founder_auth"
    assert len(calls)==6


@pytest.mark.asyncio
async def test_nonfounder_forbidden_before_data_retrieval(monkeypatch):
    calls=[]
    @asynccontextmanager
    async def scoped(pool,user_id,request_id,*,readonly_snapshot=False):
        assert readonly_snapshot is True
        yield object()
    async def reject(_):
        calls.append("checked")
        raise HTTPException(status_code=403,detail="Verified founder Business access required")
    monkeypatch.setattr(health,"user_connection",scoped)
    monkeypatch.setattr(health,"require_business_founder",reject)
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                        state=SimpleNamespace(request_id="price-health-deny"))
    with pytest.raises(HTTPException) as err:
        await health.live_pricing_health(req,SimpleNamespace(user_id=USER))
    assert err.value.status_code == 403
    assert calls==["checked"]


def test_fresh_asking_evidence_not_conflated_with_sold_proof():
    result = summary(asking={"historical_cache_records":14,
                              "fresh_candidate_records":6,
                              "last_observed_at":NOW-timedelta(minutes=10),
                              "last_checked_at":NOW-timedelta(minutes=5)},
                     bulk_hold=False)
    assert result["overall_status"] == "DEGRADED"
    assert result["sources"][2]["fresh_candidate_records"] == 6
    assert result["sources"][2]["status"] == "FRESH_CANDIDATES"
    assert result["automation"]["asking_market_value_model_enabled"] is True
    assert result["automation"]["asking_market_value_display_available"] is True
    assert result["automation"]["automatic_sold_value_publication_ready"] is False
    assert result["automation"]["asking_acquisition_automatically_scheduled"] is False
    assert all(a["code"] != "NO_CURRENT_ASKING_MARKET_VALUES" for a in result["alerts"])
    assert "UK asking prices" not in str(result["sources"][0])
