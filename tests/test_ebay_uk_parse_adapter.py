import json

import pytest

from app.ebay_uk_parse_adapter import (
    EbayUkParseAdapter,
    _contains_term,
    _normalise_text,
)


CATALOGUE_ID = "11111111-1111-1111-1111-111111111111"


def raw_mapping(**overrides) -> str:
    payload = {
        "query": "Charizard Base Set 4/102",
        "required_title_terms": ["Charizard", "Base Set", "4/102"],
        "forbidden_title_terms": ["proxy", "custom"],
        "language": "English",
        "include_sold": True,
        "include_active": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeRawParseClient:
    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        if endpoint == "search_sold_listings":
            return {
                "type": "sold",
                "items": [
                    {
                        "item_id": "267694408289",
                        "title": "Pokemon Charizard Base Set 4/102 Holo English",
                        "price": "£155.58",
                        "shipping": "+£3.94 delivery",
                        "condition": "Used",
                        "url": "https://www.ebay.co.uk/itm/267694408289",
                    },
                    {
                        "item_id": "267694408290",
                        "title": "Pokemon Charizard Evolutions 11/108 Holo English",
                        "price": "£85.00",
                        "shipping": "Free delivery",
                        "condition": "Used",
                        "url": "https://www.ebay.co.uk/itm/267694408290",
                    },
                ],
            }
        if endpoint == "search_listings":
            return {
                "items": [
                    {
                        "item_id": "297490087982",
                        "title": "Pokemon Charizard Base Set 4/102 Holo English",
                        "price": "£199.99",
                        "shipping": "Free next day delivery",
                        "condition": "Used",
                        "sold_date": "99+ sold",
                        "url": "https://www.ebay.co.uk/itm/297490087982",
                    },
                    {
                        "item_id": "297490087983",
                        "title": "Pokemon Charizard Base Set 4/102 Holo English",
                        "price": "£150.00 to £350.00",
                        "shipping": "+£4.99 delivery",
                        "condition": "Used",
                        "url": "https://www.ebay.co.uk/itm/297490087983",
                    },
                    {
                        "item_id": "297490087984",
                        "title": "Pokemon Charizard Base Set 4/102 Holo Proxy English",
                        "price": "£9.99",
                        "shipping": "Free delivery",
                        "condition": "New",
                        "url": "https://www.ebay.co.uk/itm/297490087984",
                    },
                ],
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakePsaParseClient:
    async def get(self, *, scraper_id: str, endpoint: str, snapshot_version: int, params: dict):
        assert endpoint == "search_sold_psa_cards"
        assert "PSA 10" in params["card_name"]
        return {
            "items": [
                {
                    "item_id": "227359346251",
                    "title": "Pokemon Charizard Base Set 4/102 Holo PSA 10",
                    "price": "£1,250.00",
                    "shipping": "+£17.03 delivery",
                    "condition": "New (other)",
                    "url": "https://www.ebay.co.uk/itm/227359346251",
                },
                {
                    "item_id": "227359346252",
                    "title": "Pokemon Charizard Base Set 4/102 Holo PSA 9",
                    "price": "£650.00",
                    "shipping": "Free delivery",
                    "condition": "New (other)",
                    "url": "https://www.ebay.co.uk/itm/227359346252",
                },
                {
                    "item_id": "227359346253",
                    "title": "Pokemon Charizard Base Set 4/102 Holo PSA 100 novelty",
                    "price": "£10.00",
                    "shipping": "Free delivery",
                    "condition": "New",
                    "url": "https://www.ebay.co.uk/itm/227359346253",
                },
            ]
        }


def test_identity_terms_ignore_punctuation_and_seller_word_order() -> None:
    title = _normalise_text("ONE PIECE OP05-119 SEC Luffy Monkey D Japanese Card")
    assert _contains_term(title, "Monkey.D.Luffy")
    assert _contains_term(title, "OP05-119")


def test_identity_terms_remain_exact_tokens_not_fuzzy_substrings() -> None:
    title = _normalise_text("Pokemon Charizard 40/102 PSA 100")
    assert not _contains_term(title, "4/102")
    assert not _contains_term(title, "10")


@pytest.mark.asyncio
async def test_normalizes_strict_uk_sold_and_active_evidence() -> None:
    adapter = EbayUkParseAdapter(client=FakeRawParseClient())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=raw_mapping(),
        source_variant_id="Holo",
    )

    assert len(observations) == 2
    sold = next(item for item in observations if item.observation_type == "SOLD")
    active = next(item for item in observations if item.observation_type == "ACTIVE")

    assert sold.source == "EBAY"
    assert sold.source_country == "GB"
    assert sold.currency == "GBP"
    assert sold.price_minor == 15558
    assert sold.price_gbp_minor == 15558
    assert sold.shipping_minor == 394
    assert sold.shipping_gbp_minor == 394
    assert sold.fx_rate_to_gbp == 1.0
    assert sold.language == "English"
    assert sold.metadata["provider_timestamp_absent"] is True

    assert active.price_minor == 19999
    assert active.shipping_minor == 0
    assert active.metadata["provider_sold_badge"] == "99+ sold"
    assert active.observation_type == "ACTIVE"
    assert not any(
        item.observation_type == "SOLD" and item.metadata.get("provider_item_id") == "297490087982"
        for item in observations
    )


@pytest.mark.asyncio
async def test_rejects_ranges_forbidden_terms_and_wrong_card_identity() -> None:
    adapter = EbayUkParseAdapter(client=FakeRawParseClient())

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=raw_mapping(),
        source_variant_id="Holo",
    )

    item_ids = {item.metadata["provider_item_id"] for item in observations}
    assert "267694408290" not in item_ids
    assert "297490087983" not in item_ids
    assert "297490087984" not in item_ids


@pytest.mark.asyncio
async def test_psa_endpoint_requires_exact_grade_term() -> None:
    adapter = EbayUkParseAdapter(client=FakePsaParseClient())
    mapping = raw_mapping(
        grading_company="PSA",
        grade="10",
        include_active=False,
    )

    observations = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=mapping,
        source_variant_id="Holo",
    )

    assert len(observations) == 1
    item = observations[0]
    assert item.observation_type == "SOLD"
    assert item.grading_company == "PSA"
    assert item.grade == "10"
    assert item.price_minor == 125000
    assert item.shipping_minor == 1703
    assert item.metadata["provider_item_id"] == "227359346251"
    assert item.metadata["endpoint"] == "search_sold_psa_cards"


@pytest.mark.asyncio
async def test_source_record_keys_are_stable_for_same_ebay_items() -> None:
    adapter = EbayUkParseAdapter(client=FakeRawParseClient())

    first = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=raw_mapping(),
        source_variant_id="Holo",
    )
    second = await adapter.fetch_observations(
        catalogue_id=CATALOGUE_ID,
        source_product_id=raw_mapping(),
        source_variant_id="Holo",
    )

    assert [item.source_record_key for item in first] == [item.source_record_key for item in second]


@pytest.mark.asyncio
async def test_rejects_unstructured_mapping() -> None:
    adapter = EbayUkParseAdapter(client=FakeRawParseClient())

    with pytest.raises(ValueError, match="JSON mapping specification"):
        await adapter.fetch_observations(
            catalogue_id=CATALOGUE_ID,
            source_product_id="Charizard Base Set 4/102",
            source_variant_id="Holo",
        )