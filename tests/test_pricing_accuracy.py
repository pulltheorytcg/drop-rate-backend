from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.pricing_accuracy import EvidenceRecord, evaluate_accuracy
from app.pricing_engine import MarketObservation

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def record(n, price=1000, *, category="COMICS", catalogue_id="edition-1",
           delay=0, condition="Near Mint", language="English"):
    at = NOW + timedelta(days=n)
    return EvidenceRecord(catalogue_id, category, at + timedelta(hours=delay),
        MarketObservation(source="EBAY", observation_type="SOLD", observed_at=at,
            price_gbp_minor=price, condition=condition, language=language,
            source_country="GB", source_record_key=str(n)))


def summary(rows):
    return evaluate_accuracy(rows)["overall_windows"]["5"]


def test_measures_later_sales_and_preserves_empty_collectible_categories():
    r = evaluate_accuracy([record(n) for n in range(7)], expected_categories=["MANGA", "FIGURES"])
    assert r["overall_windows"]["5"]["n"] == 2
    assert r["overall_windows"]["5"]["median_absolute_percentage_error"] == 0
    assert r["overall_windows"]["5"]["within_10_percent"] == 1
    assert r["production_prices_changed"] is False
    assert next(c for c in r["categories"] if c["category"] == "MANGA")["windows"]["5"]["n"] == 0
    assert next(c for c in r["categories"] if c["category"] == "FIGURES")["windows"]["5"]["median_absolute_error_gbp"] is None


def test_historical_bulk_import_cannot_be_used_before_it_was_available():
    rows = [replace(record(n), available_at=NOW + timedelta(days=9)) for n in range(7)]
    assert summary(rows)["n"] == 0


def test_holdout_and_simultaneous_batch_cannot_leak_into_prediction():
    rows = [record(n) for n in range(4)]
    rows += [replace(record(4), available_at=NOW + timedelta(days=5)), record(5, 999999)]
    assert summary(rows)["n"] == 0


def test_same_sale_reimport_is_one_transaction_not_extra_confidence():
    rows = [record(n) for n in range(4)]
    rows += [replace(rows[0], available_at=NOW + timedelta(hours=2)), record(5)]
    result = evaluate_accuracy(rows)
    assert result["independent_sales"] == 5
    assert result["overall_windows"]["5"]["n"] == 0


def test_conflicting_sale_prices_are_quarantined():
    rows = [record(n) for n in range(6)]
    rows.append(replace(rows[0], observation=replace(rows[0].observation, price_gbp_minor=9999)))
    result = evaluate_accuracy(rows)
    assert result["conflicting_sale_ids"] == 1
    assert result["overall_windows"]["5"]["n"] == 0


def test_sale_id_assigned_to_two_products_cannot_count_for_either():
    rows = [record(n) for n in range(6)]
    rows.append(replace(rows[0], catalogue_id="other-edition"))
    assert summary(rows)["n"] == 0


def test_later_conflict_does_not_rewrite_information_known_at_prediction_time():
    rows = [record(n) for n in range(6)]
    rows.append(replace(rows[0], catalogue_id="other-edition", available_at=NOW + timedelta(days=8)))
    assert summary(rows)["n"] == 1


def test_prices_from_other_editions_conditions_and_languages_cannot_fill_minimum():
    rows = [record(n) for n in range(4)]
    rows += [record(4, catalogue_id="edition-2"), record(5, condition="Lightly Played"),
             record(6, language="Japanese"), record(7)]
    assert summary(rows)["n"] == 0


def test_stale_sales_cannot_fill_minimum():
    rows = [record(n - 100) for n in range(5)] + [record(0)]
    assert summary(rows)["n"] == 0


def test_sold_evidence_is_required_not_active_asks_us_prices_or_guides():
    rows = [record(n) for n in range(7)]
    rows[0] = replace(rows[0], observation=replace(rows[0].observation, observation_type="ACTIVE"))
    rows[1] = replace(rows[1], observation=replace(rows[1].observation, source_country="US"))
    rows[2] = replace(rows[2], observation=replace(rows[2].observation, source="CARDMARKET", observation_type="PRICE_GUIDE"))
    result = evaluate_accuracy(rows)
    assert result["invalid_records"] == 3
    assert result["overall_windows"]["5"]["n"] == 0


def test_windows_are_scored_on_same_holdouts_and_measure_bias():
    rows = [record(n, 1000 if n < 10 else 2000) for n in range(16)]
    result = evaluate_accuracy(rows)
    assert {r["n"] for r in result["overall_windows"].values()} == {11}
    assert result["overall_windows"]["20"]["median_signed_percentage_error"] <= 0
    assert result["overall_windows"]["20"]["median_absolute_error_gbp"] >= 0
    assert result["scored_sales_with_more_than_five_prior"] == 10
    assert result["maximum_prior_sales"] == 15
    assert result["price_tiers"]["GBP_5_TO_50"]["5"]["n"] == 11


def test_input_order_and_duplicate_receipt_order_do_not_affect_results():
    rows = [record(n) for n in range(12)] + [replace(record(0), available_at=NOW + timedelta(hours=2))]
    assert evaluate_accuracy(rows) == evaluate_accuracy(rows[::-1])


def test_invalid_timezone_or_negative_money_is_reported():
    rows = [record(0, -1), replace(record(1), available_at=NOW.replace(tzinfo=None))]
    assert evaluate_accuracy(rows)["invalid_records"] == 2


def test_delivery_comparisons_use_known_postage_and_do_not_change_item_basis():
    rows = [replace(record(n, 1000 if n < 5 else 1500),
                    shipping_gbp_minor=500 if n < 5 else 0) for n in range(6)]
    item = evaluate_accuracy(rows)
    delivered = evaluate_accuracy(rows, price_basis="delivered")
    assert item["overall_windows"]["5"]["median_absolute_error_gbp"] == 5
    assert delivered["overall_windows"]["5"]["median_absolute_error_gbp"] == 0
    assert delivered["price_basis"] == "GBP_DELIVERED_PRICE"
    assert rows[0].observation.price_gbp_minor == 1000


def test_missing_shipping_is_not_assumed_free():
    rows = [replace(record(n), shipping_gbp_minor=0) for n in range(5)] + [record(5)]
    result = evaluate_accuracy(rows, price_basis="delivered")
    assert result["missing_or_invalid_shipping_records"] == 1
    assert result["overall_windows"]["5"]["n"] == 0


def test_postgres_numeric_quality_is_parsed_by_offline_cli(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    script = Path(__file__).parents[1] / "backend/scripts/replay_pricing_accuracy.py"
    spec = importlib.util.spec_from_file_location("pricing_accuracy_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = []
    for n in range(6):
        r = record(n)
        from dataclasses import asdict
        value = asdict(r.observation)
        value.update(catalogue_id=r.catalogue_id, category=r.category,
                     observed_at=r.observation.observed_at.isoformat(),
                     ingested_at=r.available_at.isoformat(), evidence_quality="1.0000")
        rows.append(value)
    path = tmp_path / "normalized.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert summary(module.read_records(path))["n"] == 1

