from pathlib import Path

import pytest

from app.ebay_sold_pricing import (
    _matches_comp,
    _query_for_target,
    five_sold_market_value,
    five_sold_store_price,
    select_five_newest_comps,
)


ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "backend" / "app"


def target(**overrides):
    value = {
        "catalogue_id": "00000000-0000-0000-0000-000000000001",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "language": "English",
    }
    value.update(overrides)
    return value


def sold(
    item_id: str,
    *,
    title: str = "Pokemon Seel 021/094 Phantasmal Flames NM",
    price: float = 5.0,
    date: str = "2026-09-20T00:00:00.000Z",
    condition_raw: str = "Ungraded - Near mint or better",
):
    return {
        "title": title,
        "sale_price": price,
        "shipping_price": 1.25,
        "currency": "£",
        "condition": "used",
        "condition_raw": condition_raw,
        "date_sold": date,
        "item_id": item_id,
        "item_link": f"https://www.ebay.co.uk/itm/{item_id}",
    }


def test_selects_five_newest_exact_comps_and_uses_median_item_price() -> None:
    payload = {
        "site": "EBAY_GB",
        "currency": "GBP",
        "results": [
            sold("1", price=5.0, date="2026-09-21T00:00:00.000Z"),
            sold("2", price=7.0, date="2026-09-25T00:00:00.000Z"),
            sold("3", price=6.0, date="2026-09-23T00:00:00.000Z"),
            sold("4", price=100.0, date="2026-09-24T00:00:00.000Z"),
            sold("5", price=4.0, date="2026-09-22T00:00:00.000Z"),
            sold("6", price=3.0, date="2026-09-20T00:00:00.000Z"),
            sold(
                "jp",
                title="Pokemon Seel 021/094 Phantasmal Flames JP Japanese NM",
                price=2.0,
                date="2026-09-26T00:00:00.000Z",
            ),
        ],
    }

    comps = select_five_newest_comps(payload, target=target())

    assert [comp.item_id for comp in comps] == ["2", "4", "3", "5", "1"]
    assert five_sold_store_price(comps) == 600
    assert comps[0].shipping_minor == 125


def test_non_gbp_response_fails_closed() -> None:
    with pytest.raises(ValueError, match="GBP"):
        select_five_newest_comps(
            {"site": "EBAY_US", "currency": "USD", "results": [sold("1")]},
            target=target(),
        )


def test_wrong_language_finish_grade_and_bundle_are_rejected() -> None:
    base = target()
    assert not _matches_comp(
        sold("jp", title="Seel 021/094 Japanese JP NM"),
        base,
    )
    assert not _matches_comp(
        sold("holo", title="Seel 021/094 Holo NM"),
        base,
    )
    assert not _matches_comp(
        sold("psa", title="Seel 021/094 PSA 10"),
        base,
    )
    assert not _matches_comp(
        sold("lot", title="Seel 021/094 bundle x2 NM"),
        base,
    )


def test_japanese_requires_positive_language_evidence() -> None:
    jp = target(language="Japanese")
    assert _matches_comp(
        sold("jp", title="Pokemon Seel 021/094 Japanese JP Near Mint"),
        jp,
    )
    assert not _matches_comp(
        sold("en", title="Pokemon Seel 021/094 English Near Mint"),
        jp,
    )


def test_graded_requires_exact_company_and_grade() -> None:
    psa10 = target(
        condition=None,
        grading_company="PSA",
        grade="10",
    )
    assert _matches_comp(
        sold("10", title="Pokemon Seel 021/094 PSA 10"),
        psa10,
    )
    assert not _matches_comp(
        sold("9", title="Pokemon Seel 021/094 PSA 9"),
        psa10,
    )
    assert not _matches_comp(
        sold("raw", title="Pokemon Seel 021/094 Near Mint"),
        psa10,
    )


def test_one_piece_default_foil_does_not_require_foil_word_but_reprint_is_rejected() -> None:
    op = target(
        game="One Piece",
        name="Monkey.D.Luffy",
        set_name="Awakening of the New Era",
        card_number="OP05-119",
        variant="Foil",
    )
    assert _matches_comp(
        sold(
            "original",
            title="One Piece Monkey D Luffy OP05-119 SEC English Near Mint",
        ),
        op,
    )
    assert not _matches_comp(
        sold(
            "reprint",
            title="One Piece Monkey D Luffy OP05-119 PRB01 The Best English Near Mint",
        ),
        op,
    )


def test_explicit_parallel_marker_must_be_present() -> None:
    parallel = target(
        game="One Piece",
        name="Foxy (Parallel)",
        set_name="Egghead Crisis",
        card_number="EB04-036",
        variant="Foil",
    )
    assert _matches_comp(
        sold(
            "parallel",
            title="One Piece Foxy Parallel EB04-036 English Near Mint",
        ),
        parallel,
    )
    assert not _matches_comp(
        sold(
            "base",
            title="One Piece Foxy EB04-036 English Near Mint",
        ),
        parallel,
    )


def test_collectr_numeric_disambiguator_is_not_required_in_search_query() -> None:
    query = _query_for_target(
        target(
            game="One Piece",
            name="Monkey.D.Luffy (073)",
            set_name="500 Years in the Future",
            card_number="OP07-073",
            variant="Foil",
        )
    )
    assert "(073)" not in query
    assert "Monkey.D.Luffy" in query
    assert "OP07-073" in query


def test_batch_pricing_reuses_one_lookup_across_missing_duplicate_copies() -> None:
    source = (BACKEND / "ebay_sold_pricing.py").read_text()
    assert "apply_group=True" in source
    assert "store_price_minor is null" in source
    assert "catalogue_id=$2" in source
    assert "language is not distinct from $6" in source
    assert "latest_pricing_snapshot_id" in source


def test_provider_io_is_explicitly_outside_database_write_transaction() -> None:
    source = (BACKEND / "ebay_sold_pricing.py").read_text()
    phase_1 = source.index("# Phase 1: short DB snapshot.")
    phase_2 = source.index("# Phase 2: provider I/O outside all DB transactions.")
    phase_3 = source.index("# Phase 3: re-lock, revalidate and write evidence + prices atomically.")
    provider_call = source.index("result = await _fetch_comp_result(target)")
    transaction = source.index("async with connection.transaction():", phase_3)
    assert phase_1 < phase_2 < provider_call < phase_3 < transaction


def test_english_search_query_stays_broad_and_post_filters_details() -> None:
    assert _query_for_target(target()) == "Seel 021/094"


def test_five_sold_pricing_requires_confirmed_identity_before_provider_lookup() -> None:
    source = (BACKEND / "ebay_sold_pricing.py").read_text()
    assert "i.identity_confirmed" in source
    assert "Canonical card identity must be confirmed before automated pricing" in source


def test_five_sold_floor_does_not_distort_market_value() -> None:
    comps = select_five_newest_comps(
        {
            "site": "EBAY_GB",
            "currency": "GBP",
            "results": [
                sold("1", price=0.20, date="2026-09-25T00:00:00.000Z"),
                sold("2", price=0.30, date="2026-09-24T00:00:00.000Z"),
                sold("3", price=0.35, date="2026-09-23T00:00:00.000Z"),
                sold("4", price=0.40, date="2026-09-22T00:00:00.000Z"),
                sold("5", price=0.50, date="2026-09-21T00:00:00.000Z"),
            ],
        },
        target=target(),
    )
    assert five_sold_market_value(comps) == 35
    assert five_sold_store_price(comps) == 100
