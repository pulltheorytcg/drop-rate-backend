from copy import deepcopy

import pytest

from scripts.seed_collectible_catalogue import load_seed, official_source_url, seed_sql, validate_seed


def test_reviewed_starter_preserves_exact_base_cards_and_distinct_figure_editions():
    rows = load_seed()["entries"]
    assert [(row["sports_card"]["subject_name"], row["sports_card"]["card_number"], row["sports_card"]["team"])
            for row in rows if row["sports_card"]] == [
        ("Bukayo Saka", "12", "Arsenal"), ("Cole Palmer", "100", "Chelsea"),
        ("Mohamed Salah", "174", "Liverpool FC"), ("Erling Haaland", "195", "Manchester City"),
    ]
    cards = [row for row in rows if row["sports_card"]]
    assert all(row["sports_card"]["parallel"] == "Base" and row["sports_card"]["print_run"] is None for row in cards)
    assert all(row["sports_card"]["season"] == "2025/26" and row["sports_card"]["release_year"] == 2025 for row in cards)
    figures = [row for row in rows if row["figure_details"]]
    assert [(row["figure_details"]["edition"], row["figure_details"]["barcode_gtin"]) for row in figures] == [
        ("3.0", "4571697188655"), ("3.0 [Basic]", "4580828662797"),
    ]
    assert figures[0]["id"] != figures[1]["id"]
    assert all(row["figure_details"]["manufacturer_sku"] is None and row["catalogue"]["language"] is None for row in figures)
    assert all(row["release_month"] == "2026-02" and row["release_date"] is None for row in figures)
    assert all(row["identity_key"].startswith("official-collectible:v1:") for row in rows)


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(identity_status="CONFIRMED"),
    lambda row: row.update(verification_scope="PHYSICAL_ITEM_VERIFIED"),
    lambda row: row.update(source_checked_at="2200-01-01"),
    lambda row: row.update(source_url="https://evil.test/facts"),
    lambda row: row.update(identity_key="manual:v1:some-existing-seller-record"),
    lambda row: row.update(id="00000000-0000-4000-8000-000000000001"),
    lambda row: row.update(price_minor=10000),
    lambda row: row["catalogue"].update(image_url="https://www.topps.com/image.jpg"),
    lambda row: row["sports_card"].update(subject_name="Another player"),
    lambda row: row["source_evidence"][0].update(url="https://www.topps.com@evil.test/checklist"),
    lambda row: row.update(source_evidence=[]),
])
def test_unreviewed_or_noncanonical_manifest_fails_before_rendering(mutate):
    data = deepcopy(load_seed())
    mutate(data["entries"][0])
    with pytest.raises(ValueError):
        seed_sql(data)


def test_future_edition_duplicate_source_and_sql_delimiter_are_rejected():
    data = deepcopy(load_seed())
    data["entries"][5]["release_month"] = "2099-02"
    with pytest.raises(ValueError, match="Future"):
        validate_seed(data)
    data = deepcopy(load_seed())
    data["entries"].append(deepcopy(data["entries"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_seed(data)
    for delimiter in ("$collectibleseed$", "$seedbody$"):
        data = deepcopy(load_seed())
        data["entries"][0]["language_scope"] = delimiter
        with pytest.raises(ValueError, match="delimiter"):
            seed_sql(data)


@pytest.mark.parametrize("url", [
    "http://www.topps.com/pages/checklists/example", "https://www.goodsmile.com.evil.test/en/product/1",
    "https://www.goodsmile.com:444/en/product/1", "https://cdn.shopify.com/unrelated.pdf",
    "https://www.goodsmile.com/en/product/1?redirect=https://evil.test", "javascript:alert(1)",
])
def test_source_urls_stay_on_reviewed_official_origins(url):
    assert not official_source_url(url)


def test_sql_is_metadata_only_and_never_upserts_or_approves_existing_seller_rows():
    sql = seed_sql(load_seed())
    for table in ("inventory_items", "media_assets", "pricing_snapshots", "reference_market_prices", "shopify_inventory_links"):
        assert table not in sql
    assert "on conflict" not in sql.lower()
    assert sql.lower().count("update tcg.") == 1
    assert "update tcg.collectible_systems" in sql.lower()
    assert "OFFICIAL_CATALOGUE" in sql
    assert "Equivalent collectible exists under another identity" in sql
    assert sql.startswith("begin;") and sql.rstrip().endswith("commit;")
