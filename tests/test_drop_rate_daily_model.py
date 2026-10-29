"""Drop Rate's daily model must be DST-safe, variant-isolated and read-only by default."""
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest

from app import drop_rate_daily_model as model
from app.reference_baseline_model import PeerGuide,Printing,ordinary_peer_baseline

WINTER=datetime(2026,10,29,4,tzinfo=timezone.utc)
SUMMER=datetime(2026,7,10,3,tzinfo=timezone.utc)


def _ref(**fields):
    data=dict(
      provider="Bandai Official",system_code="DRAGON_BALL_SUPER_MASTERS",
      language="English",provider_id="base-001",set_id="BT1",
      name="Sample card",card_number="BT1-001",rarity="Common[C]",
      image_url="https://www.dbs-cardgame.com/card.jpg",
      set_name="Galactic Battle",cursor="sample-cursor",prior_source=None,
    )
    return {**data,**fields}


def _peer_row(n,price):
    return dict(
       provider="Bandai Official",system_code="DRAGON_BALL_SUPER_MASTERS",
       language="English",provider_id=f"base-{n:03d}",set_id="BT1",
       card_number=f"BT1-{n:03d}",rarity="Common[C]",
       detail_minor=price,detail_at=WINTER,detail_source="CARDMARKET_BULK_SINGLES",
       catalogue_minor=None,catalogue_at=None,catalogue_source=None,
    )


def test_exact_uk_four_am_winters_and_summers_including_dst():
    assert model.uk_daily_pricing_slot(WINTER)==WINTER
    assert model.uk_daily_pricing_slot(SUMMER)==SUMMER
    assert model.uk_daily_pricing_slot(WINTER-timedelta(minutes=1))==WINTER-timedelta(days=1)
    assert model.uk_daily_pricing_slot(SUMMER-timedelta(minutes=1))==SUMMER-timedelta(days=1)
    with pytest.raises(ValueError):
        model.uk_daily_pricing_slot(datetime(2026,10,29,4))


def test_daily_job_is_due_once_after_four_and_revision_or_retry():
    before=WINTER-timedelta(minutes=1)
    assert not model.daily_model_due(None,before,revision=11)
    assert model.daily_model_due(None,WINTER,revision=11)
    run=dict(started_at=WINTER,status="COMPLETE",report={"importer_revision":11})
    assert not model.daily_model_due(run,WINTER+timedelta(hours=1),revision=11)
    assert model.daily_model_due(run,WINTER+timedelta(minutes=1),revision=12)
    assert model.daily_model_due({**run,"status":"FAILED"},WINTER+timedelta(hours=2),revision=11)
    assert not model.daily_model_due({**run,"status":"FAILED"},WINTER+timedelta(minutes=10),revision=11)


def test_sql_does_not_pull_naruto_promos_parallel_or_prepriced_external_records():
    sql=model.CANDIDATE_SQL
    assert "'DROP_RATE_COMPUTED_MARKET_V1'" in sql
    assert "coalesce(p.market_value_minor,0)<=0" in sql
    assert "provider_id=r.card_number" in sql
    assert "r.card_number ~ '^BT" in sql
    assert "NARUTO" not in sql
    assert "limit $2" in sql.lower()


def test_db_peer_cannot_be_model_backfed_into_itself():
    good=model._peer(_peer_row(2,5),WINTER)
    assert good and good.price_gbp_minor==5
    assert model._peer({**_peer_row(2,5),"detail_source":model.SOURCE},WINTER) is None
    assert model._peer({**_peer_row(2,5),"detail_at":WINTER-timedelta(days=8)},WINTER) is None
    assert model._peer({**_peer_row(2,5),"detail_minor":0},WINTER) is None


def test_quote_retains_source_identity_and_store_floor_without_inflating_value():
    target=_ref()
    target_printing=model._printing(target)
    peers=[
        PeerGuide(Printing("Bandai Official","DRAGON_BALL_SUPER_MASTERS","BT1",
                          f"base-{i:03}","English","STANDARD","C"),
                  minor,WINTER,"CARDMARKET_BULK_SINGLES")
        for i,minor in [(2,2),(3,3),(4,4),(5,5),(6,6),(7,6)]]
    estimate=ordinary_peer_baseline(target_printing,peers,now=WINTER)
    assert estimate is not None
    quote=model._quote(target,estimate,WINTER,peers)
    assert quote["source"]==model.SOURCE
    assert quote["observation_type"]=="DERIVED_NOT_SOLD"
    assert quote["verification_basis"]=="RULES_VERIFIED_PEER_MODEL"
    assert quote["reference_identity"]=={
        "name":target["name"],"set_id":"BT1",
        "card_number":"BT1-001","set_name":"Galactic Battle"}
    assert quote["price_gbp_minor"]<100
    assert quote["recommended_store_price_minor"]==100
    assert quote["physical_valuation_eligible"] is False
    assert quote["sold_comparable"] is False
    assert len(quote["sample_reference_ids"])>=5


class FakeConnection:
    def __init__(self):
        self.writes=[]
    async def fetch(self,sql,*args):
        if sql==model.CANDIDATE_SQL:
            return [_ref()]
        if sql==model.PEER_SQL:
            return [_peer_row(i,minor) for i,minor in
                    [(2,2),(3,3),(4,4),(5,5),(6,6),(7,6)]]
        return [{"provider":"Bandai Official","provider_id":"base-001"}]
    async def executemany(self,sql,rows):
        self.writes.extend(rows)


@pytest.mark.asyncio
async def test_full_one_card_dry_run_does_not_write(monkeypatch):
    connection=FakeConnection()
    @asynccontextmanager
    async def conn(*args):
        yield connection
    async def admin(*args):
        return None
    monkeypatch.setattr(model,"user_connection",conn)
    monkeypatch.setattr(model,"require_platform_admin",admin)
    report=await model.run_daily_reference_model(object(),uuid4(),
                 dry_run=True,limit=1000,now=WINTER)
    assert report["examined"]==1 and report["eligible"]==1
    assert report["writes_applied"]==report["writes_attempted"]==0
    assert report["inventory_writes"]==report["shopify_writes"]==0
    assert report["source"]==model.SOURCE
    assert not connection.writes


@pytest.mark.asyncio
async def test_apply_writes_only_internal_reference_source(monkeypatch):
    connection=FakeConnection()
    @asynccontextmanager
    async def conn(*args):
        yield connection
    async def admin(*args):
        return None
    monkeypatch.setattr(model,"user_connection",conn)
    monkeypatch.setattr(model,"require_platform_admin",admin)
    report=await model.run_daily_reference_model(object(),uuid4(),
                 dry_run=False,limit=1000,now=WINTER)
    assert report["writes_applied"]==report["writes_attempted"]==1
    assert len(connection.writes)==1
    args=connection.writes[0]
    assert args[15]==model.SOURCE
    assert args[5] < 100 and args[17] is None
    assert report["shopify_writes"]==report["inventory_writes"]==0


@pytest.mark.asyncio
async def test_max_one_thousand_per_batch_without_provider_calls():
    with pytest.raises(ValueError):
        await model.run_daily_reference_model(None,None,limit=1001)
    with pytest.raises(ValueError):
        await model.run_daily_reference_model(None,None,limit=0)
