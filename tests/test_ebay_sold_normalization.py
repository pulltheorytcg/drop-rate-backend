import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.ebay_sold_normalization import REVISION, normalize_uk_sold_payload


def row(**changes):
    return dict(dict(item_id="123456789", title="Pokemon Seel 021/094 Phantasmal Flames NM",
        sale_price=5, shipping_price=1.25, currency="�", condition_raw="Near Mint",
        date_sold="2026-09-20T14:30:00.000Z", location_country="United Kingdom",
        buying_format="Buy It Now", best_offer_available=False,
        item_link="https://www.ebay.co.uk/itm/123456789"), **changes)


def payload(*rows):
    return {"site":"EBAY_GB", "currency":"GBP", "results":list(rows)}


def normalized(**changes):
    return normalize_uk_sold_payload(payload(row(**changes)))


def details(**changes):
    return dict(dict(site="EBAY_GB", item_id="123456789", listing_state="sold",
        currency="�", sold_at="2026-09-20T13:30:00Z", best_offer_accepted=True,
        sale_price=4, list_price=5), **changes)


@pytest.mark.parametrize("date, expected", [
    ("2026-09-20T14:30:00Z", "2026-09-20T13:30:00+00:00"),
    ("2026-11-02T14:30:00Z", "2026-11-02T14:30:00+00:00"),
    ("2026-09-20", "2026-09-19T23:00:00+00:00"),
])
def test_provider_wall_time_becomes_utc(date, expected):
    result = normalized(date_sold=date)["results"][0]
    assert result["date_sold"] == expected
    assert result["_pricing_evidence"]["provider_date_sold"] == date


@pytest.mark.parametrize("date", ["2026-03-29T01:30:00Z", "2026-10-25T01:30:00Z", "bad", None,
                                  "2026-09-20T14:30:00+03:00"])
def test_bad_or_ambiguous_time_is_not_guessed(date):
    assert not normalized(date_sold=date)["results"]


@pytest.mark.parametrize("country, reason", [("United States", "NON_UK_ITEM_LOCATION"),
    ("Germany", "NON_UK_ITEM_LOCATION"), (None, "UNKNOWN_ITEM_LOCATION"), ("", "UNKNOWN_ITEM_LOCATION")])
def test_uk_marketplace_does_not_prove_item_location(country, reason):
    result = normalized(location_country=country)
    assert not result["results"]
    assert result["_normalization"]["reasons"] == {reason:1}


def test_conflicting_details_location_is_rejected():
    assert not normalized(details=details(location_country="United States"))["results"]


@pytest.mark.parametrize("shipping, status", [(None, "UNKNOWN"), (0, "FREE"), (1.25, "KNOWN")])
def test_shipping_preserves_unknown_free_and_paid(shipping, status):
    result = normalized(shipping_price=shipping)["results"][0]
    assert result["_pricing_evidence"]["shipping_status"] == status
    assert result["sale_price"] == "5"
    assert (result["shipping_price"] is None) == (shipping is None)


@pytest.mark.parametrize("field,value", [("sale_price",float("nan")), ("sale_price",float("inf")),
    ("sale_price",True), ("sale_price",0), ("sale_price",1e30), ("shipping_price",-1),
    ("shipping_price",float("nan")), ("currency","$")])
def test_invalid_money_and_currency_are_rejected(field, value):
    assert not normalized(**{field:value})["results"]


def test_unresolved_offer_and_unclassified_sale_are_not_sold_prices():
    assert not normalized(buying_format="Best Offer")["results"]
    assert not normalized(best_offer_available=True)["results"]
    assert not normalized(best_offer_available=None)["results"]
    assert not normalized(buying_format=None)["results"]
    assert normalized(buying_format="Auction", best_offer_available=None)["results"]


def test_verified_same_sale_uses_accepted_amount_not_asking_price():
    result = normalized(buying_format="Best Offer", details=details())["results"][0]
    assert result["sale_price"] == "4"
    assert result["_pricing_evidence"]["reported_sale_price"] == "5"
    assert result["_pricing_evidence"]["sale_price_basis"] == "DETAILS_CONFIRMED_ACCEPTED_OFFER"


