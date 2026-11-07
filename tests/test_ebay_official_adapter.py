from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.ebay_official_adapter import (
    EbayOfficialBrowseAdapter,
    _looks_like_multi_item_listing,
    _matches_listing,
    _money_minor,
    _shipping_minor,
    _listing_language,
    _active_fixed_price,
    _variant_matches,
)
from app.ebay_uk_parse_adapter import _parse_mapping_spec


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"


class FakeEbayClient:
    marketplace_id = "EBAY_GB"

    async def search_items(self, **kwargs):
        assert kwargs["item_location_country"] == "GB"
        return {
            "itemSummaries": [
                {
                    "itemId": "v1|123|0",
                    "title": "Absol 063/094 Phantasmal Flames Pokemon English",
                    "price": {"value": "12.50", "currency": "GBP"},
                    "condition": "Ungraded - Near mint or better",
                    "itemLocation": {"country": "GB"},
                    "shippingOptions": [
                        {"shippingCost": {"value": "2.99", "currency": "GBP"}}
                    ],
                    "itemWebUrl": "https://www.ebay.co.uk/itm/123",
                    "buyingOptions": ["FIXED_PRICE"],
                },
                {
                    "itemId": "v1|124|0",
                    "title": "Absol 063/094 Reverse Holo Phantasmal Flames",
                    "price": {"value": "20.00", "currency": "GBP"},
                    "condition": "Ungraded - Near mint or better",
                    "itemLocation": {"country": "GB"},
                    "itemWebUrl": "https://www.ebay.co.uk/itm/124",
                },
                {
                    "itemId": "v1|125|0",
                    "title": "Absol 063/094 PSA 10 Phantasmal Flames",
                    "price": {"value": "50.00", "currency": "GBP"},
                    "itemLocation": {"country": "GB"},
                    "itemWebUrl": "https://www.ebay.co.uk/itm/125",
                },
                {
                    "itemId": "v1|126|0",
                    "title": "Absol 063/094 Phantasmal Flames Pokemon",
                    "price": {"value": "9.00", "currency": "USD"},
                    "itemLocation": {"country": "GB"},
                },
                {
                    "itemId": "v1|127|0",
                    "title": "Absol 063/094 Phantasmal Flames Pokemon",
                    "price": {"value": "10.00", "currency": "GBP"},
                    "itemLocation": {"country": "US"},
                },
            ]
        }


def mapping(**overrides) -> str:
    payload = {
        "query": "Absol 063/094 Phantasmal Flames",
        "required_title_terms": ["Absol", "063/094"],
        "forbidden_title_terms": ["proxy", "custom", "digital"],
        "language": "English",
        "include_sold": True,
        "include_active": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_official_browse_emits_only_exact_gb_active_evidence() -> None:
    adapter = EbayOfficialBrowseAdapter(client=FakeEbayClient())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=mapping(),
        source_variant_id="Normal",
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.observation_type == "ACTIVE"
    assert observation.price_gbp_minor == 1250
    assert observation.shipping_gbp_minor == 299
    assert observation.condition == "Near Mint"
    assert observation.language == "English"
    assert observation.source_country == "GB"
    assert observation.metadata["access_method"] == "OFFICIAL_EBAY_BROWSE"
    assert observation.metadata["marketplace"] == "EBAY_GB"
    assert observation.metadata["sold_history_available"] is False


@pytest.mark.asyncio
async def test_official_browse_never_synthesizes_sold_history() -> None:
    adapter = EbayOfficialBrowseAdapter(client=FakeEbayClient())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=mapping(include_sold=True, include_active=True),
        source_variant_id="Normal",
    )

    assert observations
    assert {item.observation_type for item in observations} == {"ACTIVE"}


def test_variant_matching_is_finish_specific() -> None:
    assert _variant_matches("Absol 063/094 Pokemon", "Normal") is True
    assert _variant_matches("Absol 063/094 Reverse Holo", "Normal") is False
    assert _variant_matches("Absol 063/094 Foil", "Normal") is False
    assert _variant_matches("Absol 063/094 Reverse Holo", "Reverse Holofoil") is True
    assert _variant_matches("Absol 063/094 Holo", "Holofoil") is True
    assert _variant_matches("Absol 063/094 Reverse Holo", "Holofoil") is False
    assert _variant_matches("Absol 063/094 Non Holo", "Holofoil") is False
    assert _variant_matches("Absol 063/094 Non-Holofoil", "Holofoil") is False
    assert _variant_matches("Monkey D Luffy OP05-119 Foil", "Foil") is True
    assert _variant_matches("Monkey D Luffy OP05-119 Non Foil", "Foil") is False


