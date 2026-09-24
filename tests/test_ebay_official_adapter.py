from __future__ import annotations

import json

import pytest

from app.ebay_official_adapter import (
    EbayOfficialBrowseAdapter,
    _looks_like_multi_item_listing,
    _matches_listing,
    _money_minor,
    _variant_matches,
)


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"


class FakeEbayClient:
    marketplace_id = "EBAY_GB"

    async def search_items(self, **kwargs):
        assert kwargs["item_location_country"] == "GB"
        return {
            "itemSummaries": [
                {
                    "itemId": "v1|123|0",
                    "title": "Absol 063/094 Phantasmal Flames Pokemon",
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
    assert _variant_matches("Absol 063/094 Reverse Holo", "Reverse Holofoil") is True
    assert _variant_matches("Absol 063/094 Holo", "Holofoil") is True
    assert _variant_matches("Absol 063/094 Reverse Holo", "Holofoil") is False
    assert _variant_matches("Charizard V 019/189 PSA 9", "Holofoil") is False
    assert _variant_matches(
        "Charizard V 019/189 PSA 9",
        "Holofoil",
        allow_implicit_finish=True,
    ) is True
    assert _variant_matches(
        "Charizard V 019/189 Reverse Holo PSA 9",
        "Holofoil",
        allow_implicit_finish=True,
    ) is False


def test_multi_item_detection_rejects_lots_and_multiple_card_numbers() -> None:
    assert _looks_like_multi_item_listing("Absol 063/094 Pokemon") is False
    assert _looks_like_multi_item_listing("Absol 063/094 x4 Pokemon") is True
    assert _looks_like_multi_item_listing("Absol 063/094 And Gastly 054/094") is True
    assert _looks_like_multi_item_listing("Pokemon card bundle Absol 063/094") is True


def test_identity_rules_reject_wrong_rarity_and_reprints() -> None:
    spec = json.loads(
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
        "Monkey.D.Luffy Op05-119 SEC Awakening of the New Era Foil NM",
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


def test_graded_listing_can_omit_inherent_finish_but_not_conflict() -> None:
    spec = json.loads(
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
    ) is True
    assert _matches_listing(
        "Pokemon Charizard V 019/189 Reverse Holo PSA 9",
        spec=spec,
        source_variant_id="Holofoil",
    ) is False


def test_money_parser_requires_gbp() -> None:
    assert _money_minor({"value": "12.34", "currency": "GBP"}) == 1234
    assert _money_minor({"value": "12.34", "currency": "USD"}) is None
    assert _money_minor({"value": "0", "currency": "GBP"}) is None
