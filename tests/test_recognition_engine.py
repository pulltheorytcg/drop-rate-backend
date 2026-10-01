from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import app.recognition_images as recognition_images
from PIL import Image

from app.recognition_engine import (
    _provider_identity_fingerprint,
    _provider_visual_shortlist,
    discover_provider_evidence,
    resolve_candidates,
    score_candidate,
    visual_work_short_circuit_reason,
)
from app.recognition_images import (
    RecognitionImageError,
    ReferenceImagePayload,
    decode_image_data_url,
    hash_similarity,
    reference_image_bytes,
    reference_image_hashes,
)
from app.punk_records_client import PunkRecordsClient, _name_alias_keys
from app.recognition_vision import RecognitionObservation


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260927184033_recognition_engine_v1.sql"
INDEX_MIGRATION = ROOT / "database" / "migrations" / "20260927184141_index_recognition_system_fks.sql"
API = ROOT / "backend" / "app" / "recognition.py"
ENGINE = ROOT / "backend" / "app" / "recognition_engine.py"
VISION = ROOT / "backend" / "app" / "recognition_vision.py"
SCANNER = ROOT / "backend" / "app" / "static" / "recognition-scanner.js"
STYLES = ROOT / "backend" / "app" / "static" / "styles.css"
MAIN = ROOT / "backend" / "app" / "main.py"


def observation(**overrides) -> RecognitionObservation:
    values = {
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "Japanese",
        "language_confidence": 0.99,
        "name_guess": "Monkey D. Luffy",
        "name_confidence": 0.98,
        "set_name_guess": "Awakening of the New Era",
        "set_name_confidence": 0.95,
        "card_number": "OP05-119",
        "card_number_confidence": 0.99,
        "cost": 10,
        "cost_confidence": 0.90,
        "power": 12000,
        "power_confidence": 0.90,
        "colors": ["Purple"],
        "colors_confidence": 0.90,
        "attributes": ["Strike"],
        "attributes_confidence": 0.90,
        "traits": ["Straw Hat Crew"],
        "traits_confidence": 0.90,
        "effect_text": "Example visible effect text.",
        "effect_confidence": 0.80,
        "rarity_text": "SEC",
        "rarity_confidence": 0.95,
        "card_type_text": "Character",
        "card_type_confidence": 0.95,
        "art_treatment_text": "Base",
        "art_treatment_confidence": 0.95,
        "finish_text": "Foil",
        "finish_confidence": 0.85,
        "visible_markers": [],
        "ocr_lines": ["OP05-119", "SEC"],
        "image_quality": "GOOD",
        "counterfeit_concerns": [],
        "notes": [],
    }
    values.update(overrides)
    return RecognitionObservation(**values)


def candidate(
    *,
    catalogue_id: UUID | None = None,
    name: str = "Monkey D. Luffy",
    card_number: str = "OP05-119",
    language: str | None = "Japanese",
    art: str = "Base",
    max_value: int = 10_000,
    visual: float | None = None,
    provider_id: str | None = None,
) -> dict:
    return {
        "catalogue_id": catalogue_id or uuid4(),
        "game": "One Piece",
        "name": name,
        "set_name": "Awakening of the New Era",
        "card_number": card_number,
        "variant": "Foil",
        "rarity": "SEC",
        "language": language,
        "system_code": "ONE_PIECE_CARD_GAME",
        "identity_status": "LEGACY_UNREVIEWED",
        "printing_key": f"legacy:{uuid4()}",
        "printing_identity_status": "LEGACY_UNREVIEWED",
        "taxonomy": [
            {"dimension_code": "RARITY", "value_code": "SEC", "display_name": "Secret Rare"},
            {"dimension_code": "CARD_TYPE", "value_code": "CHARACTER", "display_name": "Character"},
            {"dimension_code": "ART_TREATMENT", "value_code": art.upper().replace(" ", "_"), "display_name": art},
            {"dimension_code": "FINISH", "value_code": "FOIL", "display_name": "Foil"},
        ],
        "provider_mappings": [],
        "reference_image_url": None,
        "source_provider": "Punk Records" if provider_id else None,
        "provider_asset_id": provider_id,
        "media_language": language if provider_id else None,
        "inventory_languages": [language],
        "max_known_value_minor": max_value,
        "has_graded_copy": False,
        "visual_similarity": visual,
    }


def provider(provider_id: str, *, art: str, visual: float = 0.95) -> dict:
    return {
        "provider": "Punk Records",
        "provider_id": provider_id,
        "base_card_id": "OP05-119",
        "pack_id": "OP05",
        "name": "Monkey D. Luffy",
        "rarity": "SEC",
        "card_type": "Character",
        "art_treatment": art,
        "image_url": "https://www.onepiece-cardgame.com/images/example.png",
        "visual_similarity": visual,
        "source_reference": "https://github.com/Kuroro1990/OPTCG",
    }


def resolve(obs: RecognitionObservation, candidates: list[dict], **kwargs) -> dict:
    return resolve_candidates(
        obs,
        candidates,
        provider_evidence=kwargs.pop("provider_evidence", []),
        exact_threshold=kwargs.pop("exact_threshold", 0.82),
        min_margin=kwargs.pop("min_margin", 0.10),
        high_value_review_minor=kwargs.pop("high_value_review_minor", 50_000),
        inventory_context=kwargs.pop("inventory_context", None),
    )


def test_single_well_evidenced_printing_can_be_exact_candidate() -> None:
    result = resolve(observation(), [candidate()])
    assert result["decision"] == "EXACT_CANDIDATE"
    assert result["top"]["score"] >= 0.82
    assert result["risk_flags"] == []


def test_wrong_language_is_hard_rejected() -> None:
    scored = score_candidate(observation(), candidate(language="English"))
    assert scored["hard_rejected"] is True
    assert "language mismatch" in scored["rejection_reasons"]


def test_wrong_collector_number_is_hard_rejected() -> None:
    scored = score_candidate(observation(), candidate(card_number="OP05-120"))
    assert scored["hard_rejected"] is True
    assert "collector number mismatch" in scored["rejection_reasons"]


