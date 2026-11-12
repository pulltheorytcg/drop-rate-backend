"""Source-aware coverage work queue: every published game without guessed Market Values."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import market_value_work_queue as work

ACTOR = UUID("11111111-1111-4111-8111-111111111111")

def coverage():
    return {
        "summary":{
            "by_game":[
              {"kind":"CARD","system_code":"POKEMON_TCG","language":"English","total":23000,
               "priced":11000,"status_counts":{"REFERENCE_AVAILABLE":11000,"STALE_EVIDENCE":12000}},
              {"kind":"CARD","system_code":"ONE_PIECE_CARD_GAME","language":"English","total":4500,
               "priced":500,"status_counts":{"REFERENCE_AVAILABLE":500,"SOURCE_ACCESS_REQUIRED":4000}},
              {"kind":"CARD","system_code":"NARUTO_KAYOU","language":"Unknown","total":2679,
               "priced":0,"status_counts":{"SOURCE_ACCESS_REQUIRED":2679}},
              {"kind":"CARD","system_code":"POKEMON_TCG","language":"English","total":50,
               "priced":0,"status_counts":{"NOT_APPLICABLE_DIGITAL":50}},
              {"kind":"SEALED","system_code":"ONE_PIECE_CARD_GAME","language":"English","total":300,
               "priced":0,"status_counts":{"STALE_EVIDENCE":300}},
            ]
        },
        "catalogue":{
            "stored_physical_tcg_references":269599,
            "published_sources":[
              {"provider":"ygoprodeck","system_code":"YUGIOH","game":"Yu-Gi-Oh!",
               "language":"English","stored_references":14000,"category":"TCG"},
              {"provider":"lorcast","system_code":"DISNEY_LORCANA","game":"Disney Lorcana",
               "language":"English","stored_references":18000,"category":"TCG"},
              {"provider":"mtgjson","system_code":"MAGIC_THE_GATHERING","game":"Magic: The Gathering",
               "language":"English","stored_references":160000,"category":"TCG"},
              {"provider":"cardcollectorcapital","system_code":"SPORTS_CARDS","game":"Sports Cards",
               "language":"English","stored_references":300,"category":"OTHER"},
              {"provider":"reviewed_figures","system_code":"FIGURES","game":"Figures",
               "language":"English","stored_references":4,"category":"OTHER"},
            ],
            "unpublished_tcg_games":[{"system_code":"RIFTBOUND","game":"Riftbound"}],
        },
    }

def test_queue_reports_source_and_language_gaps_without_invented_r2_valuation():
    out=work.build_market_coverage_work_queue(coverage())
    assert out["price_definition"]=="ACTUAL_UK_COMPLETED_SALES_ONLY"
    assert out["legacy_sql"]=={
        "references":30179,"guide_inclusive_current_reference_prices":11500,
        "missing_or_ineligible_reference_prices":18679,"verified_uk_sold_coverage":None,
        "sealed_references":300,"sealed_current_reference_prices":0,
        "sealed_missing_reference_prices":300}
    assert out["r2_first"]["stored_references_including_other_collectibles"]==192304
    assert out["groups_count"] == 10
    assert out["total_stored_references"]==269599
    assert any(x["game"]=="Yu-Gi-Oh!" for x in out["groups"])
    assert any(x["game"]=="Disney Lorcana" for x in out["groups"])
    assert any(x["game"]=="Magic: The Gathering" for x in out["groups"])
    assert any(x["game"]=="Sports Cards" for x in out["groups"])
    assert any(x["game"]=="Figures" for x in out["groups"])
    assert any(x["catalogue_tier"]=="SQL_SEALED" and x["reference_count"]==300
               for x in out["groups"])
    assert any(x["game"]=="Riftbound" and x["catalogue_tier"]=="UNPUBLISHED" for x in out["groups"])
    for group in out["groups"]:
        assert group["market_value_must_be_sold_backed"] is True
        assert "ASKING" not in group["market_value_coverage"]
        if group["catalogue_tier"]=="R2_FIRST":
            assert group["current_reference_prices"] is None
            assert group["reference_prices_missing"] is None
            assert group["market_value_coverage"]=="NOT_MEASURED"
    assert out["groups"][0]["largest_blocker"]=="STALE_EVIDENCE"
    assert out["groups"][0]["reference_prices_missing"]==12000
    assert "guide" in out["notice"].lower()


def test_duplicate_partitions_fail_closed_no_double_count():
    c=coverage()
    c["catalogue"]["published_sources"].append(dict(c["catalogue"]["published_sources"][0]))
    with pytest.raises(ValueError,match="Duplicate"):
        work.build_market_coverage_work_queue(c)


def test_no_partitions_and_empty_catalogue_do_not_invent_coverage():
    result=work.build_market_coverage_work_queue({"summary":{},"catalogue":{}})
    assert result["groups_count"]==0
    assert result["total_stored_references"] is None
    assert result["legacy_sql"]["verified_uk_sold_coverage"] is None


@pytest.mark.asyncio
async def test_founder_route_is_readonly_and_reuses_existing_coverage_cache(monkeypatch):
    events=[]
    class Connection:
        async def fetch(self,sql):
            assert sql == work.CANONICAL_PRODUCT_SQL
            events.append("canonical_counts")
            return [
              {"product_type":"COMIC","game":"Manga","product_count":805},
              {"product_type":"COMIC","game":"Marvel Comics","product_count":138},
              {"product_type":"FIGURE","game":"Figures","product_count":2},
            ]
    @asynccontextmanager
    async def scoped(pool,user_id,request_id,*,readonly_snapshot=False):
        assert readonly_snapshot is True and user_id == ACTOR
        events.append("readonly")
        yield Connection()
    async def founder(conn):
        events.append("founder")
        return {"business_allowed":True}
    async def cached(pool,user_id,request_id):
        events.append("cached_coverage")
        assert user_id==ACTOR
        return coverage()
    monkeypatch.setattr(work,"user_connection",scoped)
    monkeypatch.setattr(work,"require_business_founder",founder)
    monkeypatch.setattr(work,"shared_price_coverage",cached)
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="market-queue-test"))
    result=await work.market_value_coverage_queue(req,SimpleNamespace(user_id=ACTOR))
    assert result["groups_count"]==13
    assert result["canonical_non_card_products"]["catalogue_rows"]==945
    assert any(x["game"]=="Manga" for x in result["groups"])
    assert any(x["game"]=="Marvel Comics" for x in result["groups"])
    assert events==["readonly","founder","canonical_counts","cached_coverage"]


@pytest.mark.asyncio
async def test_seller_access_is_denied_before_query(monkeypatch):
    events=[]
    @asynccontextmanager
    async def scoped(pool,user_id,request_id,*,readonly_snapshot=False):
        assert readonly_snapshot is True
        yield object()
    async def deny(conn):
        events.append("deny")
        raise HTTPException(403,"Verified founder Business access required")
    async def never(*args):
        raise AssertionError("Coverage data accessed before roster check")
    monkeypatch.setattr(work,"user_connection",scoped)
    monkeypatch.setattr(work,"require_business_founder",deny)
    monkeypatch.setattr(work,"shared_price_coverage",never)
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="market-queue-deny"))
    with pytest.raises(HTTPException) as exc:
        await work.market_value_coverage_queue(req,SimpleNamespace(user_id=ACTOR))
    assert exc.value.status_code==403
    assert events==["deny"]