def test_money_parser_requires_gbp() -> None:
    assert _money_minor({"value": "12.34", "currency": "GBP"}) == 1234
    assert _money_minor({"value": "12.34", "currency": "USD"}) is None
    assert _money_minor({"value": "0", "currency": "GBP"}) is None


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "1e100000", "-1", "0.00001", True, None])
def test_invalid_price_is_rejected_without_aborting_batch(value) -> None:
    assert _money_minor({"value": value, "currency": "GBP"}) is None


def test_shipping_preserves_known_free_and_unknown_costs() -> None:
    assert _shipping_minor({"shippingOptions": [{"shippingCost": {"value": "0", "currency": "GBP"}}]}) == 0
    assert _shipping_minor({}) is None
    assert _shipping_minor({"shippingOptions": [{"shippingCost": {"value": "0", "currency": "EUR"}}]}) is None
    assert _shipping_minor({"shippingOptions": [
        {"shippingCost": {"value": "2.99", "currency": "GBP"}},
        {"shippingCost": {"value": "0.00", "currency": "GBP"}},
    ]}) == 0


def test_language_comes_from_returned_listing_not_search_mapping() -> None:
    assert _listing_language({"title": "Absol 063/094 Pokemon"}) == (None, False)
    assert _listing_language({"title": "Absol 063/094 English"}) == ("English", False)
    assert _listing_language({"title": "Absol 063/094 JP"}) == ("Japanese", False)
    assert _listing_language({"localizedAspects": [{"name": "Language", "value": "English"}]}) == ("English", False)
    assert _listing_language({"title": "Absol 063/094 Japanese", "localizedAspects": [{"name": "Language", "value": "English"}]}) == (None, True)


def test_active_evidence_requires_buy_now_and_unexpired_listing() -> None:
    now = datetime.now(timezone.utc)
    assert _active_fixed_price({"buyingOptions": ["FIXED_PRICE", "BEST_OFFER"]}, now)
    assert not _active_fixed_price({"buyingOptions": ["AUCTION"]}, now)
    assert not _active_fixed_price({}, now)
    assert not _active_fixed_price({"buyingOptions": ["FIXED_PRICE"], "itemEndDate": (now - timedelta(seconds=1)).isoformat()}, now)
    assert not _active_fixed_price({"buyingOptions": ["FIXED_PRICE"], "itemEndDate": "invalid"}, now)
    assert not _active_fixed_price({"buyingOptions": ["FIXED_PRICE"], "itemEndDate": "2027-01-01"}, now)


@pytest.mark.parametrize("title", [
    "Charizard V 019/189 Holo PSA 9.5",
    "Charizard V 019/189 Holo PSA 90",
    "Charizard V 019/189 Holo PSA 9/10",
    "Charizard V 019/189 Holo PSA 10 with 9 cards",
    "Charizard V 019/189 Holo PSA 9 BGS 9",
])
def test_grade_is_exact_and_bound_to_the_grading_company(title) -> None:
    spec = _parse_mapping_spec(mapping(required_title_terms=["Charizard V", "019/189"], grading_company="PSA", grade="9"))
    assert not _matches_listing(title, spec=spec, source_variant_id="Holofoil")


def test_card_rarity_ace_spec_is_not_another_grading_company() -> None:
    spec = _parse_mapping_spec(mapping(required_title_terms=["Prime Catcher", "157/162"], grading_company="PSA", grade="9"))
    assert _matches_listing("Prime Catcher 157/162 Holo ACE SPEC PSA 9", spec=spec, source_variant_id="Holofoil")


class RowsClient:
    marketplace_id = "EBAY_GB"

    def __init__(self, rows):
        self.rows = rows

    async def search_items(self, **kwargs):
        assert kwargs["fixed_price_only"] is True
        assert kwargs["item_location_country"] == "GB"
        return {"itemSummaries": self.rows}


def active_row(**overrides):
    row = {
        "itemId": "v1|123|0",
        "title": "Absol 063/094 Phantasmal Flames English",
        "price": {"value": "12.50", "currency": "GBP"},
        "condition": "Ungraded - Near mint or better",
        "itemLocation": {"country": "GB"},
        "buyingOptions": ["FIXED_PRICE"],
        "shippingOptions": [{"shippingCost": {"value": "0", "currency": "GBP"}}],
    }
    row.update(overrides)
    return row


