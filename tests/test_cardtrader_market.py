from __future__ import annotations

from uuid import uuid4

import pytest

from app.cardtrader_market import refresh_cardtrader_sealed_market
from app.recognition_vision import RecognitionObservation


def observation(**overrides) -> RecognitionObservation:
    values = {
        "object_type": "SEALED_PRODUCT",
        "object_type_confidence": 0.99,
        "sealed_product_type": "BOOSTER_PACK",
        "sealed_product_type_confidence": 0.99,
        "product_code": "OP-17",
        "product_code_confidence": 0.98,
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "Japanese",
        "language_confidence": 0.99,
        "name_guess": "ONE PIECE CARD GAME OP-17 Booster Pack",
        "name_confidence": 0.93,
        "set_name_guess": "World's Strongest Warriors",
        "set_name_confidence": 0.96,
        "card_number": "",
        "card_number_confidence": 0.0,
        "cost": None,
        "cost_confidence": 0.0,
        "power": None,
        "power_confidence": 0.0,
        "colors": [],
        "colors_confidence": 0.0,
        "attributes": [],
        "attributes_confidence": 0.0,
        "traits": [],
        "traits_confidence": 0.0,
        "effect_text": "",
        "effect_confidence": 0.0,
        "rarity_text": "",
        "rarity_confidence": 0.0,
        "card_type_text": "",
        "card_type_confidence": 0.0,
        "art_treatment_text": "",
        "art_treatment_confidence": 0.0,
        "finish_text": "",
        "finish_confidence": 0.0,
        "visible_markers": ["OP-17"],
        "ocr_lines": ["OP-17"],
        "image_quality": "GOOD",
        "counterfeit_concerns": [],
        "notes": [],
    }
    values.update(overrides)
    return RecognitionObservation(**values)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args):
        self.calls.append((query, args))
        return "INSERT 0 1"


class FakeCardTrader:
    currency = "GBP"

    async def list_games(self):
        return [{"id": 18, "name": "One Piece Card Game"}]

    async def list_categories(self, *, game_id=None):
        assert game_id == 18
        return [
            {"id": 102, "game_id": 18, "name": "Boosters"},
            {"id": 103, "game_id": 18, "name": "Booster Boxes"},
        ]

    async def list_expansions(self):
        return [{"id": 1700, "game_id": 18, "name": "OP-17: The World's Strongest Warriors"}]

    async def list_blueprints(self, *, expansion_id):
        assert expansion_id == 1700
        return [
            {
                "id": 7003,
                "category_id": 102,
                "expansion_id": 1700,
                "name": "OP-17 Booster Pack",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/7003/op17.jpg",
            },
            {
                "id": 7004,
                "category_id": 103,
                "expansion_id": 1700,
                "name": "OP-17 Booster Box",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/7004/op17-box.jpg",
            },
        ]

    async def list_marketplace_products(self, *, blueprint_id, language=None, foil=None):
        assert blueprint_id == 7003
        assert language == "jp"
        return [
            {
                "id": 9001,
                "blueprint_id": 7003,
                "quantity": 2,
                "price": {"cents": 479, "currency": self.currency},
                "properties_hash": {"language": "jp"},
                "graded": False,
                "on_vacation": False,
                "bundle_size": 1,
                "user": {"country_code": "GB", "user_type": "professional"},
            },
            {
                "id": 9002,
                "blueprint_id": 7003,
                "quantity": 1,
                "price": {"cents": 525, "currency": self.currency},
                "properties_hash": {"language": "jp"},
                "graded": False,
                "on_vacation": False,
                "bundle_size": 1,
                "user": {"country_code": "DE", "user_type": "normal"},
            },
            {
                "id": 9003,
                "blueprint_id": 7003,
                "quantity": 1,
                "price": {"cents": 300, "currency": self.currency},
                "properties_hash": {"language": "jp"},
                "graded": False,
                "on_vacation": True,
                "bundle_size": 1,
                "user": {"country_code": "GB", "user_type": "normal"},
            },
            {
                "id": 9004,
                "blueprint_id": 7003,
                "quantity": 1,
                "price": {"cents": 850, "currency": self.currency},
                "properties_hash": {"language": "jp"},
                "graded": False,
                "on_vacation": False,
                "bundle_size": 2,
                "user": {"country_code": "GB", "user_type": "normal"},
            },
        ]


@pytest.mark.asyncio
async def test_exact_japanese_pack_ingests_only_eligible_gbp_single_pack_offers() -> None:
    connection = FakeConnection()
    result = await refresh_cardtrader_sealed_market(
        connection,
        catalogue_id=uuid4(),
        observation=observation(),
        physical_language="Japanese",
        client=FakeCardTrader(),
    )

    assert result["status"] == "INGESTED"
    assert result["inserted"] == 2
    assert result["eligible"] == 2
    assert result["blueprint_id"] == 7003
    assert len(connection.calls) == 2
    for query, args in connection.calls:
        assert "'CARDTRADER'" in query
        assert "'ACTIVE'" in query
        assert "'GBP'" in query
        assert "'SEALED'" in query
        assert args[3] in {479, 525}
        assert args[4] == "Japanese"


@pytest.mark.asyncio
async def test_non_gbp_cardtrader_account_fails_closed_without_market_observation() -> None:
    connection = FakeConnection()
    client = FakeCardTrader()
    client.currency = "EUR"

    result = await refresh_cardtrader_sealed_market(
        connection,
        catalogue_id=uuid4(),
        observation=observation(),
        physical_language="Japanese",
        client=client,
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["inserted"] == 0
    assert "GBP" in result["detail"]
    assert connection.calls == []


class AmbiguousCardTrader(FakeCardTrader):
    async def list_blueprints(self, *, expansion_id):
        rows = await super().list_blueprints(expansion_id=expansion_id)
        rows.append(
            {
                "id": 7013,
                "category_id": 102,
                "expansion_id": 1700,
                "name": "OP-17 Booster Pack Variant",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/7013/op17-variant.jpg",
            }
        )
        return rows


@pytest.mark.asyncio
async def test_ambiguous_same_score_sealed_blueprints_do_not_ingest_market_data() -> None:
    connection = FakeConnection()
    result = await refresh_cardtrader_sealed_market(
        connection,
        catalogue_id=uuid4(),
        observation=observation(),
        physical_language="Japanese",
        client=AmbiguousCardTrader(),
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["inserted"] == 0
    assert connection.calls == []
