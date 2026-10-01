from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ebay_sealed_pricing import (
    _sealed_comp_matches,
    _sealed_query,
    _select_five_sold,
)


ROOT = Path(__file__).resolve().parents[1]
SEALED_PRICING = ROOT / "backend" / "app" / "ebay_sealed_pricing.py"
OWNER_API = ROOT / "backend" / "app" / "owner_portal_api.py"


def target(**overrides) -> dict:
    values = {
        "set_code": "OP-17",
        "language": "Japanese",
        "sealed_product_type": "BOOSTER_PACK",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "title",
    [
        "One Piece Card Game OP-17 Japanese Booster Pack New Sealed",
        "ONE PIECE OP17 JP Single Booster Pack Sealed",
        "One Piece OP 17 Japanese 1 Pack New",
    ],
)
def test_japanese_op17_single_pack_titles_match(title: str) -> None:
    assert _sealed_comp_matches({"title": title}, target()) is True


@pytest.mark.parametrize(
    "title",
    [
        "One Piece OP-17 Japanese Booster Box 24 Packs",
        "One Piece OP17 JP Display Box",
        "One Piece OP-17 Japanese Case of Booster Packs",
        "One Piece OP-17 Japanese Booster Pack Bundle x12",
        "One Piece OP-17 English Booster Pack",
        "One Piece OP-16 Japanese Booster Pack",
    ],
)
def test_box_multipack_language_and_wrong_set_titles_fail_closed(title: str) -> None:
    assert _sealed_comp_matches({"title": title}, target()) is False


def test_sealed_query_is_specific_to_game_code_language_and_unit() -> None:
    query = _sealed_query(target())
    assert "One Piece" in query
    assert "OP-17" in query
    assert "Japanese" in query
    assert "booster pack" in query


def test_select_five_sold_requires_gbp_and_returns_five_newest_exact_packs() -> None:
    rows = []
    for index in range(7):
        rows.append(
            {
                "item_id": f"good-{index}",
                "title": "One Piece OP-17 Japanese Booster Pack Sealed",
                "date_sold": f"2026-09-{20 + index:02d}T12:00:00Z",
                "sale_price": f"{4.00 + index / 10:.2f}",
                "shipping_price": "1.55",
                "item_link": f"https://example.test/good-{index}",
            }
        )
    rows.extend(
        [
            {
                "item_id": "box",
                "title": "One Piece OP-17 Japanese Booster Box 24 Packs",
                "date_sold": "2026-09-30T12:00:00Z",
                "sale_price": "95.00",
                "shipping_price": "0",
            },
            {
                "item_id": "english",
                "title": "One Piece OP-17 English Booster Pack",
                "date_sold": "2026-09-30T12:00:00Z",
                "sale_price": "5.00",
                "shipping_price": "0",
            },
        ]
    )
    comps = _select_five_sold({"currency": "GBP", "results": rows}, target())

    assert len(comps) == 5
    assert [item["item_id"] for item in comps] == [
        "good-6",
        "good-5",
        "good-4",
        "good-3",
        "good-2",
    ]


def test_select_five_sold_rejects_non_gbp_payload() -> None:
    with pytest.raises(ValueError, match="GBP"):
        _select_five_sold({"currency": "EUR", "results": []}, target())


def test_sealed_pricing_performs_provider_io_between_short_db_phases() -> None:
    source = SEALED_PRICING.read_text()
    function = source[source.index("async def refresh_verified_sealed_ebay_market"):]

    snapshot_index = function.index("target = await _snapshot(")
    provider_index = function.index("result = await _fetch_uk_sold(target)")
    persist_index = function.index("async with user_connection(", provider_index)

    assert snapshot_index < provider_index < persist_index
    assert "Provider HTTP is performed between two short user-scoped DB transactions." in function


def test_sealed_pricing_writes_ebay_sold_gb_observations_then_uses_normal_pricing_engine() -> None:
    source = SEALED_PRICING.read_text()

    assert 'source="EBAY"' in source
    assert 'observation_type="SOLD"' in source
    assert 'source_country="GB"' in source
    assert 'seal_status="SEALED"' in source
    assert 'selection_rule": "FIVE_NEWEST_EXACT_SEALED_PACK_SALES"' in source
    assert '_recalculate_one(connection, owner_id, target["id"])' in source


def test_owner_market_refresh_delegates_to_transaction_safe_sealed_pricer() -> None:
    source = OWNER_API.read_text()
    start = source.index('@router.post("/inventory/{inventory_code}/refresh-market")')
    end = source.index('@router.post("/graded-certificate-intake"', start)
    block = source[start:end]

    assert "refresh_verified_sealed_ebay_market(" in block
    assert "user_connection(" not in block
    assert 'result.get("status") == "BLOCKED"' in block