async def fetch_rows(rows):
    return await EbayOfficialBrowseAdapter(client=RowsClient(rows)).fetch_observations(
        catalogue_id=CATALOGUE_ID, source_product_id=mapping(), source_variant_id="Normal",
    )


@pytest.mark.asyncio
async def test_duplicate_listings_are_one_comparable_and_conflicts_are_quarantined() -> None:
    row = active_row()
    accepted = await fetch_rows([row, dict(row)])
    assert len(accepted) == 1
    assert accepted[0].shipping_gbp_minor == 0
    assert accepted[0].metadata["shipping_known"] is True
    assert await fetch_rows([row, active_row(price={"value": "99", "currency": "GBP"}), row]) == []


@pytest.mark.asyncio
async def test_unknown_language_and_postage_are_not_invented() -> None:
    observations = await fetch_rows([active_row(title="Absol 063/094 Phantasmal Flames", shippingOptions=[])])
    assert len(observations) == 1
    assert observations[0].language is None
    assert observations[0].shipping_gbp_minor is None
    assert observations[0].metadata["shipping_known"] is False
    assert observations[0].metadata["language_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"title": "Absol 063/094 Phantasmal Flames Japanese"},
    {"title": "Absol 063/094 Phantasmal Flames English Japanese"},
    {"itemId": 123},
    {"itemId": "not-a-provider-id"},
    {"itemLocation": {"country": "US"}},
    {"itemLocation": {}},
    {"price": {"value": "NaN", "currency": "GBP"}},
    {"buyingOptions": ["AUCTION"]},
    {"itemEndDate": "2000-01-01T00:00:00Z"},
])
async def test_ambiguous_non_gb_or_unpurchasable_rows_are_excluded(overrides) -> None:
    assert await fetch_rows([active_row(**overrides)]) == []


def test_multi_item_detection_rejects_lots_and_multiple_card_numbers() -> None:
    assert _looks_like_multi_item_listing("Absol 063/094 Pokemon") is False
    assert _looks_like_multi_item_listing("Absol 063/094 x4 Pokemon") is True
    assert _looks_like_multi_item_listing("Absol 063/094 And Gastly 054/094") is True
    assert _looks_like_multi_item_listing("Pokemon card bundle Absol 063/094") is True
    assert _looks_like_multi_item_listing("Luffy OP05-119 + Zoro OP06-118") is True
    assert _looks_like_multi_item_listing("Luffy OP05-119 OP05-119") is False


def test_identity_rules_reject_wrong_rarity_and_reprints() -> None:
    spec = _parse_mapping_spec(
        mapping(
            required_title_terms=["Monkey D Luffy", "OP05-119", "SEC"],
            forbidden_title_terms=[
                "SR",
                "reprint",
                "premium booster",
                "the best",
                "proxy",
                "custom",
                "digital",
            ],
        )
    )

    assert _matches_listing(
        "Monkey.D.Luffy OP05-119 SEC Awakening of the New Era Foil NM",
        spec=spec,
        source_variant_id="Foil",
    ) is True
    assert _matches_listing(
        "Bandai One Piece OP05 Monkey D. Luffy OP05-119 SR Foil",
        spec=spec,
        source_variant_id="Foil",
    ) is False
    assert _matches_listing(
        "Monkey.D.Luffy Reprint OP05-119 Premium Booster The Best One Piece Foil",
        spec=spec,
        source_variant_id="Foil",
    ) is False


def test_graded_listing_missing_finish_fails_closed() -> None:
    spec = _parse_mapping_spec(
        mapping(
            required_title_terms=["Charizard V", "019/189"],
            grading_company="PSA",
            grade="9",
        )
    )

    assert _matches_listing(
        "Pokemon Charizard V 019/189 PSA 9",
        spec=spec,
        source_variant_id="Holofoil",
    ) is False
    assert _matches_listing(
        "Pokemon Charizard V 019/189 Holo PSA 9",
        spec=spec,
        source_variant_id="Holofoil",
    ) is True
    assert _matches_listing(
        "Pokemon Charizard V 019/189 Reverse Holo PSA 9",
        spec=spec,
        source_variant_id="Holofoil",
    ) is False

