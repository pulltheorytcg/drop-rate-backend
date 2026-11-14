"""Official Cardmarket bulk audit cannot publish estimates or invent mappings."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.cardmarket_bulk_feed_audit import GAME_IDS, SCHEMA, audit_bulk_exports
from app.cardmarket_public_pilot import PilotError

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def fixtures():
    stamp = (NOW - timedelta(hours=4)).isoformat()
    products = {"version": 1, "createdAt": stamp, "products": [
        {"idProduct": 101, "name": "Card A", "categoryName": "Pokemon Single",
         "idCategory": 6},
        {"idProduct": 102, "name": "Card B", "categoryName": "Pokemon Single",
         "idCategory": 6},
    ]}
    prices = {"version": 1, "createdAt": stamp, "priceGuides": [
        {"idProduct": 101, "idCategory": 6, "trend": 900.0, "low": 1.0},
        {"idProduct": 103, "idCategory": 6, "trend": 0.2},
    ]}
    return products, prices


def run(products=None, prices=None, game="pokemon", kind="singles"):
    a, b = fixtures()
    return audit_bulk_exports(game=game, product_kind=kind,
                              products_export=a if products is None else products,
                              price_export=b if prices is None else prices, now=NOW)


@pytest.mark.parametrize("game", sorted(GAME_IDS))
def test_every_declared_game_returns_metadata_only(game):
    result = run(game=game)
    assert result["schema"] == SCHEMA
    assert result["status"] == "REVIEW_ONLY_SOURCE_ALIGNMENT"
    assert result["source_id_intersection_count"] == 1
    assert result["catalogue_without_guide_row_count"] == 1
    assert result["price_guide_rows_outside_selected_catalogue"] == 1
    assert result["canonical_printings_verified"] == 0
    assert result["verified_item_level_sales"] == 0
    assert result["physical_market_values_added"] == 0
    assert result["publishable"] is False
    assert result["commercial_display_permission"] == "NOT_VERIFIED"
    assert result["database_writes"] == result["shopify_writes"] == 0
    assert not any("amount" in k or "market_value_minor" in k for k in result)


@pytest.mark.parametrize("wrong", ["naruto", "", "dragon_ball", "magic_sealed"])
def test_unreviewed_game_is_blocked(wrong):
    with pytest.raises(PilotError, match="Unsupported"):
        run(game=wrong)


def test_input_files_are_untouched_and_source_low_and_rogue_trend_not_used():
    products, guides = fixtures()
    before = deepcopy((products, guides))
    result = run(products, guides)
    assert (products, guides) == before
    assert result["source_id_intersection_count"] == 1
    assert "trend" not in str(result) and "900" not in str(result)


@pytest.mark.parametrize("which", ["product", "guide"])
def test_duplicate_id_aborts_before_any_coverage_claim(which):
    products, guides = fixtures()
    container, key = (products, "products") if which == "product" else (guides, "priceGuides")
    container[key].append(deepcopy(container[key][0]))
    with pytest.raises(PilotError, match="duplicate"):
        run(products, guides)


def test_mismatched_product_and_guide_category_aborts():
    products, guides = fixtures()
    guides["priceGuides"][0]["idCategory"] = 19
    with pytest.raises(PilotError, match="Conflicting"):
        run(products, guides)


@pytest.mark.parametrize("version", [2, False, "1", 0])
def test_unknown_schema_fails_closed(version):
    products, guides = fixtures()
    guides["version"] = version
    with pytest.raises(PilotError, match="schema version"):
        run(products, guides)


def test_stale_and_future_source_fail_closed():
    products, guides = fixtures()
    products["createdAt"] = (NOW - timedelta(days=4)).isoformat()
    with pytest.raises(PilotError, match="stale"):
        run(products, guides)
    products["createdAt"] = (NOW + timedelta(minutes=1)).isoformat()
    with pytest.raises(PilotError, match="future"):
        run(products, guides)


def test_source_dates_must_agree():
    products, guides = fixtures()
    guides["createdAt"] = (NOW - timedelta(days=2, hours=8)).isoformat()
    with pytest.raises(PilotError, match="inconsistent"):
        run(products, guides)


@pytest.mark.parametrize("mutation", [
    {"name": ""}, {"categoryName": ""}, {"idProduct": 0},
    {"idCategory": "bad"},
])
def test_corrupt_source_product_rejected(mutation):
    products, guides = fixtures()
    products["products"][0].update(mutation)
    with pytest.raises(PilotError):
        run(products, guides)


def test_sealed_catalogue_is_also_a_non_publishing_audit():
    result = run(kind="nonsingles")
    assert result["product_kind"] == "nonsingles"
    assert result["physical_market_values_added"] == 0


@pytest.mark.asyncio
async def test_official_fetch_only_and_no_redirects_or_credentials():
    from scripts.audit_cardmarket_bulk_feed import _read_source
    import httpx
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("price_guide_6.json"):
            return httpx.Response(302, headers={"location": "https://example.com"})
        return httpx.Response(200, json=fixtures()[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PilotError, match="unavailable"):
            await _read_source(client, "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json")
        with pytest.raises(PilotError, match="Unexpected"):
            await _read_source(client, "https://example.com/productCatalog/priceGuide/price_guide_6.json")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_oversized_download_aborts_without_parsing():
    from scripts.audit_cardmarket_bulk_feed import _read_source
    import httpx
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"content-length": "64000001"}, content=b"{}")
    )) as client:
        with pytest.raises(PilotError, match="byte limit"):
            await _read_source(client, "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json")
