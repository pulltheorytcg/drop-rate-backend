from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.owner_portal_api import _owner_scan_inventory_payload
from app.recognition_sealed import resolve_sealed_candidates
from app.recognition_vision import OBSERVATION_SCHEMA, RecognitionObservation, VISION_INSTRUCTIONS


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
SEALED = ROOT / "backend" / "app" / "recognition_sealed.py"
OWNER_API = ROOT / "backend" / "app" / "owner_portal_api.py"
OWNER_JS = ROOT / "backend" / "app" / "static" / "owner-recognition.js"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001162000_one_piece_op17_sealed_reference.sql"
)
ENGLISH_DISPLAY_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001185000_op17_english_display_identity.sql"
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


def op17_provider_row(**overrides) -> dict:
    values = {
        "provider": "CardTrader",
        "provider_id": "7003",
        "name": "OP-17 Booster Pack",
        "set_name": "OP-17",
        "product_code": "OP-17",
        "sealed_product_type": "BOOSTER_PACK",
        "language": None,
        "image_url": "https://cardtrader.com/uploads/blueprints/image/7003/op17.jpg",
        "retrieval_score": 0.99,
        "retrieval_only": True,
        "exact_printing_verified": False,
        "visual_similarity": 0.97,
        "visual_similarity_source": "remote_provider_image",
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




def test_provider_only_sealed_candidate_is_review_only_never_exact() -> None:
    result = resolve_sealed_candidates(
        observation(),
        [],
        provider_rows=[op17_provider_row()],
    )

    assert result["decision"] == "NEEDS_REVIEW"
    assert result["top"]["source_kind"] == "PROVIDER"
    assert result["top"]["catalogue_id"] is None
    assert result["top"]["provider"] == "CardTrader"
    assert "UNMAPPED_SEALED_PROVIDER_CANDIDATE" in result["risk_flags"]
    assert result["top"]["signals"]["identity_verified"] is False


def test_provider_duplicate_cannot_demote_verified_local_pack() -> None:
    row = op17_row()
    result = resolve_sealed_candidates(
        observation(),
        [row],
        provider_rows=[op17_provider_row()],
    )

    assert result["decision"] == "EXACT_CANDIDATE"
    assert result["top"]["catalogue_id"] == row["catalogue_id"]
    assert [candidate["source_kind"] for candidate in result["candidates"]] == ["CATALOGUE"]


def test_provider_booster_box_is_rejected_for_pack_scan() -> None:
    result = resolve_sealed_candidates(
        observation(),
        [],
        provider_rows=[
            op17_provider_row(
                provider_id="7004",
                name="OP-17 Booster Box",
                sealed_product_type="BOOSTER_BOX",
            )
        ],
    )

    assert result["decision"] == "NO_MATCH"
    assert result["top"] is None
    assert result["candidates"][0]["source_kind"] == "PROVIDER"
    assert result["candidates"][0]["hard_rejected"] is True
    assert "sealed product type mismatch" in result["candidates"][0]["rejection_reasons"]


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
    assert "discover_one_piece_cardtrader_sealed_candidates(" in source
    assert "attach_provider_visual_evidence(" in source
    assert "provider_rows=sealed_provider_rows" in source
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
    assert "\n    null,\n    '',\n    '',\n    'Japanese'\n" in sql


def test_batch_inventory_intake_preserves_sealed_physical_state() -> None:
    api = OWNER_API.read_text()
    js = OWNER_JS.read_text()

    assert "seal_status: str | None" in api
    assert "seal_status=payload.seal_status" in api
    assert "condition,seal_status,grading_company" in api
    assert "function ownerBatchIsSealed(item)" in js
    assert 'seal_status: sealed ? "SEALED" : null' in js
    assert "condition: sealed ? null : condition" in js


def test_batch_review_shows_provider_only_sealed_suggestion_without_allowing_intake() -> None:
    js = OWNER_JS.read_text()

    assert "function ownerBatchDisplayCandidate(item)" in js
    assert "item?.selected || item?.suggested || null" in js
    assert 'candidate.catalogue_id || candidate.source_kind === "PROVIDER"' in js
    assert 'item.suggested?.source_kind === "PROVIDER"' in js
    assert 'fix.textContent = "Needs Drop Rate review"' in js
    assert "fix.disabled = true" in js
    assert "ownerScanLoadCandidateImage(image, item.runId, selected.id)" in js


def test_sealed_cardtrader_failure_is_non_fatal_and_audited() -> None:
    api = API.read_text()
    sealed = SEALED.read_text()

    assert "except CardTraderApiError as exc:" in api
    assert '"provider": "CardTrader"' in api
    assert "sealed_provider_errors" in api
    assert "provider_errors=sealed_provider_errors" in api
    assert '"provider_errors": [dict(item) for item in (provider_errors or [])]' in sealed


def test_op17_english_display_name_preserves_japanese_physical_language() -> None:
    sql = ENGLISH_DISPLAY_MIGRATION.read_text()

    assert "Booster Pack: World''s Strongest Warriors [OP-17]" in sql
    assert "World''s Strongest Warriors [OP-17]" in sql
    assert "'display_name_en'" in sql
    assert "'set_name_en'" in sql
    assert "sealed:v1:one_piece_card_game:op17:booster_pack:jp" in sql

    seed = MIGRATION.read_text()
    assert "'Japanese'" in seed
    assert "'official_name_ja','ブースターパック 世界最強の戦士【OP-17】'" in seed


def test_verified_exact_sealed_intake_sets_identity_confirmed_without_affecting_graded_flow() -> None:
    api = OWNER_API.read_text()
    recognition_start = api.index('@router.post("/recognition-intake"')
    recognition_block = api[recognition_start:]
    graded_start = api.index('@router.post("/graded-certificate-intake"')
    graded_block = api[graded_start:recognition_start]

    assert "verified_exact_sealed_identity = False" in recognition_block
    assert 'run["decision"] == "EXACT_CANDIDATE"' in recognition_block
    assert 'feedback["outcome"] == "CONFIRMED_TOP"' in recognition_block
    assert "pr.collectible_type='SEALED'" in recognition_block
    assert "pr.identity_status='VERIFIED'" in recognition_block
    assert "sd.identity_status='VERIFIED'" in recognition_block
    assert "$11,'DRAFT',$12,$13::jsonb,'FOR_SALE'" in recognition_block
    assert "verified_exact_sealed_identity," in recognition_block
    assert "verified_exact_sealed_identity" not in graded_block


def test_scan_inventory_payload_reports_actual_identity_verification_state() -> None:
    catalogue = {
        "id": "catalogue",
        "product_type": "SEALED",
        "game": "One Piece",
        "name": "Booster Pack: World's Strongest Warriors [OP-17]",
        "set_name": "World's Strongest Warriors [OP-17]",
        "card_number": None,
        "variant": "",
        "rarity": "",
        "language": "Japanese",
    }
    base_inventory = {
        "id": "inventory",
        "inventory_code": "INV-TEST",
        "catalogue_id": "catalogue",
        "status": "DRAFT",
        "condition": None,
        "seal_status": "SEALED",
        "grading_company": None,
        "grade": None,
        "certificate_number": None,
        "language": "Japanese",
        "market_value_minor": None,
        "recommended_retail_minor": None,
        "store_price_minor": None,
        "pricing_updated_at": None,
        "created_at": None,
        "updated_at": None,
    }

    verified = _owner_scan_inventory_payload(
        {**base_inventory, "identity_confirmed": True},
        catalogue,
        replayed=False,
    )
    pending = _owner_scan_inventory_payload(
        {**base_inventory, "identity_confirmed": False},
        catalogue,
        replayed=False,
    )

    assert verified["identity_status"] == "VERIFIED_CANONICAL_IDENTITY"
    assert verified["inventory"]["identity_confirmed"] is True
    assert pending["identity_status"] == "SELLER_CONFIRMED_PENDING_DROP_RATE_VERIFICATION"


def test_batch_copy_treats_cards_and_sealed_products_as_items() -> None:
    js = OWNER_JS.read_text()

    assert "Recognised cards and sealed products will appear here automatically." in js
    assert "Point at a card or sealed product" in js
    assert "item.identityStatus = data.identity_status || null" in js
    assert 'item.identityStatus !== "VERIFIED_CANONICAL_IDENTITY"' in js
    assert "added with verified identity" in js