@pytest.mark.parametrize("changes", [{"item_id":"987654321"}, {"sold_at":"2026-09-19T13:30:00Z"},
    {"listing_state":"active"}, {"currency":"$"}, {"sale_price":5}, {"list_price":None},
    {"sold_at":"2026-09-20T13:30:00"}, {"site":"EBAY_US"}])
def test_unrelated_or_unverified_details_never_supply_offer_price(changes):
    assert not normalized(buying_format="Best Offer", details=details(**changes))["results"]


def test_confirmed_non_offer_sale_can_be_used_even_when_offers_were_available():
    result = normalized(best_offer_available=True, details=details(best_offer_accepted=False, sale_price=5))
    assert result["results"][0]["sale_price"] == "5"


def test_duplicate_rows_count_once_and_conflicts_have_no_order_bias():
    original = row()
    assert len(normalize_uk_sold_payload(payload(original, copy.deepcopy(original)))["results"]) == 1
    for change in ({"sale_price":9}, {"location_country":"United States"}, {"best_offer_available":True}):
        other = row(**change)
        for rows in ((original,other),(other,original)):
            assert not normalize_uk_sold_payload(payload(*rows))["results"]


def test_input_is_immutable_and_private_detail_fields_are_not_retained():
    raw = payload(row(details={"seller":{"username":"private-seller"}, "description_text":"private"}))
    before = copy.deepcopy(raw)
    result = normalize_uk_sold_payload(raw)
    assert raw == before
    assert "private" not in json.dumps(result)
    assert result["_normalization"]["revision"] == REVISION


def test_day_only_sale_cannot_borrow_offer_price_from_item_details():
    assert not normalized(date_sold="2026-09-20T00:00:00Z", buying_format="Best Offer",
        details=details(sold_at="2026-09-19T23:00:00Z"))["results"]


@pytest.mark.parametrize("kind", ["COMIC", "MANGA", "SEALED", "GRADED"])
def test_normalization_and_provenance_reach_each_existing_collectible_matcher(kind):
    from app.live_market_refresh import select_comps
    from test_book_market import target as book_target, TITLE
    from test_live_market_refresh import target as card_target
    target=book_target()
    title=TITLE
    if kind=="MANGA":
        target["book_printing"].update(system_code="MANGA",series_title="Fixture Manga",publisher="VIZ Media",
            book_format="MANGA",cover_code=None,release_year=2003,barcode_gtin="9781566199094")
        title="Fixture Manga Volume 1 VIZ Media 2003 English first printing ISBN 9781566199094 Near Mint"
    elif kind=="SEALED":
        target=dict(product_type="SEALED",set_code="OP-17",language="Japanese",sealed_product_type="BOOSTER_PACK")
        title="One Piece OP-17 Japanese Booster Pack New Sealed"
    elif kind=="GRADED":
        target=card_target(grading_company="PSA",grade="9",condition=None)
        title="Seel 021/094 Phantasmal Flames PSA 9"
    raw=payload(*[row(item_id=str(123456780+n),title=title) for n in range(5)])
    comps=select_comps(normalize_uk_sold_payload(raw),target,datetime(2026,9,21,tzinfo=timezone.utc))
    assert len(comps)==5
    assert all(c["provider_evidence"]["normalization_revision"]==REVISION for c in comps)
    assert all(c["sold_at"].hour==13 for c in comps)


