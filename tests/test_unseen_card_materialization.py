from pathlib import Path

from app.recognition import (
    _candidate_materialization_reason,
    _provider_catalogue_identity_key,
    _provider_variant,
)


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
SCANNER = ROOT / "backend" / "app" / "static" / "owner-recognition.js"


def _eligible_candidate() -> dict:
    return {
        "catalogue_id": None,
        "source_kind": "PROVIDER",
        "hard_rejected": False,
        "provider": "Punk Records",
        "provider_id": "OP05-069",
        "provider_language": "Japanese",
        "score": 0.93262,
        "signals": {
            "card_number": {
                "match": 1.0,
                "candidate": "OP05-069",
                "ocr_conflict": False,
            },
            "provider": {"match": 0.93589},
            "language": {"match": 1.0},
        },
    }


def test_live_op05_style_unseen_candidate_is_materialization_eligible() -> None:
    assert _candidate_materialization_reason(
        _eligible_candidate(),
        exact_threshold=0.82,
    ) is None


def test_unseen_candidate_materialization_fails_closed_on_weak_or_conflicting_evidence() -> None:
    weak = _eligible_candidate()
    weak["score"] = 0.70
    assert _candidate_materialization_reason(weak, exact_threshold=0.82) == (
        "SCORE_BELOW_EXACT_THRESHOLD"
    )

    conflict = _eligible_candidate()
    conflict["signals"]["card_number"]["ocr_conflict"] = True
    assert _candidate_materialization_reason(conflict, exact_threshold=0.82) == (
        "OCR_CARD_NUMBER_CONFLICT"
    )

    wrong_language = _eligible_candidate()
    wrong_language["signals"]["language"]["match"] = 0.0
    assert _candidate_materialization_reason(wrong_language, exact_threshold=0.82) == (
        "LANGUAGE_NOT_EXACT"
    )

    not_provider = _eligible_candidate()
    not_provider["source_kind"] = "CATALOGUE"
    assert _candidate_materialization_reason(not_provider, exact_threshold=0.82) == (
        "PROVIDER_CANDIDATE_REQUIRED"
    )


def test_provider_identity_key_is_stable_and_printing_specific() -> None:
    base = _provider_catalogue_identity_key(
        system_code="ONE_PIECE_CARD_GAME",
        provider="Punk Records",
        provider_id="OP05-069",
        provider_language="Japanese",
    )
    same = _provider_catalogue_identity_key(
        system_code="ONE_PIECE_CARD_GAME",
        provider="punk records",
        provider_id="op05-069",
        provider_language="japanese",
    )
    parallel = _provider_catalogue_identity_key(
        system_code="ONE_PIECE_CARD_GAME",
        provider="Punk Records",
        provider_id="OP05-069_p1",
        provider_language="Japanese",
    )

    assert base == same
    assert base != parallel


def test_provider_variant_preserves_printing_evidence() -> None:
    assert _provider_variant("OP05-069", {"art_treatment": "Base"}) == "Base"
    assert _provider_variant("OP05-069_p1", {}) == "Parallel"
    assert _provider_variant("OP05-069_r1", {}) == "Reprint"


def test_materialization_endpoint_requires_persisted_reference_and_human_verified_mapping() -> None:
    source = API.read_text()
    start = source.index('@router.post("/runs/{run_id}/candidates/{candidate_id}/materialize")')
    end = source.index('@router.post("/resolve")', start)
    block = source[start:end]

    assert "r.owner_id=$3" in block
    assert "tcg.reference_cards" in block
    assert "tcg.reference_sets" in block
    assert "Provider candidate is not backed by the persisted reference library" in block
    assert "'NEEDS_REVIEW'" in block
    assert "'VERIFIED','HUMAN'" in block
    assert "verified_by_user_id" in block
    assert "update tcg.recognition_candidates" in block
    assert "top_catalogue_id" in block
    assert "requires_canonical_review" in block


def test_owner_scanner_displays_unmapped_provider_candidates_and_routes_confirmation() -> None:
    source = SCANNER.read_text()

    assert 'candidate.catalogue_id || candidate.source_kind === "PROVIDER"' in source
    assert "ownerScanCanMaterializeCandidate(candidate)" in source
    assert "This is my card · add to Drop Rate" in source
    assert "/materialize" in source
    assert "await ownerScanConfirmCandidate(data.run || run, updated)" in source
