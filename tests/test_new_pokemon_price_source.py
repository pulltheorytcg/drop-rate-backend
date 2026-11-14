"""Regression tests for the read-only me06 source probe."""
from datetime import datetime, timezone
import pytest
from app.new_pokemon_price_source import select_samples, detail_evidence, release_listing_evidence
from app.cardmarket_public_pilot import PilotError


def manifest():
    return {"id":"me06","name":"Delta Reign","cards":[
        {"id":f"me06-{i:03}","localId":f"{i:03}","name":f"Verified Card {i}"}
        for i in range(1,142)]}


def sources():
    now=datetime.now(timezone.utc).isoformat()
    return (
        {"createdAt":now,"products":[{"idProduct":481001,
           "categoryName":"Pokemon Single","idExpansion":999,"name":"Verified Card 1"}]},
        {"createdAt":now,"priceGuides":[{"idProduct":481001,"avg7":0.5}]}
    )


def details():
    samples=select_samples(manifest())
    return [
        {**card,"set":{"id":"me06"},
          "variants_detailed":([{"size":"standard","type":"normal","variantId":"exact-v1",
                "thirdParty":{"cardmarket":481001},
                "pricing":{"cardmarket":{"idProduct":481001}}}]
                if idx==0 else [])}
        for idx,card in enumerate(samples)
    ]


def test_sample_is_bounded_deterministic():
    samples=select_samples(manifest())
    assert len(samples)==12
    assert samples[0]["id"]=="me06-001"
    assert samples[-1]["id"]=="me06-141"
    assert len({x["id"] for x in samples})==12


@pytest.mark.parametrize("change",[
    {"id":"me05"},{"cards":[]},{"cards":[{"id":"wrong-001","localId":"001","name":"Oops"}]},
    {"cards":[{"id":"me06-001","localId":"001","name":""}]},
])
def test_bad_manifest_blocks_every_proposed_price_link(change):
    m=manifest()
    m.update(change)
    with pytest.raises(PilotError):
        select_samples(m)


@pytest.mark.parametrize("change",[
    {"name":"Wrong printing"},{"id":"me06-002"},{"localId":"002"},
    {"set":{"id":"me05"}}
])
def test_provider_card_detail_mismatch_fails_closed(change):
    m=manifest()
    d=details()
    d[0].update(change)
    products,guides=sources()
    with pytest.raises(PilotError):
        detail_evidence(m,d,products,guides,now=datetime.now(timezone.utc))


def test_direct_id_source_receipt_only_no_price_field():
    products,guides=sources()
    report=detail_evidence(manifest(),details(),products,guides,now=datetime.now(timezone.utc))
    assert report["sampled_cards"]==12
    assert report["samples_with_direct_cardmarket_id"]==1
    assert report["sampled_direct_ids_with_guide"]==1
    assert report["db_writes"]==0 and report["verified_printing_price_matches"]==0
    assert report["uk_sold_market_values"]==0
    assert "avg7" not in str(report)
    assert "price_gbp_minor" not in str(report)


def test_missing_cardmarket_id_yields_no_candidates():
    d=details()
    d[0]["variants_detailed"]=[]
    products,guides=sources()
    report=detail_evidence(manifest(),d,products,guides,now=datetime.now(timezone.utc))
    assert report["samples_with_direct_cardmarket_id"]==0
    assert report["sampled_direct_ids_with_guide"]==0


def test_duplicate_market_product_identity_fails_closed():
    products,guides=sources()
    products["products"].append(products["products"][0].copy())
    with pytest.raises(PilotError):
        detail_evidence(manifest(),details(),products,guides,now=datetime.now(timezone.utc))


def test_official_release_presence_is_only_diagnostic():
    products,_=sources()
    products["products"].append({"idProduct":481002,"name":"Delta Reign Card",
                                 "categoryName":"Pokemon Single","idExpansion":456})
    nonsingles={"createdAt":datetime.now(timezone.utc).isoformat(),
                "products":[{"idProduct":987654,"name":"Mega Evolution Delta Reign Booster Box",
                             "idExpansion":456,"categoryName":"Pokemon Booster Boxes"}]}
    result=release_listing_evidence(manifest(),products,nonsingles,now=datetime.now(timezone.utc))
    assert result["single_release_title_mentions"]==1
    assert result["non_single_release_title_mentions"]==1
    assert result["release_title_is_not_printing_match"] is True
    assert "price" not in str(result).lower()


def test_release_presence_requires_true_set_identity():
    products,_=sources()
    with pytest.raises(PilotError):
        release_listing_evidence({"id":"me05","name":"Delta Reign"},products,products,
                                 now=datetime.now(timezone.utc))
