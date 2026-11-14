"""Prepared Cardmarket regional values never promote into UK physical valuations."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.cardmarket_bulk_context import prepare_cardmarket_context, SOURCE
from app.cardmarket_public_pilot import PilotError
from app.fx import FxQuote, ECB_SOURCE

NOW = datetime(2026, 11, 14, 14, tzinfo=timezone.utc)
GUIDE = NOW - timedelta(hours=8)
FX = FxQuote(base_currency="EUR", quote_currency="GBP", source=ECB_SOURCE,
             rate=Decimal("0.8338"), effective_at=GUIDE-timedelta(hours=12),
             retrieved_at=NOW-timedelta(hours=1))
HASHES = {"product_sha256": "a"*64, "guide_sha256": "b"*64}


def candidate():
    return {"provider": "TCGdex", "system_code": "POKEMON_TCG",
            "language": "English", "provider_id": "swsh8-1", "name": "Caterpie",
            "set_id": "swsh8", "set_name": "Fusion Strike", "card_number": "1/264",
            "variant_id": "normal-variant", "cardmarket_id": 582029,
            "finish": "Normal", "source_link": "TCGDEX_CARDMARKET",
            "source_field": "avg7", "daily_guide_eur_minor": 250,
            "match_basis": "EIGHT_NAME_COHORT_AND_TRUSTED_SOURCE_ID",
            "is_exact_variant": True, "publishable": False,
            "physical_valuation_eligible": False,
            "guide_observed_at": GUIDE.isoformat()}


def run(candidates=None, fx=FX, guide_at=GUIDE, now=NOW, **kwargs):
    return prepare_cardmarket_context(
        candidates=[candidate()] if candidates is None else candidates, fx=fx,
        guide_at=guide_at, now=now, **{**HASHES, **kwargs}
    )


def test_official_avg7_becomes_nonphysical_gbp_context_with_real_identity():
    x = candidate()
    before = deepcopy(x)
    report = run([x])
    assert x == before
    assert report["regional_reference_count"] == 1
    assert report["regional_variant_quote_count"] == 1
    assert report["status"] == "PREPARED_NOT_PUBLISHED"
    assert report["physical_market_values"] == report["shopify_store_prices"] == 0
    record = report["prepared"][0]
    assert record["reference_key"].startswith("r:")
    assert len(record["identity_sha256"]) == len(record["quotes_sha256"]) == 64
    q = record["quotes"][0]
    assert q["source"] == SOURCE
    assert q["original_minor"] == 250
    assert q["regional_sale"]["price_gbp_minor"] == 208
    assert q["market_scope"] == "EU_AGGREGATED_7_DAY_SALES"
    assert q["language_basis"] == "UNSPECIFIED"
    assert q["physical_valuation_eligible"] is False
    assert "market_value_minor" not in q


def test_multiple_finishes_stay_separate_no_low_price_fallback():
    first = candidate()
    second = {**first, "variant_id": "reverse-variant",
              "source_field": "avg7-holo", "finish": "Reverse Holofoil",
              "daily_guide_eur_minor": 399}
    report = run([second, first])
    assert report["regional_reference_count"] == 1
    assert {q["source_field"] for q in report["prepared"][0]["quotes"]} == {"avg7", "avg7-holo"}
    assert report["regional_variant_quote_count"] == 2


def test_number_only_guides_cannot_become_valuations():
    row = candidate()
    row.update(source_link="CARDMARKET_CATALOGUE", is_exact_variant=False)
    report = run([row])
    assert report["regional_reference_count"] == 0
    assert report["rejections"]["SOURCE_IDENTITY_OR_VARIANT_NOT_VERIFIED"] == 1


@pytest.mark.parametrize("changed", [
    {"source_field": "low"}, {"variant_id": ""}, {"daily_guide_eur_minor": 0},
    {"daily_guide_eur_minor": True}, {"publishable": True},
    {"physical_valuation_eligible": True}, {"set_id": None},
    {"language": "Unknown"}, {"source_link": "TCGPLAYER"},
])
def test_bad_candidates_fail_closed_without_gbp_write(changed):
    row = candidate()
    row.update(changed)
    assert run([row])["regional_reference_count"] == 0


def test_same_canonical_key_cannot_be_relabelled_to_another_printing():
    first = candidate()
    second = {**first, "set_name": "Another Set", "variant_id": "other"}
    with pytest.raises(PilotError, match="reused"):
        run([first, second])


def test_exact_variant_duplicates_never_append_twice():
    row = candidate()
    result = run([row, deepcopy(row)])
    assert result["regional_reference_count"] == 1
    assert result["regional_variant_quote_count"] == 1
    assert result["rejections"]["DUPLICATE_FINISH_SLOT"] == 1


@pytest.mark.parametrize("fx", [
    FxQuote("USD","GBP",Decimal("0.8"),FX.effective_at,FX.retrieved_at,ECB_SOURCE),
    FxQuote("EUR","GBP",Decimal("NaN"),FX.effective_at,FX.retrieved_at,ECB_SOURCE),
    FxQuote("EUR","GBP",Decimal("0.8"),GUIDE+timedelta(hours=1),FX.retrieved_at,ECB_SOURCE),
    FxQuote("EUR","GBP",Decimal("0.8"),GUIDE-timedelta(days=9),FX.retrieved_at,ECB_SOURCE),
])
def test_fx_must_be_verified_historical_eur_gbp(fx):
    with pytest.raises(PilotError, match="ECB"):
        run(fx=fx)


def test_missing_real_provider_receipts_block():
    with pytest.raises(PilotError, match="SHA256"):
        run(guide_sha256="fake")


def test_expired_data_cannot_be_refreshed_by_new_now_timestamp():
    with pytest.raises(PilotError, match="stale"):
        run(now=NOW+timedelta(days=5))


def test_quote_matches_existing_regional_price_validator():
    from app.regional_catalogue_prices import eligible_quotes
    quote = run()["prepared"][0]["quotes"][0]
    assert len(eligible_quotes([quote],NOW,allowed_sources={SOURCE})) == 1
