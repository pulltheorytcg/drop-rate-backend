from __future__ import annotations

import base64
import io
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.recognition_engine import resolve_candidates, score_candidate
from app.recognition_images import (
    RecognitionImageError,
    decode_image_data_url,
    hash_similarity,
)
from app.recognition_vision import RecognitionObservation


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260927184033_recognition_engine_v1.sql"
INDEX_MIGRATION = ROOT / "database" / "migrations" / "20260927184141_index_recognition_system_fks.sql"
API = ROOT / "backend" / "app" / "recognition.py"
ENGINE = ROOT / "backend" / "app" / "recognition_engine.py"
VISION = ROOT / "backend" / "app" / "recognition_vision.py"
SCANNER = ROOT / "backend" / "app" / "static" / "recognition-scanner.js"
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
    language: str = "Japanese",
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
    result = resolve(
        observation(),
        [],
        provider_evidence=[provider("OP05-119_p1", art="Parallel")],
    )
    assert result["decision"] == "NEEDS_REVIEW"
    assert result["top"] is None


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
    assert "Take or upload a card photo" in ui
    assert "Recognise exact printing" in ui
    assert "Top candidate" in ui
    assert "Runner-up" in ui
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
    assert "Human label saved to the recognition audit dataset" in ui


def test_recognition_system_foreign_keys_are_indexed() -> None:
    sql = INDEX_MIGRATION.read_text()
    assert "recognition_runs_system_idx" in sql
    assert "recognition_candidates_system_idx" in sql
