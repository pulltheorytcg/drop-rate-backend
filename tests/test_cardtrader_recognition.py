from __future__ import annotations

from app.cardtrader_client import CardTraderApiError
from app.cardtrader_recognition import discover_one_piece_cardtrader_candidates
from app.recognition_engine import _provider_only_candidates, _provider_support
from app.recognition_images import _trusted_reference_url
from app.recognition_vision import RecognitionObservation


def observation(**overrides) -> RecognitionObservation:
    values = {
        "object_type": "CARD",
        "object_type_confidence": 0.99,
        "sealed_product_type": "UNKNOWN",
        "sealed_product_type_confidence": 0.0,
        "product_code": "",
        "product_code_confidence": 0.0,
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "Japanese",
        "language_confidence": 0.99,
        "name_guess": "モンキー・Ｄ・ガープ",
        "name_confidence": 0.96,
        "set_name_guess": "ブースターパック 世界最強の戦士 OP-17",
        "set_name_confidence": 0.95,
        "card_number": "OP12-056",
        "card_number_confidence": 0.92,
        "cost": 5,
        "cost_confidence": 0.9,
        "power": 6000,
        "power_confidence": 0.9,
        "colors": ["Black"],
        "colors_confidence": 0.9,
        "attributes": ["Strike"],
        "attributes_confidence": 0.9,
        "traits": ["Navy"],
        "traits_confidence": 0.9,
        "effect_text": "",
        "effect_confidence": 0.0,
        "rarity_text": "SR",
        "rarity_confidence": 0.9,
        "card_type_text": "Character",
        "card_type_confidence": 0.95,
        "art_treatment_text": "",
        "art_treatment_confidence": 0.0,
        "finish_text": "Holofoil",
        "finish_confidence": 0.9,
        "visible_markers": ["OP-17"],
        "ocr_lines": ["OP12-056"],
        "image_quality": "GOOD",
        "counterfeit_concerns": [],
        "notes": [],
    }
    values.update(overrides)
    return RecognitionObservation(**values)


class FakeCardTrader:
    async def list_games(self):
        return [{"id": 18, "name": "One Piece Card Game"}]

    async def list_categories(self, *, game_id=None):
        assert game_id == 18
        return [
            {"id": 101, "game_id": 18, "name": "Single Cards"},
            {"id": 102, "game_id": 18, "name": "Boosters"},
        ]

    async def list_expansions(self):
        return [
            {"id": 1700, "game_id": 18, "name": "OP-17"},
            {"id": 1600, "game_id": 18, "name": "OP-16"},
        ]

    async def list_blueprints(self, *, expansion_id):
        assert expansion_id == 1700
        return [
            {
                "id": 7001,
                "game_id": 18,
                "category_id": 101,
                "expansion_id": 1700,
                "name": "モンキー・Ｄ・ガープ",
                "version": "Parallel",
                "image_url": (
                    "https://cardtrader.com/uploads/blueprints/image/7001/"
                    "preview_garp-op12-056.jpg"
                ),
                "fixed_properties": {"collector_number": "OP12-056"},
            },
            {
                "id": 7002,
                "game_id": 18,
                "category_id": 101,
                "expansion_id": 1700,
                "name": "Wrong card",
                "image_url": (
                    "https://cardtrader.com/uploads/blueprints/image/7002/"
                    "preview_wrong.jpg"
                ),
                "fixed_properties": {"collector_number": "OP12-099"},
            },
            {
                "id": 7003,
                "game_id": 18,
                "category_id": 102,
                "expansion_id": 1700,
                "name": "OP-17 Booster Pack",
                "image_url": (
                    "https://cardtrader.com/uploads/blueprints/image/7003/"
                    "preview_booster.jpg"
                ),
            },
        ]


async def test_cardtrader_one_piece_retrieves_exact_number_single_without_booster() -> None:
    rows = await discover_one_piece_cardtrader_candidates(
        observation(),
        FakeCardTrader(),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "CardTrader"
    assert row["provider_id"] == "7001"
    assert row["base_card_id"] == "OP12-056"
    assert row["retrieval_only"] is True
    assert row["exact_printing_verified"] is False
    assert row["image_url"].endswith("/garp-op12-056.jpg")


async def test_cardtrader_one_piece_fails_closed_without_relevant_expansion() -> None:
    rows = await discover_one_piece_cardtrader_candidates(
        observation(
            set_name_guess="Completely unrelated release",
            card_number="P-999",
        ),
        FakeCardTrader(),
    )
    assert rows == []


def test_retrieval_only_provider_cannot_support_local_exact_acceptance() -> None:
    candidate = {
        "card_number": "OP12-056",
        "provider_mappings": [],
        "name": "モンキー・Ｄ・ガープ",
        "variant": "Parallel",
        "taxonomy": [],
    }
    retrieval_only = {
        "provider": "CardTrader",
        "provider_id": "7001",
        "base_card_id": "OP12-056",
        "retrieval_only": True,
        "library_reference": True,
        "identity_score": 1.0,
        "identity_evidence_weight": 1.0,
        "non_number_identity_score": 1.0,
        "non_number_evidence_weight": 1.0,
        "visual_similarity": 0.99,
        "art_treatment": "Parallel",
    }

    support, evidence = _provider_support(candidate, [retrieval_only])
    assert support == 0.0
    assert evidence is None


def test_retrieval_only_provider_can_still_surface_as_unmapped_challenger() -> None:
    obs = observation()
    row = {
        "provider": "CardTrader",
        "provider_id": "7001",
        "base_card_id": "OP12-056",
        "language": "Japanese",
        "retrieval_only": True,
        "library_reference": True,
        "identity_score": 0.95,
        "identity_evidence_weight": 0.7,
        "non_number_identity_score": 0.94,
        "non_number_evidence_weight": 0.6,
        "retrieval_score": 0.95,
        "visual_similarity": 0.96,
        "name": "モンキー・Ｄ・ガープ",
        "set_name": "OP-17",
        "image_url": "https://cardtrader.com/uploads/blueprints/image/7001/garp.jpg",
    }
    candidates = _provider_only_candidates(obs, [row], catalogue_candidates=[])

    assert candidates
    assert candidates[0]["provider"] == "CardTrader"
    assert candidates[0]["catalogue_id"] is None
    assert candidates[0]["signals"]["visual"]["match"] == 0.96


def test_cardtrader_images_are_trusted_only_on_cardtrader_https_hosts() -> None:
    assert _trusted_reference_url(
        "https://cardtrader.com/uploads/blueprints/image/7001/garp.jpg"
    )
    assert _trusted_reference_url(
        "https://cdn.cardtrader.com/uploads/blueprints/image/7001/garp.webp"
    )
    assert not _trusted_reference_url(
        "https://example.com/uploads/blueprints/image/7001/garp.jpg"
    )