def test_round1_marker_can_recover_nami_identity_but_keeps_ocr_conflict_review() -> None:
    obs = observation(
        name_guess="ナミ (Nami)",
        set_name_guess="頂上決戦 / Paramount War (OP-02)",
        set_name_confidence=0.88,
        card_number="OP02-036",
        card_number_confidence=0.78,
        cost=3,
        cost_confidence=0.99,
        power=1000,
        power_confidence=0.99,
        colors=["Green"],
        colors_confidence=0.98,
        attributes=["Wisdom"],
        attributes_confidence=0.82,
        traits=["FILM", "麦わらの一味"],
        traits_confidence=0.72,
        effect_text="",
        effect_confidence=0.18,
        rarity_text="R",
        rarity_confidence=0.66,
        card_type_text="Character",
        card_type_confidence=0.96,
        art_treatment_text="Full-art illustration with visible ROUND1 ONE PIECE collaboration stamp",
        art_treatment_confidence=0.88,
        finish_text="Possible foil",
        finish_confidence=0.38,
        visible_markers=["ROUND1 ONE PIECE logo across artwork"],
        ocr_lines=["ROUND1", "ONE PIECE", "ナミ", "OP02-036"],
        image_quality="FAIR",
    )
    local = candidate(
        name="Nami (Round 1 Promo)",
        card_number="ST29-008",
        language=None,
        art="Base",
        max_value=3206,
    )
    local["set_name"] = "One Piece Promotion Cards"
    local["rarity"] = "C"
    local["taxonomy"] = [
        {"dimension_code": "RARITY", "value_code": "C", "display_name": "Common"},
        {"dimension_code": "CARD_TYPE", "value_code": "CHARACTER", "display_name": "Character"},
        {"dimension_code": "FINISH", "value_code": "FOIL", "display_name": "Foil"},
    ]
    local["inventory_languages"] = []

    provider_item = {
        "provider": "Punk Records",
        "provider_id": "ST29-008",
        "base_card_id": "ST29-008",
        "pack_id": "550029",
        "language": "Japanese",
        "name": "ナミ",
        "rarity": "Common",
        "card_type": "Character",
        "colors": ["Yellow"],
        "cost": 3,
        "power": 1000,
        "attributes": ["Special"],
        "types": ["エッグヘッド", "麦わらの一味"],
        "effect": "",
        "art_treatment": "Base",
        "image_url": "https://www.onepiece-cardgame.com/images/cardlist/card/ST29-008.png",
        "retrieval_score": 0.8125,
        "visual_similarity": None,
    }
    provider_item.update(_provider_identity_fingerprint(obs, provider_item))

    result = resolve(obs, [local], provider_evidence=[provider_item])

    assert result["top"]["catalogue_id"] == local["catalogue_id"]
    assert result["top"]["signals"]["promo_marker"]["match"] == 1.0
    assert result["top"]["signals"]["card_number"]["source"] == "promo_marker_recovery"
    assert result["top"]["signals"]["card_number"]["recovered"] == "ST29-008"
    assert result["top"]["signals"]["language"]["match"] == 1.0
    assert result["decision"] == "NEEDS_REVIEW"
    assert "OCR_CARD_NUMBER_CONFLICT" in result["risk_flags"]


def test_bilingual_japanese_name_aliases_keep_native_and_english_forms() -> None:
    aliases = _name_alias_keys("ナミ (Nami)")
    assert "ナミ" in aliases
    assert "nami" in aliases


def test_round1_promotion_beats_non_promotion_printing_with_same_card_number() -> None:
    obs = observation(
        name_guess="ナミ",
        card_number="ST29-008",
        card_number_confidence=0.99,
        art_treatment_text="ROUND1 ONE PIECE collaboration promotional artwork",
        art_treatment_confidence=0.99,
        visible_markers=["ROUND1 ONE PIECE", "NOT FOR SALE"],
        ocr_lines=["ナミ", "ST29-008", "ROUND1"],
        finish_text="Foil",
        finish_confidence=0.80,
    )
    normal = candidate(
        name="Nami",
        card_number="ST29-008",
        language="Japanese",
        art="Base",
        max_value=500,
    )
    promo = candidate(
        name="Nami (Round 1 Promo)",
        card_number="ST29-008",
        language="Japanese",
        art="Base",
        max_value=500,
    )
    promo["printing_attributes"] = {
        "promotion_key": "ROUND1_2026",
        "promotion_name": "ROUND1 Promotion Pack",
        "promotion_aliases": ["ROUND1", "Round One"],
        "exclusive_artwork": True,
    }
    normal["printing_attributes"] = {}

    result = resolve(obs, [normal, promo])

    assert result["top"]["catalogue_id"] == promo["catalogue_id"]
    assert result["top"]["signals"]["promotion"]["match"] == 1.0
    assert result["runner_up"]["catalogue_id"] == normal["catalogue_id"]
    assert result["runner_up"]["signals"]["promotion"]["match"] == 0.0
    assert result["decision"] == "NEEDS_REVIEW"
    assert "PROMOTION_MEDIA_UNVERIFIED" in result["risk_flags"]


def test_provider_only_candidates_rank_by_their_own_identity_not_global_ocr_confidence() -> None:
    obs = observation(
        name_guess="ナミ",
        card_number="P-0?3",
        card_number_confidence=0.20,
        language="Japanese",
        language_confidence=0.99,
    )
    weak = {
        "provider": "Punk Records",
        "provider_id": "ST01-007",
        "base_card_id": "ST01-007",
        "language": "Japanese",
        "identity_score": 0.61,
        "retrieval_score": 0.75,
        "visual_similarity": None,
    }
    strong = {
        "provider": "Punk Records",
        "provider_id": "ST29-008",
        "base_card_id": "ST29-008",
        "language": "Japanese",
        "identity_score": 0.90,
        "retrieval_score": 1.0,
        "visual_similarity": 0.56,
    }

    result = resolve(obs, [], provider_evidence=[weak, strong])

    assert result["candidates"][0]["provider_id"] == "ST29-008"
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]
    assert result["candidates"][0]["signals"]["card_number"]["match"] == 0.0


