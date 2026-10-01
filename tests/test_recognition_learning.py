from __future__ import annotations

import asyncio
from pathlib import Path

from app.recognition_engine import score_candidate
from app.recognition_learning import (
    dataset_split,
    decode_fingerprints,
    encode_fingerprints,
    resolve_learning_system_code,
)

from test_recognition_engine import candidate, observation


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260927205101_recognition_verified_learning.sql"
)
API = ROOT / "backend" / "app" / "recognition.py"
ENGINE = ROOT / "backend" / "app" / "recognition_engine.py"
LEARNING = ROOT / "backend" / "app" / "recognition_learning.py"
OWNER_ACCESS_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260928195408_owner_recognition_access.sql"
)
SCANNER = ROOT / "backend" / "app" / "static" / "recognition-scanner.js"


def test_learning_fingerprint_round_trip_is_pixel_free() -> None:
    values = (0, 1, (1 << 255) + 123, (1 << 256) - 1)
    encoded = encode_fingerprints(values)

    assert encoded == [f"{value:064x}" for value in values]
    assert decode_fingerprints(encoded) == values
    assert all(len(value) == 64 for value in encoded)


def test_learning_split_is_deterministic_and_keeps_holdout_isolated() -> None:
    train_hash = "00000000" + ("0" * 56)
    validation_hash = "00000050" + ("0" * 56)  # 80 % 100
    holdout_hash = "0000005a" + ("0" * 56)  # 90 % 100

    assert dataset_split(train_hash) == "TRAIN"
    assert dataset_split(train_hash) == "TRAIN"
    assert dataset_split(validation_hash) == "VALIDATION"
    assert dataset_split(holdout_hash) == "HOLDOUT"


class _LearningSystemConnection:
    def __init__(self, selected_system: str | None) -> None:
        self.selected_system = selected_system
        self.calls: list[tuple[str, object]] = []

    async def fetchval(self, query: str, selected_catalogue_id: object) -> str | None:
        self.calls.append((query, selected_catalogue_id))
        return self.selected_system


def test_search_correction_recovers_system_from_canonical_card() -> None:
    connection = _LearningSystemConnection("ONE_PIECE_CARD_GAME")
    resolved = asyncio.run(
        resolve_learning_system_code(
            connection,
            {
                "outcome": "CORRECTED_BY_SEARCH",
                "system_code": None,
                "selected_catalogue_id": "card-1",
            },
        )
    )

    assert resolved == "ONE_PIECE_CARD_GAME"
    assert len(connection.calls) == 1
    assert "p.product_type='CARD'" in connection.calls[0][0]


def test_search_correction_canonical_system_overrides_wrong_run_system() -> None:
    connection = _LearningSystemConnection("POKEMON")
    resolved = asyncio.run(
        resolve_learning_system_code(
            connection,
            {
                "outcome": "CORRECTED_BY_SEARCH",
                "system_code": "DRAGON_BALL_SUPER",
                "selected_catalogue_id": "card-2",
            },
        )
    )

    assert resolved == "POKEMON"


def test_non_search_feedback_never_guesses_system_from_catalogue() -> None:
    connection = _LearningSystemConnection("POKEMON")
    resolved = asyncio.run(
        resolve_learning_system_code(
            connection,
            {
                "outcome": "CONFIRMED_TOP",
                "system_code": "ONE_PIECE_CARD_GAME",
                "selected_catalogue_id": "card-3",
            },
        )
    )

    assert resolved == "ONE_PIECE_CARD_GAME"
    assert connection.calls == []


def test_search_correction_without_canonical_system_fails_closed() -> None:
    connection = _LearningSystemConnection(None)
    resolved = asyncio.run(
        resolve_learning_system_code(
            connection,
            {
                "outcome": "CORRECTED_BY_SEARCH",
                "system_code": None,
                "selected_catalogue_id": "card-4",
            },
        )
    )

    assert resolved is None


def test_verified_scan_signal_is_bounded_and_visible() -> None:
    item = candidate()
    item["learning_visual_similarity"] = 0.97
    item["learning_example_count"] = 3

    scored = score_candidate(observation(), item)

    assert scored["signals"]["learning"]["available"] is True
    assert scored["signals"]["learning"]["eligible_for_identity"] is True
    assert scored["signals"]["learning"]["example_count"] == 3
    assert scored["signals"]["learning"]["source"] == "human_verified_scans"
    assert scored["hard_rejected"] is False


