from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.recognition_sealed import resolve_sealed_candidates
from app.recognition_vision import OBSERVATION_SCHEMA, RecognitionObservation, VISION_INSTRUCTIONS


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
SEALED = ROOT / "backend" / "app" / "recognition_sealed.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001162000_one_piece_op17_sealed_reference.sql"
)


def observation(**overrides) -> RecognitionObservation:
    values = {
        "object_type": "SEALED_PRODUCT",
        "object_type_confidence": 0.99,
        "sealed_product_type": "BOOSTER_PACK",
        "sealed_product_type_confidence": 0.98,
        "product_code": "OP-17",
        "product_code_confidence": 0.99,
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "Japanese",
        "language_confidence": 0.99,
        "name_guess": "",
        "name_confidence": 0.0,
        "set_name_guess": "世界最強の戦士 OP-17",
        "set_name_confidence": 0.94,
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
        "ocr_lines": ["OP-17", "ONE PIECE CARD GAME"],
        "image_quality": "GOOD",
        "counterfeit_concerns": [],
        "notes": [],
    }
    values.update(overrides)
    return RecognitionObservation(**values)


def op17_row(**overrides) -> dict:
    values = {
        "catalogue_id": uuid4(),
        "product_type": "SEALED",
        "game": "One Piece",
        "name": "Booster Pack 世界最強の戦士 [OP-17]",
        "set_name": "世界最強の戦士 [OP-17]",
        "language": "Japanese",
        "system_code": "ONE_PIECE_CARD_GAME",
        "identity_status": "VERIFIED",
        "set_code": "OP-17",
        "release_region": "JP",
        "release_date": None,
        "profile_attributes": {"language": "Japanese"},
        "manufacturer_sku": "OP-17",
        "sealed_identity_status": "VERIFIED",
        "contents": {"cards_per_pack": 6, "packs_per_box": 24},
        "sealed_attributes": {"language": "Japanese", "region": "JP"},
        "sealed_product_type": "BOOSTER_PACK",
        "reference_image_url": None,
    }
    values.update(overrides)
    return values


def test_op17_japanese_single_pack_resolves_as_exact_sealed_product() -> None:
    row = op17_row()
    result = resolve_sealed_candidates(observation(), [row])

    assert result["decision"] == "EXACT_CANDIDATE"
    assert result["top"]["catalogue_id"] == row["catalogue_id"]
    assert result["top"]["candidate_snapshot"]["collectible_type"] == "SEALED"
    assert result["top"]["candidate_snapshot"]["sealed_product_type"] == "BOOSTER_PACK"
    assert result["top"]["signals"]["product_code"]["match"] == 1.0
    assert result["risk_flags"] == []


def test_pack_scan_cannot_exact_match_a_booster_box() -> None:
    row = op17_row(sealed_product_type="BOOSTER_BOX")
    result = resolve_sealed_candidates(observation(), [row])

    assert result["decision"] == "NO_MATCH"
    assert result["top"] is None
    assert result["candidates"][0]["hard_rejected"] is True
    assert "sealed product type mismatch" in result["candidates"][0]["rejection_reasons"]


def test_sealed_exact_match_requires_verified_identity() -> None:
    row = op17_row(identity_status="NEEDS_REVIEW")
    result = resolve_sealed_candidates(observation(), [row])

    assert result["decision"] == "NEEDS_REVIEW"
    assert "SEALED_IDENTITY_UNVERIFIED" in result["risk_flags"]


def test_vision_contract_classifies_object_before_identity() -> None:
    properties = OBSERVATION_SCHEMA["properties"]
    required = OBSERVATION_SCHEMA["required"]

    for field in (
        "object_type",
        "object_type_confidence",
        "sealed_product_type",
        "sealed_product_type_confidence",
        "product_code",
        "product_code_confidence",
    ):
        assert field in properties
        assert field in required

    assert "SEALED_PRODUCT" in properties["object_type"]["enum"]
    assert "BOOSTER_PACK" in properties["sealed_product_type"]["enum"]
    assert "must never be interpreted as an\nindividual card" in VISION_INSTRUCTIONS
    assert "Use NONE when no collectible is actually present" in VISION_INSTRUCTIONS


def test_api_routes_empty_and_sealed_objects_before_card_provider_discovery() -> None:
    source = API.read_text()

    none_index = source.index('if observation.object_type == "NONE"')
    sealed_index = source.index('if observation.object_type == "SEALED_PRODUCT"')
    provider_index = source.index("# v1.4 latency path: provider discovery")

    assert none_index < sealed_index < provider_index
    assert "NO_COLLECTIBLE_PRESENT" in source
    assert "load_sealed_candidates(connection, observation)" in source
    assert "resolve_sealed_candidates(observation, sealed_rows)" in source
    assert "persist_sealed_resolution(" in source


def test_sealed_loader_uses_only_canonical_sealed_identity_and_approved_media() -> None:
    source = SEALED.read_text()

    assert "pr.collectible_type='SEALED'" in source
    assert "p.product_type in ('SEALED','COLLECTION')" in source
    assert "a.dimension_code='SEALED_TYPE'" in source
    assert "m.scope='CANONICAL_PRODUCT'" in source
    assert "m.approval_status='APPROVED'" in source
    assert "m.rights_status='VERIFIED'" in source
    assert "m.rights_tier='STOREFRONT_ALLOWED'" in source
    assert "m.source_status='ACTIVE'" in source


def test_op17_seed_uses_bandai_evidence_without_importing_box_price_as_pack_value() -> None:
    sql = MIGRATION.read_text()

    assert "sealed:v1:one_piece_card_game:op17:booster_pack:jp" in sql
    assert "'OP-17'" in sql
    assert "'BOOSTER_PACK'" in sql
    assert "'cards_per_pack',6" in sql
    assert "'packs_per_box',24" in sql
    assert "https://cp.onepiece-cardgame.com/flame-flame-fruit/goods" in sql
    assert "not imported as a single-pack market value" in sql
    assert "market_value_minor" not in sql