def test_catalogue_replay_prefers_rechecked_basis_without_reinterpreting_utc_history():
    from app.catalogue_valuations import catalogue_values
    from test_catalogue_valuations import observation, NOW, PRODUCT
    evidence=normalized()["results"][0]["_pricing_evidence"]
    verified=[observation(n) for n in range(1,6)]
    for r in verified:
        r["metadata"]["provider_evidence"]=evidence
    legacy=observation(0)
    legacy["price_gbp_minor"]=999999
    result=catalogue_values(PRODUCT,[legacy,*verified],now=NOW)[0]
    comps=result["evidence"]["comps"]
    assert {c["item_id"] for c in comps}=={str(n) for n in range(1,6)}
    assert comps[0]["sold_at"]==verified[0]["observed_at"].isoformat()
    assert all(c["provider_evidence"]==evidence for c in comps)
    assert not catalogue_values(PRODUCT,[legacy,*verified[:4]],now=NOW)


def test_legacy_basis_is_preserved_until_rechecked_and_json_metadata_is_supported():
    from app.ebay_sold_normalization import prefer_normalized_uk_rows
    old={"metadata":{}}
    verified={"metadata":json.dumps({"provider_evidence":normalized()["results"][0]["_pricing_evidence"]})}
    assert prefer_normalized_uk_rows([old])==[old]
    assert prefer_normalized_uk_rows([old,verified])==[verified]
    assert prefer_normalized_uk_rows([{"metadata":"broken"}])==[{"metadata":"broken"}]


@pytest.mark.parametrize("changes", [{"site":"EBAY_US"}, {"currency":"USD"}, {"results":None}])
def test_wrong_response_rejected(changes):
    with pytest.raises(ValueError):
        normalize_uk_sold_payload(dict(payload(row()), **changes))


@pytest.mark.asyncio
async def test_http_boundary_normalizes_and_preserves_quota_without_extra_calls(monkeypatch):
    from app import ebay_sold_pricing as market
    calls=[]
    async def handle(request):
        calls.append(request)
        return httpx.Response(200, json=payload(row(), row(item_id="223456789",location_country="Canada")),
                              headers={"X-Credits-Charged":"1", "X-RateLimit-Remaining":"99"})
    client_class=httpx.AsyncClient
    monkeypatch.setattr(market.httpx,"AsyncClient",lambda **kwargs:client_class(transport=httpx.MockTransport(handle),**kwargs))
    result=await market.TrawlEbaySoldClient(api_key="test-only").sold(query="Seel", max_pages=1)
    assert len(calls)==1 and "details" not in calls[0].url.params
    assert len(result["results"])==1
    assert result["_usage"]=={"remaining":99,"charged":1}
    assert result["_normalization"]["excluded"]==1


@pytest.mark.asyncio
async def test_normalized_provenance_reaches_immutable_observation_insert():
    from app.ebay_sold_pricing import _persist_comp, select_five_newest_comps
    target=dict(catalogue_id="00000000-0000-4000-8000-000000000001", game="Pokemon", name="Seel",
        set_name="Phantasmal Flames", card_number="021/094", variant="Normal", condition="Near Mint",
        grading_company=None, grade=None, language="English", product_type="CARD")
    comp=select_five_newest_comps(normalized(), target=target)[0]
    calls=[]
    async def insert(sql,*args):
        calls.append((sql,args))
        return {"id":UUID(int=1)}
    assert await _persist_comp(SimpleNamespace(fetchrow=insert),target,comp,query="Seel")
    sql,args=calls[0]
    metadata=json.loads(args[-1])
    assert metadata["provider_evidence"]["item_location_country"]=="GB"
    assert metadata["provider_evidence"]["normalization_revision"]==REVISION
    assert args[4]==datetime(2026,9,20,13,30,tzinfo=timezone.utc)
    assert "on conflict (source, source_record_key) do nothing" in sql
    from dataclasses import replace
    await _persist_comp(SimpleNamespace(fetchrow=insert),target,replace(comp,provider_evidence=None),query="Seel")
    assert calls[0][1][2]!=calls[1][1][2], "Rechecked evidence must append without overwriting legacy history"
    await _persist_comp(SimpleNamespace(fetchrow=insert),target,comp,query="Seel")
    assert calls[0][1][2]==calls[2][1][2], "Rechecking unchanged evidence must remain idempotent"