def test_verified_scan_cannot_override_hard_collector_number_conflict() -> None:
    item = candidate(card_number="OP05-120")
    item["learning_visual_similarity"] = 1.0
    item["learning_example_count"] = 8

    scored = score_candidate(observation(), item)

    assert scored["signals"]["learning"]["match"] == 1.0
    assert scored["hard_rejected"] is True
    assert "collector number mismatch" in scored["rejection_reasons"]


def test_repeated_verified_scans_can_support_printing_visual_evidence() -> None:
    item = candidate()
    item["learning_visual_similarity"] = 0.96
    item["learning_example_count"] = 2

    scored = score_candidate(observation(), item)

    assert scored["signals"]["visual"]["available"] is True
    assert scored["signals"]["visual"]["source"] == "human_verified_scans"
    assert scored["signals"]["visual"]["match"] == 0.96
    assert scored["printing_score"] >= 0.95


def test_one_verified_scan_does_not_self_verify_exact_printing_visual() -> None:
    item = candidate()
    item["learning_visual_similarity"] = 0.99
    item["learning_example_count"] = 1

    scored = score_candidate(observation(), item)

    assert scored["signals"]["learning"]["eligible_for_identity"] is True
    assert scored["signals"]["visual"]["available"] is False


def test_verified_learning_migration_is_append_only_audited_and_private() -> None:
    sql = MIGRATION.read_text()

    assert "create table tcg.recognition_learning_examples" in sql
    assert "create table tcg.recognition_hard_negatives" in sql
    assert "create table tcg.recognition_model_versions" in sql
    assert "dataset_split in ('TRAIN','VALIDATION','HOLDOUT')" in sql
    assert "recognition_learning_examples_immutable" in sql
    assert "recognition_hard_negatives_immutable" in sql
    assert "recognition_learning_examples_audit" in sql
    assert "recognition_hard_negatives_audit" in sql
    assert "force row level security" in sql
    assert "from public,anon,authenticated" in sql
    assert "update tcg.inventory_items" not in sql.casefold()
    assert "source_image_bytes" not in sql.casefold()


def test_api_materializes_learning_only_after_explicit_feedback() -> None:
    source = API.read_text()

    assert 'ENGINE_VERSION = "v1.6.1"' in source
    assert "materialize_learning_example(" in source
    assert "feedback_id=feedback[\"id\"]" in source
    assert "discover_learning_candidate_hints(" in source
    assert "learning_catalogue_ids=" in source
    assert "attach_learning_visual_evidence(" in source
    assert "encode_fingerprints(image.hashes)" in source
    assert '"verified_learning_enabled": True' in source
    assert '"learning_labels": "HUMAN_VERIFIED_ONLY"' in source
    assert '"learning_raw_pixels_stored": False' in source
    assert '@router.get("/learning/status")' in source
    assert "update tcg.inventory_items" not in source.casefold()


def test_online_learning_uses_train_split_only_and_active_labels() -> None:
    source = LEARNING.read_text()
    access_sql = OWNER_ACCESS_MIGRATION.read_text()

    assert "discover_learning_candidate_hints" in source
    assert "min_similarity: float = 0.94" in source
    assert "tcg.recognition_learning_hint_rows($1,$2)" in source
    assert "tcg.recognition_learning_visual_rows($1::uuid[],$2)" in source
    assert "e.dataset_split='TRAIN'" in access_sql
    assert "newer.supersedes_example_id=e.id" in access_sql
    assert "CONFIRMED_TOP" in access_sql
    assert "CORRECTED_TO_CANDIDATE" in access_sql
    assert "REJECTED_ALL" in source
    assert "recognition_hard_negatives" in source


def test_learning_weight_stays_small_and_hard_gates_remain() -> None:
    source = ENGINE.read_text()

    assert '"learning": 0.04' in source
    assert "learning_count >= 1 and learning_similarity >= 0.90" in source
    assert "learning_count >= 2 and learning_similarity >= 0.94" in source
    assert 'hard_rejections.append("collector number mismatch")' in source
    assert 'hard_rejections.append("language mismatch")' in source


def test_scanner_explains_that_feedback_teaches_without_mutating_inventory() -> None:
    ui = SCANNER.read_text()

    assert "Verified scans" in ui
    assert "human verified" in ui
    assert "become verified learning data" in ui
    assert "Inventory was not changed" in ui
