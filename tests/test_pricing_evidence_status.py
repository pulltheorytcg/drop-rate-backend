from datetime import datetime, timedelta, timezone

from app.pricing import summarize_sold_evidence


NOW = datetime(2026, 9, 25, 22, 30, tzinfo=timezone.utc)


def sold(
    key: str,
    price: int,
    *,
    days_old: int = 1,
    source: str = "EBAY",
    language: str | None = "English",
    condition: str | None = "Near Mint",
    grading_company: str | None = None,
    grade: str | None = None,
    seal_status: str | None = None,
    provider_item_id: str | None = None,
):
    return {
        "source": source,
        "source_record_key": key,
        "observation_type": "SOLD",
        "observed_at": NOW - timedelta(days=days_old),
        "price_gbp_minor": price,
        "shipping_gbp_minor": 0,
        "condition": condition,
        "grading_company": grading_company,
        "grade": grade,
        "language": language,
        "seal_status": seal_status,
        "source_country": "GB",
        "metadata": (
            {"provider_item_id": provider_item_id}
            if provider_item_id is not None
            else {}
        ),
    }


def raw_target(language: str = "English") -> dict:
    return {
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "language": language,
        "seal_status": None,
    }


def test_five_fresh_comps_are_enough_without_forcing_another_paid_refresh() -> None:
    observations = [
        sold(str(i), 1000 + (i * 10), days_old=i)
        for i in range(1, 6)
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target(),
        as_of=NOW,
        freshness_days=7,
    )

    assert result["status"] == "FRESH"
    assert result["selected_comp_count"] == 5
    assert result["target_reached"] is False
    assert result["refresh_recommended"] is False


def test_only_ten_newest_exact_comps_are_selected() -> None:
    observations = [
        sold(str(i), 1000 + i, days_old=i)
        for i in range(1, 13)
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target(),
        as_of=NOW,
        freshness_days=30,
    )

    assert result["available_exact_sold_count"] == 12
    assert result["selected_comp_count"] == 10
    assert result["target_reached"] is True
    assert [item["source_record_key"] for item in result["selected_comps"]] == [
        str(i) for i in range(1, 11)
    ]


def test_duplicate_sale_from_two_access_paths_is_counted_once() -> None:
    observations = [
        sold("trawl-a", 1200, days_old=1, provider_item_id="ebay-123"),
        sold("official-a", 1200, days_old=1, provider_item_id="ebay-123"),
        sold("b", 1210, days_old=2, provider_item_id="ebay-124"),
        sold("c", 1220, days_old=3, provider_item_id="ebay-125"),
        sold("d", 1230, days_old=4, provider_item_id="ebay-126"),
        sold("e", 1240, days_old=5, provider_item_id="ebay-127"),
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target(),
        as_of=NOW,
        freshness_days=7,
    )

    assert result["available_exact_sold_count"] == 5
    assert result["selected_comp_count"] == 5
    assert result["refresh_recommended"] is False


def test_stale_evidence_requests_refresh_even_with_five_comps() -> None:
    observations = [
        sold(str(i), 1000 + i, days_old=20 + i)
        for i in range(1, 6)
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target(),
        as_of=NOW,
        freshness_days=7,
    )

    assert result["status"] == "STALE"
    assert result["selected_comp_count"] == 5
    assert result["refresh_recommended"] is True
    assert "STALE_NEWEST_COMP" in result["refresh_reasons"]


def test_language_is_an_exact_pricing_identity_boundary() -> None:
    observations = [
        sold("en-1", 1000, language="English"),
        sold("jp-1", 5000, language="Japanese"),
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target("English"),
        as_of=NOW,
    )

    assert result["available_exact_sold_count"] == 1
    assert result["selected_comps"][0]["source_record_key"] == "en-1"


def test_grade_is_an_exact_pricing_identity_boundary() -> None:
    observations = [
        sold(
            "psa10",
            10000,
            condition=None,
            grading_company="PSA",
            grade="10",
        ),
        sold(
            "psa9",
            7000,
            condition=None,
            grading_company="PSA",
            grade="9",
        ),
        sold("raw", 3000),
    ]
    target = {
        "condition": None,
        "grading_company": "PSA",
        "grade": "10",
        "language": "English",
        "seal_status": None,
    }

    result = summarize_sold_evidence(
        observations,
        target=target,
        as_of=NOW,
    )

    assert result["available_exact_sold_count"] == 1
    assert result["selected_comps"][0]["source_record_key"] == "psa10"


def test_raw_mean_and_median_are_retained_for_outlier_aware_pricing() -> None:
    observations = [
        sold("1", 1800),
        sold("2", 1900),
        sold("3", 2000),
        sold("4", 2100),
        sold("5", 9000),
    ]

    result = summarize_sold_evidence(
        observations,
        target=raw_target(),
        as_of=NOW,
    )

    assert result["raw_mean_minor"] == 3360
    assert result["median_minor"] == 2000
    assert result["raw_mean_minor"] > result["median_minor"]


def test_non_sold_rows_do_not_count_as_sold_history() -> None:
    row = sold("active", 1000)
    row["observation_type"] = "ACTIVE"

    result = summarize_sold_evidence(
        [row],
        target=raw_target(),
        as_of=NOW,
    )

    assert result["status"] == "EMPTY"
    assert result["selected_comp_count"] == 0
    assert result["refresh_recommended"] is True