def test_same_number_base_vs_parallel_without_unique_discriminator_needs_review() -> None:
    base = candidate(art="Base")
    parallel = candidate(art="Parallel", name="Monkey D. Luffy (Parallel)")
    result = resolve(
        observation(
            art_treatment_text="",
            art_treatment_confidence=0.0,
            finish_text="Foil",
        ),
        [base, parallel],
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert "AMBIGUOUS_PRINTING" in result["risk_flags"]


def test_provider_visual_evidence_can_support_one_unique_printing_but_not_self_verify() -> None:
    base = candidate(art="Base", provider_id="OP05-119")
    parallel = candidate(art="Parallel", name="Monkey D. Luffy (Parallel)")
    evidence = [provider("OP05-119", art="Base", visual=0.99)]
    result = resolve(observation(), [base, parallel], provider_evidence=evidence)
    assert result["top"]["catalogue_id"] == base["catalogue_id"]
    assert result["top"]["signals"]["provider"]["match"] >= 0.90
    assert result["decision"] in {"EXACT_CANDIDATE", "NEEDS_REVIEW"}


def test_high_value_candidate_always_needs_human_review() -> None:
    result = resolve(observation(), [candidate(max_value=75_000)])
    assert result["decision"] == "NEEDS_REVIEW"
    assert "HIGH_VALUE_REVIEW" in result["risk_flags"]


def test_graded_inventory_always_needs_human_review() -> None:
    current = candidate()
    result = resolve(
        observation(),
        [current],
        inventory_context={
            "catalogue_id": current["catalogue_id"],
            "grading_company": "PSA",
            "grade": "10",
        },
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert "GRADED_ITEM_REVIEW" in result["risk_flags"]


def test_current_inventory_identity_conflict_never_auto_passes() -> None:
    proposed = candidate()
    result = resolve(
        observation(),
        [proposed],
        inventory_context={
            "catalogue_id": uuid4(),
            "grading_company": None,
            "grade": None,
        },
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert "CURRENT_IDENTITY_CONFLICT" in result["risk_flags"]


def test_counterfeit_concern_never_auto_passes() -> None:
    result = resolve(
        observation(counterfeit_concerns=["Typography appears inconsistent"]),
        [candidate()],
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert "POTENTIAL_COUNTERFEIT_REVIEW" in result["risk_flags"]


def test_provider_only_match_is_review_not_exact() -> None:
    external = provider("OP05-119_p1", art="Parallel")
    external.update(
        {
            "identity_score": 0.94,
            "identity_evidence_weight": 0.72,
            "non_number_identity_score": 0.95,
            "non_number_evidence_weight": 0.68,
            "retrieval_score": 0.96,
            "language": "Japanese",
        }
    )
    result = resolve(
        observation(),
        [],
        provider_evidence=[external],
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert result["top"]["source_kind"] == "PROVIDER"
    assert result["top"]["catalogue_id"] is None
    assert "UNMAPPED_PROVIDER_CANDIDATE" in result["risk_flags"]


def test_strong_unmapped_provider_printing_challenges_local_catalogue_candidate() -> None:
    local = candidate(
        name="Nico Robin",
        card_number="ST29-009",
        language="Japanese",
        art="Base",
    )
    external = provider("EB03-054_round1", art="ROUND1 Promo", visual=0.98)
    external.update(
        {
            "base_card_id": "EB03-054",
            "name": "Nico Robin",
            "language": "Japanese",
            "identity_score": 0.72,
            "identity_evidence_weight": 0.60,
            "non_number_identity_score": 0.96,
            "non_number_evidence_weight": 0.72,
            "retrieval_score": 0.98,
        }
    )

    result = resolve(
        observation(
            name_guess="Nico Robin",
            card_number="ST29-009",
            card_number_confidence=0.78,
            art_treatment_text="ROUND1 ONE PIECE promotional artwork",
            art_treatment_confidence=0.98,
            visible_markers=["ROUND1 ONE PIECE"],
            ocr_lines=["Nico Robin", "ST29-009", "ROUND1"],
        ),
        [local],
        provider_evidence=[external],
    )

    assert result["decision"] == "NEEDS_REVIEW"
    assert "UNMAPPED_PROVIDER_CHALLENGER" in result["risk_flags"]
    assert any(
        item["source_kind"] == "PROVIDER"
        and item["provider_id"] == "EB03-054_round1"
        for item in result["candidates"]
    )
    shown = [result["top"], result["runner_up"]]
    assert any(
        item is not None
        and item["source_kind"] == "PROVIDER"
        and item["provider_id"] == "EB03-054_round1"
        for item in shown
    )


def test_explicitly_mapped_provider_row_is_not_duplicated_as_external_candidate() -> None:
    local = candidate(provider_id="OP05-119")
    local["provider_mappings"] = [
        {
            "source_provider": "Punk Records",
            "provider_id": "OP05-119",
            "match_status": "VERIFIED",
        }
    ]
    external = provider("OP05-119", art="Base", visual=0.99)
    external.update(
        {
            "identity_score": 0.98,
            "identity_evidence_weight": 0.80,
            "non_number_identity_score": 0.98,
            "non_number_evidence_weight": 0.75,
            "retrieval_score": 1.0,
            "language": "Japanese",
        }
    )

    result = resolve(
        observation(),
        [local],
        provider_evidence=[external],
    )

    assert not any(
        item["source_kind"] == "PROVIDER"
        for item in result["candidates"]
    )


def test_image_decoder_hashes_valid_front_image_without_persisting_pixels() -> None:
    image = Image.new("RGB", (600, 840), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    raw = output.getvalue()
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode()

    decoded = decode_image_data_url(data_url, max_bytes=1_000_000)
    assert decoded.mime_type == "image/png"
    assert decoded.size_bytes == len(raw)
    assert decoded.width == 600
    assert decoded.height == 840
    assert len(decoded.sha256) == 64
    assert decoded.hashes
    assert hash_similarity(decoded.hashes, decoded.hashes) == 1.0


def test_image_decoder_rejects_low_resolution_and_wrong_type() -> None:
    image = Image.new("RGB", (100, 100), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    with pytest.raises(RecognitionImageError, match="resolution"):
        decode_image_data_url(data_url, max_bytes=1_000_000)
    with pytest.raises(RecognitionImageError, match="JPEG, PNG or WebP"):
        decode_image_data_url("data:image/gif;base64,R0lGODlh", max_bytes=1_000_000)


def test_recognition_migration_is_fail_closed_audited_and_immutable() -> None:
    sql = MIGRATION.read_text()
    assert "create table tcg.recognition_runs" in sql
    assert "create table tcg.recognition_candidates" in sql
    assert "create table tcg.recognition_feedback" in sql
    assert "unique (owner_id, idempotency_key)" in sql
    assert "Recognition candidate evidence is immutable" in sql
    assert "alter table tcg.recognition_runs force row level security" in sql
    assert "alter table tcg.recognition_candidates force row level security" in sql
    assert "with check (" in sql
    assert "tcg.is_platform_admin()" in sql
    assert "create trigger recognition_runs_audit" in sql
    assert "create trigger recognition_candidates_audit" in sql
    assert "create trigger recognition_feedback_audit" in sql
    assert "Recognition feedback owner mismatch" in sql
    assert "Human label must select a viable recognition candidate" in sql
    assert "update tcg.inventory_items" not in sql.casefold()
    assert "insert into tcg.identity_verification_events" not in sql.casefold()


def test_recognition_api_never_auto_applies_identity() -> None:
    source = API.read_text()
    assert '@router.post("/resolve")' in source
    assert '@router.get("/status")' in source
    assert '@router.get("/runs")' in source
    assert '@router.post("/runs/{run_id}/feedback")' in source
    assert "auto_applied" in source
    assert '"auto_applies_inventory_identity": False' in source
    assert "update tcg.inventory_items" not in source.casefold()
    assert "insert into tcg.identity_verification_events" not in source.casefold()
    assert "source_image_sha256" in source
    assert "source_image_bytes" not in source


def test_vision_adapter_is_observation_only_and_uses_structured_schema() -> None:
    source = VISION.read_text()
    assert "input_image" in source
    assert '"detail": "high"' in source
    assert '"type": "json_schema"' in source
    assert '"strict": True' in source
    assert "Do not decide whether" in source
    assert "A character/name match is not an exact-printing match." in source


def test_founder_hq_exposes_recognition_scanner_and_safety_copy() -> None:
    ui = SCANNER.read_text()
    main = MAIN.read_text()
    assert "Open live camera" in ui
    assert "Choose a card photo" in ui
    assert "Recognise exact printing" in ui
    assert "Top candidate" in ui
    assert "Runner-up" in ui
    assert "Unmapped provider challenger" in ui
    assert "Top evidence candidate · catalogue mapping required" in ui
    assert "Art treatment" in ui
    assert "Recognition Engine v1 never auto-edits inventory identity" in ui
    assert "Confirm top candidate" in ui
    assert "Runner-up is correct" in ui
    assert "Reject all candidates" in ui
    assert "/api/v1/recognition/resolve" in ui
    assert "/api/v1/recognition/runs" in ui
    assert "recognition-scanner.js" in main
    assert "recognition_router" in main


def test_engine_requires_unique_discriminator_for_same_number_printings() -> None:
    source = ENGINE.read_text()
    assert "same_number_count > 1" in source
    assert "art_unique" in source
    assert "visual_unique" in source
    assert "provider_unique" in source
    assert "AMBIGUOUS_PRINTING" in source


def test_recognition_migration_has_balanced_plpgsql_dollar_quotes() -> None:
    sql = MIGRATION.read_text()
    assert "\nas $\n" not in sql
    assert "\n$;\n" not in sql
    assert sql.count("as $$") == sql.count("$$;")


def test_human_feedback_is_append_only_training_truth_not_inventory_mutation() -> None:
    sql = MIGRATION.read_text()
    api = API.read_text()
    ui = SCANNER.read_text()

    assert "recognition_feedback_immutable" in sql
    assert "CORRECTED_TO_CANDIDATE" in sql
    assert "supersedes_feedback_id" in sql
    assert "insert into tcg.recognition_feedback" in api
    assert "update tcg.inventory_items" not in api.casefold()
    assert "Human label saved to the verified learning dataset" in ui


def test_recognition_system_foreign_keys_are_indexed() -> None:
    sql = INDEX_MIGRATION.read_text()
    assert "recognition_runs_system_idx" in sql
    assert "recognition_candidates_system_idx" in sql


def test_mobile_live_camera_scanner_uses_rear_camera_and_one_tap_recognition() -> None:
    ui = SCANNER.read_text()

    assert "Open live camera" in ui
    assert "Capture & recognise" in ui
    assert "navigator.mediaDevices.getUserMedia" in ui
    assert 'cameraFacingMode: "environment"' in ui
    assert 'facingMode: { ideal: facingMode }' in ui
    assert "recognitionCardCrop" in ui
    assert "canvas.toBlob" in ui
    assert "recognitionCanvasJpegDataUrl" in ui
    assert "recognitionPromiseTimeout" in ui
    assert "await runRecognitionScan()" in ui


def test_mobile_camera_stream_is_not_uploaded_continuously_and_is_shutdown() -> None:
    ui = SCANNER.read_text()

    assert "MediaRecorder" not in ui
    assert "RTCPeerConnection" not in ui
    assert "track.stop()" in ui
    assert 'window.addEventListener("pagehide"' in ui
    assert 'document.addEventListener("visibilitychange"' in ui
    assert "stopRecognitionCamera();" in ui


def test_mobile_camera_has_permission_fallback_switch_camera_and_optional_torch() -> None:
    ui = SCANNER.read_text()

    assert "Camera permission was blocked" in ui
    assert "You can upload a photo instead." in ui
    assert "Switch camera" in ui
    assert "getCapabilities" in ui
    assert "capabilities.torch" in ui
    assert "applyConstraints({ advanced: [{ torch: next }] })" in ui


def test_camera_permission_policy_is_first_party_only() -> None:
    main = MAIN.read_text()

    assert 'camera=(self), microphone=(), geolocation=()' in main
    assert 'camera=()' not in main
    assert 'camera=(*)' not in main


def test_mobile_camera_ui_has_card_alignment_guide_and_responsive_styles() -> None:
    ui = SCANNER.read_text()
    styles = STYLES.read_text()

    assert "recognition-card-guide" in ui
    assert "Fill the frame · keep the card flat · avoid glare" in ui
    assert ".recognition-camera-viewport" in styles
    assert ".recognition-card-guide" in styles
    assert "aspect-ratio:5/7" in styles


def op11_luffy_observation(**overrides) -> RecognitionObservation:
    values = {
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "English",
        "language_confidence": 0.99,
        "name_guess": "Monkey D. Luffy",
        "name_confidence": 0.99,
        "set_name_guess": "",
        "set_name_confidence": 0.05,
        "card_number": "",
        "card_number_confidence": 0.08,
        "cost": 8,
        "cost_confidence": 0.99,
        "power": 8000,
        "power_confidence": 0.99,
        "colors": ["Blue"],
        "colors_confidence": 0.95,
        "attributes": ["Strike"],
        "attributes_confidence": 0.95,
        "traits": ["Straw Hat Crew"],
        "traits_confidence": 0.95,
        "effect_text": (
            "[Rush] [When Attacking] You may trash 1 card from your hand: "
            "Return up to 1 Character with a cost of 4 or less to the owner's hand. "
            "Then, give up to 1 rested DON!! card to your Leader or 1 of your Characters."
        ),
        "effect_confidence": 0.92,
        "rarity_text": "",
        "rarity_confidence": 0.08,
        "card_type_text": "Character",
        "card_type_confidence": 0.99,
        "art_treatment_text": "Base",
        "art_treatment_confidence": 0.88,
        "finish_text": "Foil",
        "finish_confidence": 0.78,
        "visible_markers": [
            "8 cost",
            "8000 power",
            "Blue",
            "Strike",
            "Rush",
            "Straw Hat Crew",
        ],
        "ocr_lines": [
            "8",
            "8000",
            "STRIKE",
            "Rush",
            "Monkey D. Luffy",
            "Straw Hat Crew",
        ],
        "image_quality": "FAIR",
        "counterfeit_concerns": [],
        "notes": [],
    }
    values.update(overrides)
    return RecognitionObservation(**values)


def op11_provider(
    provider_id: str,
    *,
    art: str,
    visual: float | None,
) -> dict:
    item = {
        "provider": "Punk Records",
        "provider_id": provider_id,
        "base_card_id": "OP11-118",
        "pack_id": "569111",
        "language": "English",
        "name": "Monkey.D.Luffy",
        "rarity": "SecretRare",
        "card_type": "Character",
        "colors": ["Blue"],
        "cost": 8,
        "power": 8000,
        "attributes": ["Strike"],
        "types": ["Straw Hat Crew"],
        "effect": (
            "[Rush]<br>[When Attacking] You may trash 1 card from your hand: "
            "Return up to 1 Character with a cost of 4 or less to the owner's hand. "
            "Then, give up to 1 rested DON!! card to your Leader or 1 of your Characters."
        ),
        "art_treatment": art,
        "image_url": "https://en.onepiece-cardgame.com/images/cardlist/card/example.png",
        "visual_similarity": visual,
        "source_reference": "https://github.com/Kuroro1990/OPTCG",
    }
    item.update(_provider_identity_fingerprint(op11_luffy_observation(), item))
    return item


def test_op11_118_recovers_from_gameplay_fingerprint_when_tiny_id_is_unreadable() -> None:
    obs = op11_luffy_observation()
    local = candidate(
        name="Monkey.D.Luffy (118)",
        card_number="OP11-118",
        language=None,
        art="Base",
        max_value=175,
    )
    local["set_name"] = "A Fist of Divine Speed"

    evidence = [
        op11_provider("OP11-118", art="Base", visual=0.96),
        op11_provider("OP11-118_p1", art="Parallel", visual=0.71),
        op11_provider("OP11-118_p2", art="Parallel", visual=0.67),
    ]
    result = resolve(obs, [local], provider_evidence=evidence)

    assert result["top"]["catalogue_id"] == local["catalogue_id"]
    assert result["top"]["candidate_snapshot"]["card_number"] == "OP11-118"
    assert result["top"]["candidate_snapshot"]["set_name"] == "A Fist of Divine Speed"
    assert result["top"]["candidate_snapshot"]["language"] == "English"
    assert result["top"]["signals"]["card_number"]["source"] == "provider_fingerprint"
    assert result["top"]["signals"]["card_number"]["recovered"] == "OP11-118"
    assert result["top"]["signals"]["provider"]["identity_score"] >= 0.90
    assert result["decision"] == "EXACT_CANDIDATE"


def test_op11_118_identity_is_returned_but_printing_stays_review_when_art_is_ambiguous() -> None:
    obs = op11_luffy_observation(art_treatment_text="", art_treatment_confidence=0.0)
    local = candidate(
        name="Monkey.D.Luffy (118)",
        card_number="OP11-118",
        language=None,
        art="Base",
        max_value=175,
    )
    local["set_name"] = "A Fist of Divine Speed"

    evidence = [
        op11_provider("OP11-118", art="Base", visual=0.83),
        op11_provider("OP11-118_p1", art="Parallel", visual=0.82),
        op11_provider("OP11-118_p2", art="Parallel", visual=0.81),
    ]
    result = resolve(obs, [local], provider_evidence=evidence)

    assert result["top"]["candidate_snapshot"]["card_number"] == "OP11-118"
    assert result["decision"] == "NEEDS_REVIEW"
    assert "PROVIDER_PRINTING_AMBIGUITY" in result["risk_flags"]
    assert all("No local catalogue printing" not in reason for reason in result["reasons"])


def test_punctuation_in_collectr_style_names_does_not_block_catalogue_retrieval() -> None:
    source = ENGINE.read_text()

    assert "regexp_replace(coalesce(p.name,''), '[^A-Za-z0-9]', '', 'g')" in source
    assert "_compact(_name_core(observation.name_guess))" in source


@pytest.mark.asyncio
async def test_punk_records_english_name_lookup_filters_by_visible_stats() -> None:
    client = PunkRecordsClient(index_ttl_seconds=60)
    cards = {
        "OP11-118": {
            "name": "Monkey.D.Luffy",
            "card_id": "OP11-118",
            "pack_id": "569111",
            "colors": ["Blue"],
            "cost": 8,
            "category": "Character",
            "power": 8000,
        },
        "OP11-118_p1": {
            "name": "Monkey.D.Luffy",
            "card_id": "OP11-118_p1",
            "pack_id": "569111",
            "colors": ["Blue"],
            "cost": 8,
            "category": "Character",
            "power": 8000,
        },
        "OP05-119": {
            "name": "Monkey.D.Luffy",
            "card_id": "OP05-119",
            "pack_id": "569105",
            "colors": ["Purple"],
            "cost": 10,
            "category": "Character",
            "power": 12000,
        },
    }
    names = {"monkey.d.luffy": list(cards)}
    full = {
        key: {
            "id": key,
            **value,
            "rarity": "SecretRare",
            "attributes": ["Strike"],
            "types": ["Straw Hat Crew"],
            "effect": "[Rush]",
            "img_full_url": f"https://en.onepiece-cardgame.com/images/{key}.png",
        }
        for key, value in cards.items()
    }

    async def fake_cards_index(folder: str = "japanese") -> dict:
        assert folder == "english"
        return cards

    async def fake_name_index(folder: str) -> dict:
        assert folder == "english"
        return names

    async def fake_card(folder: str, pack_id: str, provider_id: str) -> dict:
        assert folder == "english"
        return full[provider_id]

    client._cards_index = fake_cards_index  # type: ignore[method-assign]
    client._by_name_index = fake_name_index  # type: ignore[method-assign]
    client._card = fake_card  # type: ignore[method-assign]

    found = await client.find_candidates(
        language="English",
        name="Monkey D. Luffy",
        cost=8,
        power=8000,
        card_type="Character",
        colors=["Blue"],
    )

    ids = [item["provider_id"] for item in found]
    assert ids[:2] == ["OP11-118", "OP11-118_p1"]
    assert "OP05-119" in ids
    assert found[0]["retrieval_score"] > next(
        item["retrieval_score"] for item in found if item["provider_id"] == "OP05-119"
    )
    assert all(item["language"] == "English" for item in found)




@pytest.mark.asyncio
async def test_round1_low_confidence_number_is_not_used_to_bias_provider_retrieval() -> None:
    calls: list[dict] = []

    class RecordingPunk:
        async def find_candidates(self, **kwargs):
            calls.append(kwargs)
            return []

    obs = observation(
        name_guess="ナミ (Nami)",
        card_number="OP02-036",
        card_number_confidence=0.78,
        art_treatment_text="Full-art with visible ROUND1 ONE PIECE mark",
        art_treatment_confidence=0.98,
        visible_markers=["ROUND1 ONE PIECE"],
        ocr_lines=["ナミ", "OP02-036", "ROUND1"],
    )

    await discover_provider_evidence(obs, punk=RecordingPunk())

    assert len(calls) == 1
    assert calls[0]["card_number"] is None
    assert calls[0]["name"] == "ナミ (Nami)"
    assert calls[0]["power"] == obs.power
    assert calls[0]["cost"] == obs.cost


@pytest.mark.asyncio
async def test_high_confidence_number_remains_a_provider_retrieval_hint() -> None:
    calls: list[dict] = []

    class RecordingPunk:
        async def find_candidates(self, **kwargs):
            calls.append(kwargs)
            return []

    obs = observation(
        card_number="OP05-119",
        card_number_confidence=0.99,
    )

    await discover_provider_evidence(obs, punk=RecordingPunk())

    assert len(calls) == 1
    assert calls[0]["card_number"] == "OP05-119"


@pytest.mark.asyncio
async def test_punk_records_japanese_bilingual_name_recovers_round1_nami() -> None:
    client = PunkRecordsClient(index_ttl_seconds=60)
    cards = {
        "OP02-036": {
            "name": "ナミ",
            "card_id": "OP02-036",
            "pack_id": "550102",
            "colors": ["Green"],
            "cost": 3,
            "category": "Character",
            "power": 5000,
        },
        "ST29-008": {
            "name": "ナミ",
            "card_id": "ST29-008",
            "pack_id": "550029",
            "colors": ["Yellow"],
            "cost": 3,
            "category": "Character",
            "power": 1000,
        },
        "ST29-008_p1": {
            "name": "ナミ",
            "card_id": "ST29-008_p1",
            "pack_id": "550029",
            "colors": ["Yellow"],
            "cost": 3,
            "category": "Character",
            "power": 1000,
        },
    }
    names = {"ナミ": list(cards)}
    full = {
        key: {
            "id": key,
            **value,
            "rarity": "Common" if key.startswith("ST29") else "SuperRare",
            "attributes": ["Special"],
            "types": ["エッグヘッド", "麦わらの一味"] if key.startswith("ST29") else ["FILM"],
            "effect": "",
            "img_full_url": f"https://www.onepiece-cardgame.com/images/cardlist/card/{key}.png",
        }
        for key, value in cards.items()
    }

    async def fake_cards_index(folder: str = "japanese") -> dict:
        assert folder == "japanese"
        return cards

    async def fake_name_index(folder: str) -> dict:
        assert folder == "japanese"
        return names

    async def fake_card(folder: str, pack_id: str, provider_id: str) -> dict:
        assert folder == "japanese"
        return full[provider_id]

    client._cards_index = fake_cards_index  # type: ignore[method-assign]
    client._by_name_index = fake_name_index  # type: ignore[method-assign]
    client._card = fake_card  # type: ignore[method-assign]

    found = await client.find_candidates(
        language="Japanese",
        card_number="OP02-036",
        name="ナミ (Nami)",
        cost=3,
        power=1000,
        card_type="Character",
        colors=["Green"],
        limit=20,
    )

    ids = [item["provider_id"] for item in found]
    assert "ST29-008" in ids
    assert "ST29-008_p1" in ids
    assert next(
        item["retrieval_score"] for item in found if item["provider_id"] == "ST29-008"
    ) > next(
        item["retrieval_score"] for item in found if item["provider_id"] == "OP02-036"
    )


def test_vision_schema_extracts_gameplay_fingerprint_not_only_tiny_card_id() -> None:
    source = VISION.read_text()

    for field in (
        "cost",
        "power",
        "colors",
        "attributes",
        "traits",
        "effect_text",
    ):
        assert f'"{field}"' in source
    assert "identity fingerprints when glare or" in source
    assert "extract every field independently from pixels" in source
    assert "guessed card number must" in source


def test_recognition_logic_change_bumps_idempotency_version() -> None:
    api = API.read_text()
    assert 'ENGINE_VERSION = "v1.8.0"' in api
    assert 'f"recognition:{ENGINE_VERSION}:{settings.recognition_model}:"' in api


def test_luffy_wrong_cost_does_not_eliminate_correct_identity() -> None:
    obs = op11_luffy_observation(
        cost=6,
        cost_confidence=0.98,
        card_number="",
        card_number_confidence=0.05,
    )
    correct = candidate(
        name="Monkey.D.Luffy (118)",
        card_number="OP11-118",
        language=None,
        art="Base",
        max_value=175,
    )
    correct["set_name"] = "A Fist of Divine Speed"

    wrong = candidate(
        name="Monkey.D.Luffy",
        card_number="OP05-119",
        language=None,
        art="Base",
        max_value=175,
    )
    wrong["set_name"] = "Awakening of the New Era"
    wrong["rarity"] = "SEC"

    evidence = [
        op11_provider("OP11-118", art="Base", visual=0.95),
        op11_provider("OP11-118_p1", art="Parallel", visual=0.72),
        op11_provider("OP11-118_p2", art="Parallel", visual=0.68),
        {
            **op11_provider("OP05-119", art="Base", visual=0.55),
            "base_card_id": "OP05-119",
            "cost": 10,
            "power": 12000,
            "colors": ["Purple"],
            "effect": "Different effect text.",
        },
    ]
    for item in evidence:
        item.update(_provider_identity_fingerprint(obs, item))

    result = resolve(obs, [correct, wrong], provider_evidence=evidence)

    assert result["top"]["catalogue_id"] == correct["catalogue_id"]
    assert result["top"]["score"] >= 0.94
    assert result["runner_up"]["catalogue_id"] == wrong["catalogue_id"]
    assert result["runner_up"]["score"] <= 0.60
    assert result["margin"] >= 0.30
    assert result["top"]["signals"]["language"]["match"] == 1.0
    assert result["top"]["signals"]["set"]["match"] == 1.0
    assert result["top"]["signals"]["card_type"]["match"] == 1.0


def op14_doflamingo_observation() -> RecognitionObservation:
    return RecognitionObservation(
        game="One Piece",
        game_confidence=0.99,
        language="Japanese",
        language_confidence=0.99,
        name_guess="ドンキホーテ・ドフラミンゴ",
        name_confidence=0.99,
        set_name_guess="",
        set_name_confidence=0.10,
        card_number="OP14-080",
        card_number_confidence=0.78,
        cost=10,
        cost_confidence=0.99,
        power=10000,
        power_confidence=0.99,
        colors=["Purple"],
        colors_confidence=0.97,
        attributes=["Special"],
        attributes_confidence=0.76,
        traits=["王下七武海", "ドンキホーテ海賊団"],
        traits_confidence=0.90,
        effect_text=(
            "【登場時】ドン!!-3：以下から1つを選ぶ。"
            "自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、"
            "相手のコスト8以下のキャラ1枚までをKOする。"
            "相手のコスト7以下のキャラ1枚までは、"
            "次の相手のエンドフェイズ終了時まで、レストにできない。"
        ),
        effect_confidence=0.77,
        rarity_text="",
        rarity_confidence=0.25,
        card_type_text="Character",
        card_type_confidence=0.99,
        art_treatment_text="Full-art parallel/alternate-art-style illustration",
        art_treatment_confidence=0.82,
        finish_text="Foil/holographic",
        finish_confidence=0.96,
        visible_markers=["10", "10000", "Purple", "Special"],
        ocr_lines=["OP14-080"],
        image_quality="FAIR",
        counterfeit_concerns=[],
        notes=[],
    )


def op14_provider(
    provider_id: str,
    *,
    base_id: str,
    name: str,
    cost: int,
    power: int,
    colors: list[str],
    card_type: str,
    rarity: str,
    traits: list[str],
    effect: str,
    art: str,
    visual: float | None,
) -> dict:
    item = {
        "provider": "Punk Records",
        "provider_id": provider_id,
        "base_card_id": base_id,
        "pack_id": "550114",
        "language": "Japanese",
        "name": name,
        "rarity": rarity,
        "card_type": card_type,
        "colors": colors,
        "cost": cost,
        "power": power,
        "attributes": ["Special"],
        "types": traits,
        "effect": effect,
        "art_treatment": art,
        "image_url": "https://www.onepiece-cardgame.com/images/cardlist/card/example.png",
        "visual_similarity": visual,
        "source_reference": "https://github.com/Kuroro1990/OPTCG",
    }
    item.update(_provider_identity_fingerprint(op14_doflamingo_observation(), item))
    return item


def test_op14_069_overrides_wrong_ocr_number_using_stronger_japanese_fingerprint() -> None:
    obs = op14_doflamingo_observation()
    effect = (
        "【登場時】ドン‼-3：以下から1つを選ぶ。"
        "自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、"
        "相手のコスト8以下のキャラ1枚までを、KOする。"
        "相手のコスト7以下のキャラ3枚までは、"
        "次の相手のエンドフェイズ終了時まで、レストにできない。"
    )
    correct_provider = op14_provider(
        "OP14-069",
        base_id="OP14-069",
        name="ドンキホーテ・ドフラミンゴ",
        cost=10,
        power=10000,
        colors=["Purple"],
        card_type="Character",
        rarity="SuperRare",
        traits=["王下七武海", "ドンキホーテ海賊団"],
        effect=effect,
        art="Base",
        visual=0.91,
    )
    parallel_provider = {
        **correct_provider,
        "provider_id": "OP14-069_p1",
        "art_treatment": "Parallel",
        "visual_similarity": 0.88,
    }
    wrong_provider = op14_provider(
        "OP14-080",
        base_id="OP14-080",
        name="ゲッコー・モリア",
        cost=4,
        power=5000,
        colors=["Black", "Yellow"],
        card_type="Leader",
        rarity="Leader",
        traits=["王下七武海", "スリラーバーク海賊団"],
        effect="Different leader effect.",
        art="Base",
        visual=0.42,
    )

    correct = candidate(
        name="Donquixote Doflamingo",
        card_number="OP14-069",
        language="Japanese",
        art="Base",
        max_value=1000,
    )
    correct["set_name"] = "The Azure Sea's Seven"
    correct["rarity"] = "SR"

    wrong = candidate(
        name="Gecko Moria",
        card_number="OP14-080",
        language="Japanese",
        art="Base",
        max_value=1000,
    )
    wrong["set_name"] = "The Azure Sea's Seven"
    wrong["rarity"] = "L"
    wrong["taxonomy"] = [
        {"dimension_code": "CARD_TYPE", "value_code": "LEADER", "display_name": "Leader"},
        {"dimension_code": "RARITY", "value_code": "L", "display_name": "Leader"},
        {"dimension_code": "ART_TREATMENT", "value_code": "BASE", "display_name": "Base"},
    ]

    result = resolve(
        obs,
        [correct, wrong],
        provider_evidence=[correct_provider, parallel_provider, wrong_provider],
    )

    assert result["top"]["catalogue_id"] == correct["catalogue_id"]
    assert result["top"]["candidate_snapshot"]["card_number"] == "OP14-069"
    assert result["top"]["score"] >= 0.94
    assert result["runner_up"]["catalogue_id"] == wrong["catalogue_id"]
    assert result["runner_up"]["score"] <= 0.65
    assert result["margin"] >= 0.25
    assert result["top"]["signals"]["card_number"]["source"] == "provider_override"
    assert result["top"]["signals"]["card_number"]["ocr_conflict"] is True
    assert result["top"]["signals"]["card_number"]["recovered"] == "OP14-069"
    assert result["top"]["signals"]["language"]["match"] == 1.0
    assert result["top"]["signals"]["set"]["match"] == 1.0
    assert result["top"]["signals"]["rarity"]["match"] == 1.0
    assert result["top"]["signals"]["card_type"]["match"] == 1.0
    assert result["decision"] == "NEEDS_REVIEW"
    assert "OCR_CARD_NUMBER_CONFLICT" in result["risk_flags"]


def test_catalogue_lookup_can_use_recovered_provider_card_numbers() -> None:
    source = ENGINE.read_text()
    assert "provider_numbers = sorted(" in source
    assert "non_number_identity_score" in source
    assert "= any(" in source
    assert 'provider_evidence=provider_items' in API.read_text()


def test_identity_and_printing_confidence_are_separate_in_ui() -> None:
    ui = SCANNER.read_text()
    assert "Identity confidence" in ui
    assert "Printing confidence" in ui
    assert '["Promotion", signals.promotion]' in ui
    assert "Identity margin vs runner-up" in ui
    assert "provider override (OCR read" in ui


def test_reference_image_fingerprint_cache_deduplicates_inflight_and_reuses_success(
    monkeypatch,
) -> None:
    recognition_images._clear_reference_image_hash_cache()
    calls = 0

    async def fake_fetch(url: str, *, max_bytes: int, timeout_seconds: float):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return (11, 22, 33)

    monkeypatch.setattr(
        recognition_images,
        "_reference_image_hashes_uncached",
        fake_fetch,
    )

    async def run():
        first, second = await asyncio.gather(
            reference_image_hashes("https://assets.tcgdex.net/card.png"),
            reference_image_hashes("https://assets.tcgdex.net/card.png"),
        )
        third = await reference_image_hashes("https://assets.tcgdex.net/card.png")
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first == second == third == (11, 22, 33)
    assert calls == 1


def test_reference_image_fingerprint_cache_does_not_negative_cache_transient_failure(
    monkeypatch,
) -> None:
    recognition_images._clear_reference_image_hash_cache()
    calls = 0

    async def fake_fetch(url: str, *, max_bytes: int, timeout_seconds: float):
        nonlocal calls
        calls += 1
        return None if calls == 1 else (44, 55)

    monkeypatch.setattr(
        recognition_images,
        "_reference_image_hashes_uncached",
        fake_fetch,
    )

    async def run():
        first = await reference_image_hashes("https://assets.tcgdex.net/retry.png")
        second = await reference_image_hashes("https://assets.tcgdex.net/retry.png")
        return first, second

    first, second = asyncio.run(run())
    assert first is None
    assert second == (44, 55)
    assert calls == 2


def test_reference_image_byte_cache_reuses_success(monkeypatch) -> None:
    recognition_images._clear_reference_image_hash_cache()
    calls = 0

    async def fake_fetch(url: str, *, max_bytes: int, timeout_seconds: float):
        nonlocal calls
        calls += 1
        return ReferenceImagePayload(content_type="image/png", data=b"cached-image")

    monkeypatch.setattr(
        recognition_images,
        "_fetch_reference_image_uncached",
        fake_fetch,
    )

    async def run():
        first = await reference_image_bytes("https://assets.tcgdex.net/card.png")
        second = await reference_image_bytes("https://assets.tcgdex.net/card.png")
        return first, second

    first, second = asyncio.run(run())
    assert first == second
    assert first is not None
    assert first.content_type == "image/png"
    assert calls == 1


def test_provider_visual_shortlist_excludes_low_relevance_same_character_rows() -> None:
    strong = {"provider_id": "OP09-048", "identity_score": 0.82, "non_number_identity_score": 0.99}
    medium = {"provider_id": "OP09-048_r1", "identity_score": 0.70, "non_number_identity_score": 0.80}
    weak = {"provider_id": "P-052", "identity_score": 0.57, "non_number_identity_score": 0.69}

    selected = _provider_visual_shortlist([strong, medium, weak])

    assert strong in selected
    assert medium in selected
    assert weak not in selected


def test_visual_short_circuit_only_uses_irreversible_human_review_gates() -> None:
    assert visual_work_short_circuit_reason(observation()) is None
    assert (
        visual_work_short_circuit_reason(observation(game_confidence=0.89))
        == "LOW_GAME_CONFIDENCE"
    )
    assert (
        visual_work_short_circuit_reason(
            observation(language="Unknown", language_confidence=0.20)
        )
        == "LANGUAGE_UNCERTAIN"
    )
    assert (
        visual_work_short_circuit_reason(observation(image_quality="POOR"))
        == "POOR_IMAGE_QUALITY"
    )
    assert (
        visual_work_short_circuit_reason(
            observation(counterfeit_concerns=["Suspicious print layout"])
        )
        == "POTENTIAL_COUNTERFEIT_REVIEW"
    )
    assert (
        visual_work_short_circuit_reason(
            observation(),
            {"grading_company": "PSA", "grade": "10"},
        )
        == "GRADED_ITEM_REVIEW"
    )


def test_v14_parallel_evidence_work_and_stage_timing_are_wired_without_gate_changes() -> None:
    api = API.read_text()
    engine = ENGINE.read_text()

    assert "provider_result, learning_hints, library_items, provider_visual_hints = await asyncio.gather(" in api
    assert "candidates, _ = await asyncio.gather(" in api
    assert '"provider_discovery"' in api
    assert '"learning_hints"' in api
    assert '"catalogue_lookup"' in api
    assert '"provider_visual"' in api
    assert '"catalogue_visual"' in api
    assert '"learning_visual"' in api
    assert '"resolve"' in api
    assert '"pipeline_before_persist"' in api
    assert '"visual_short_circuit_reason": visual_short_circuit' in api
    assert "visual_work_short_circuit_reason" in engine

    # Safety thresholds and explicit human-review gates remain in the resolver.
    assert "observation.game_confidence < 0.90" in engine
    assert "observation.language_confidence < 0.85" in engine
    assert "HIGH_VALUE_REVIEW" in engine
    assert "GRADED_ITEM_REVIEW" in engine
    assert "POTENTIAL_COUNTERFEIT_REVIEW" in engine


def test_scanner_candidate_image_uses_authenticated_proxy_and_shows_market_value() -> None:
    ui = SCANNER.read_text()
    api = API.read_text()
    main = MAIN.read_text()

    assert "snapshot.reference_image_url || snapshot.image_url" in ui
    assert "const image = document.createElement(\"img\");" in ui
    assert "loadRecognitionCandidateImage(image, runId, candidate.id);" in ui
    assert "/candidates/${candidateId}/image" in ui
    assert "Market value" in ui
    assert "candidate.market_value_minor" in ui
    assert '@router.get("/runs/{run_id}/candidates/{candidate_id}/image")' in api
    assert "reference_image_bytes" in api
    assert "price.market_value_minor" in api
    assert "blob:" in main
    assert "img-src *" not in main
    assert "canvas.toBlob" in ui
    assert "recognitionPromiseTimeout" in ui
    assert "AbortController" in ui
    assert "70000" in ui
    assert "candidate.provider_id" in ui
    assert "Exact printing image not verified yet" in ui
    assert "Previous results are not shown during this scan." in ui
    assert "The previous scan result has been cleared." in ui
    assert "const viableCandidates = candidates.filter((item) => !item.hard_rejected);" in ui
