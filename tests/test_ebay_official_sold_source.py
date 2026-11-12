"""Official eBay UK sold evidence: restricted access, exact facts, no price writes."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from app.ebay_official_sold_source import (
    MarketplaceInsightsApproval, OfficialMarketplaceInsightsClient,
    NORMALIZATION_REVISION, normalize_marketplace_insights,
)
from app.ebay_official_client import EbayOfficialClient, EbayApiError
from app.pricing_engine import ComparableTarget, MarketObservation, PricingPolicy, calculate_price

NOW=datetime(2026,11,12,20,0,tzinfo=timezone.utc)
CATALOGUE_ID=UUID("00000000-0000-4000-8000-000000000001")
APPROVED=MarketplaceInsightsApproval(True,"EBAY_PARTNER_APPROVED_2026",frozenset({"183454"}),True)
NO_ACCESS=MarketplaceInsightsApproval(False,None,frozenset(),False)

def target(**updates):
    result=dict(catalogue_id=CATALOGUE_ID,game="Pokemon",name="Charizard",
                set_name="Base Set",card_number="4/102",variant="Holofoil",
                language="English",condition="Near Mint",grade=None,
                grading_company=None,seal_status=None)
    result.update(updates)
    return result

def sale(n,title=None,**updates):
    row=dict(itemId="v1|"+str(300000000000+n)+"|0",
      title=title or "Pokemon Charizard 4/102 Base Set Holofoil Near Mint",
      lastSoldDate=(NOW-timedelta(days=n+1)).isoformat(),
      lastSoldPrice={"value":str(32+n)+".00","currency":"GBP"},
      buyingOptions=["FIXED_PRICE"],totalSoldQuantity=1,
      itemLocation={"country":"GB"},condition="Near Mint")
    row.update(updates)
    return row

def transform(rows,ref=None):
    return normalize_marketplace_insights({"itemSales":rows},target=ref or target(),
        approval=APPROVED,category_id="183454",now=NOW)


def test_access_entitlement_is_required_even_for_own_ebay_oauth():
    with pytest.raises(PermissionError):
        normalize_marketplace_insights({"itemSales":[sale(1)]},target=target(),
          approval=NO_ACCESS,category_id="183454",now=NOW)
    for forbidden in ["193000","183454;drop table", ""]:
        with pytest.raises(PermissionError):
            normalize_marketplace_insights({"itemSales":[]},target=target(),
                approval=APPROVED,category_id=forbidden,now=NOW)


@pytest.mark.asyncio
async def test_not_approved_does_not_even_fetch_oauth_or_make_http(monkeypatch):
    class FakeOAuth:
        marketplace_id="EBAY_GB"
        async def application_token(self):
            raise AssertionError("Unapproved source must not mint a token")
    client=OfficialMarketplaceInsightsClient(oauth_client=FakeOAuth(),approval=NO_ACCESS)
    with pytest.raises(PermissionError):
        await client.sold(query="Charizard 4/102 Base Set",category_id="183454")


@pytest.mark.asyncio
async def test_live_official_request_uses_restricted_uk_endpoint_and_no_scraper(monkeypatch):
    calls=[]
    async def handler(request):
        calls.append(request)
        assert request.url.path == "/buy/marketplace_insights/v1_beta/item_sales/search"
        assert request.url.params["category_ids"] == "183454"
        assert request.url.params["limit"] == "5"
        assert request.url.params["filter"] == "itemLocationCountry:GB,priceCurrency:GBP"
        assert request.headers["x-ebay-c-marketplace-id"] == "EBAY_GB"
        assert request.headers["authorization"] == "Bearer sample-official-app-token"
        return httpx.Response(200,json={"itemSales":[sale(0)],"total":1})
    original=httpx.AsyncClient
    def fake_client(*args,**kwargs):
        return original(transport=httpx.MockTransport(handler),**{
            key:value for key,value in kwargs.items() if key != "transport"})
    monkeypatch.setattr(httpx,"AsyncClient",fake_client)
    class FakeOAuth:
        marketplace_id="EBAY_GB"
        async def application_token(self):return "sample-official-app-token"
    result=await OfficialMarketplaceInsightsClient(oauth_client=FakeOAuth(),
         approval=APPROVED).sold(query="Charizard 4/102 Base Set",
                                category_id="183454",limit=5)
    assert len(calls)==1
    assert result["itemSales"][0]["lastSoldPrice"]["currency"]=="GBP"
    assert "trawl" not in calls[0].url.host


def test_five_exact_pokemon_sales_normalize_without_writing_or_inventing_price():
    payload=transform([sale(i) for i in range(5)])
    assert payload["count"]==5
    assert payload["status"]=="CANDIDATES_REQUIRE_INDEPENDENT_REVIEW"
    assert payload["can_publish_market_value"] is False
    observations=payload["observations"]
    assert len({o.source_record_key for o in observations})==5
    for entry in observations:
        assert entry.source=="EBAY"
        assert entry.observation_type=="SOLD"
        assert entry.currency=="GBP"
        assert entry.source_country=="GB"
        assert entry.sample_size==1
        assert entry.metadata["provider_evidence"]["normalization_revision"]==NORMALIZATION_REVISION
        assert entry.metadata["provider_evidence"]["accepted_best_offer_uncertain_rows_excluded"] is True
        assert entry.metadata["access_method"]=="EBAY_MARKETPLACE_INSIGHTS_RESTRICTED"
        assert entry.price_minor==entry.price_gbp_minor
        assert entry.shipping_minor is None
    old_policy=PricingPolicy(min_sources=1,min_confidence=0.3,max_auto_change_pct=100,
        max_volatility_pct=100)
    result=calculate_price([
         MarketObservation(source=o.source,observation_type=o.observation_type,
             observed_at=o.observed_at,price_gbp_minor=o.price_gbp_minor,
             condition=o.condition,grading_company=o.grading_company,grade=o.grade,
             language=o.language,seal_status=o.seal_status,source_country=o.source_country,
             source_record_key=o.source_record_key) for o in observations],
         target=ComparableTarget(condition="Near Mint",language="English"),
         policy=old_policy,as_of=NOW)
    assert result.sold_observation_count == 5
    assert result.market_value_minor > 0
    assert result.algorithm_version=="drop-rate-market-v4"


def test_rejects_best_offer_non_gbp_other_country_old_date_and_unproven_sales():
    rows=[
      sale(0,buyingOptions=["BEST_OFFER","FIXED_PRICE"]),
      sale(1,lastSoldPrice={"value":"42.00","currency":"EUR"}),
      sale(2,itemLocation={"country":"US"}),
      sale(3,lastSoldDate=(NOW-timedelta(days=95)).isoformat()),
      sale(4,totalSoldQuantity=0),
      sale(5,buyingOptions=["AUCTION"],bidCount=0),
      sale(6,lastSoldPrice={"value":"38.001","currency":"GBP"}),
      sale(7,lastSoldPrice={"value":"0","currency":"GBP"}),
    ]
    output=transform(rows)
    assert output["count"]==0
    assert output["rejected"]["AMBIGUOUS_BEST_OFFER_OR_FORMAT"]==1
    assert output["rejected"]["NO_GBP_ACTUAL_SOLD_PRICE"]==1
    assert output["rejected"]["NON_UK_ITEM_LOCATION"]==1
    assert output["rejected"]["INVALID_OR_STALE_SOLD_AMOUNT_DATE"]==3
    assert output["rejected"]["NOT_CONFIRMED_SOLD"]==1
    assert output["rejected"]["AUCTION_WITHOUT_CONFIRMED_BID"]==1


def test_one_piece_ordinary_foil_cannot_inherit_manga_parallel_value():
    ref=target(game="One Piece",name="Monkey.D.Luffy",set_name="Awakening of the New Era",
       card_number="OP05-119",variant="Foil")
    ordinary="One Piece Monkey D Luffy OP05-119 SEC English Foil Near Mint"
    rows=[sale(i,title=ordinary) for i in range(4)]
    rows.append(sale(5,title=ordinary+" Manga Parallel"))
    output=transform(rows,ref=ref)
    assert output["count"]==4
    assert output["rejected"]["WRONG_EXACT_PRINTING_OR_PHYSICAL_STATE"]==1


def test_graded_psa9_not_psa95_and_raw_never_matches_graded():
    ref=target(name="Charizard V",set_name="Darkness Ablaze",card_number="019/189",
               variant="Holofoil",condition=None,grading_company="PSA",grade="9")
    base="Pokemon Charizard V 019/189 Darkness Ablaze Holofoil PSA 9"
    rows=[sale(i,title=base,condition="Used") for i in range(4)]
    rows.append(sale(5,title=base+".5",condition="Used"))
    out=transform(rows,ref=ref)
    assert out["count"]==4
    assert out["rejected"]["WRONG_EXACT_PRINTING_OR_PHYSICAL_STATE"]==1
    assert all(x.grading_company=="PSA" and x.grade=="9" and x.condition is None
               for x in out["observations"])
    raw=transform([sale(0,title=base)],ref=target())
    assert raw["count"]==0


def test_duplicate_item_id_counts_one_not_total_quantity_and_conflicts_fail_closed():
    row=sale(0,totalSoldQuantity=17)
    output=transform([row,row.copy()])
    assert output["count"]==1
    assert output["observations"][0].sample_size==1
    conflict=sale(0,lastSoldPrice={"value":"999.00","currency":"GBP"})
    invalid=transform([row,conflict])
    assert invalid["count"]==0
    assert invalid["rejected"]["CONFLICTING_ITEM_ID"]>=2


def test_incomplete_printing_or_page_does_not_guess():
    with pytest.raises(ValueError):
        transform([sale(0)],ref=target(card_number=""))
    with pytest.raises(ValueError):
        normalize_marketplace_insights({"itemSales":[sale(i) for i in range(30)]},
           target=target(),approval=APPROVED,category_id="183454",now=NOW)
    with pytest.raises(ValueError):
        normalize_marketplace_insights({"itemSales":[]},target=target(),approval=APPROVED,
           category_id="183454",now=NOW.replace(tzinfo=None))
