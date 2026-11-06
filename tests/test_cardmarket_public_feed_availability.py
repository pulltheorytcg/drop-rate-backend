from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest
from app.cardmarket_public_feed_availability import source_availability, SourceRejected

NOW = datetime(2026,11,5,18,tzinfo=timezone.utc)
def fixture():
    c={"createdAt":(NOW-timedelta(days=2)).isoformat(),"products":[
        {"idProduct":17,"categoryName":"Card Single","idExpansion":100},
        {"idProduct":18,"categoryName":"Card Single","idExpansion":100}]}
    p={"createdAt":(NOW-timedelta(hours=2)).isoformat(),"priceGuides":[
        {"idProduct":17,"trend":"1.30","trend-foil":"2.00"},
        {"idProduct":99,"trend":"9.30"}]}
    return c,p


@pytest.mark.parametrize("game,game_id",[("YUGIOH",3),("DISNEY_LORCANA",19)])
def test_public_export_feasibility_never_claims_exact_printing_or_market_value(game, game_id):
    c,p=fixture()
    original=deepcopy((c,p))
    result=source_availability(game=game,catalogue=c,guides=p,now=NOW)
    assert result["game_id"] == game_id
    assert result["source_product_rows"] == 2 and result["source_guide_rows"] == 2
    assert result["matching_product_ids"] == 1
    assert result["with_nonzero_statistical_normal"] == 1
    assert result["with_nonzero_statistical_foil"] == 1
    assert result["unjoined_source_products"] == 1
    assert result["exact_printing_matches"] == 0
    assert result["verified_uk_sold_market_values"] == 0
    assert result["database_writes"] == result["r2_writes"] == result["shopify_writes"] == 0
    assert (c,p) == original


@pytest.mark.parametrize("change", [
    {"idProduct":17}, {"idProduct":False},{"idProduct":0},{"idProduct":"17"}
])
def test_duplicate_or_invalid_ids_fail_closed(change):
    c,p=fixture()
    c["products"][1].update(change)
    with pytest.raises(SourceRejected,match="product ID"):
        source_availability(game="YUGIOH",catalogue=c,guides=p,now=NOW)


def test_bad_guide_data_never_borrows_asking_low_or_retail_price():
    c,p=fixture()
    p["priceGuides"][0]={"idProduct":17,"trend":"NaN","avg30":0,
                          "low":100,"suggested":500,"trend-foil":True,
                          "avg30-foil":"Infinity"}
    result=source_availability(game="DISNEY_LORCANA",catalogue=c,guides=p,now=NOW)
    assert result["with_nonzero_statistical_normal"] == 0
    assert result["with_nonzero_statistical_foil"] == 0
    assert result["verified_uk_sold_market_values"] == 0


def test_future_and_stale_exports_cannot_look_current():
    c,p=fixture()
    p["createdAt"]=(NOW-timedelta(days=5)).isoformat()
    with pytest.raises(SourceRejected,match="Stale"):
        source_availability(game="YUGIOH",catalogue=c,guides=p,now=NOW)
    p["createdAt"]=(NOW-timedelta(days=1)).isoformat()
    c["createdAt"]=(NOW+timedelta(minutes=5)).isoformat()
    with pytest.raises(SourceRejected,match="future"):
        source_availability(game="YUGIOH",catalogue=c,guides=p,now=NOW)


def test_unknown_game_and_incomplete_ids_rejected():
    c,p=fixture()
    with pytest.raises(SourceRejected,match="Unapproved"):
        source_availability(game="RIFTBOUND",catalogue=c,guides=p,now=NOW)
    p["priceGuides"].append({"idProduct":17,"trend":5})
    with pytest.raises(SourceRejected,match="duplicate"):
        source_availability(game="YUGIOH",catalogue=c,guides=p,now=NOW)
