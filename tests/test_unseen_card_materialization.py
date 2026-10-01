from pathlib import Path

from app.recognition import _candidate_materialization_reason


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
SCANNER = ROOT / "backend" / "app" / "static" / "owner-recognition.js"
MIGRATION = ROOT / "database" / "migrations" / "20261001143000_fix_recognition_materialization_immutability.sql"


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


def test_materialization_endpoint_routes_privileged_writes_through_db_function() -> None:
    source = API.read_text()
    start = source.index('@router.post("/runs/{run_id}/candidates/{candidate_id}/materialize")')
    end = source.index('@router.post("/resolve")', start)
    block = source[start:end]

    assert "r.owner_id=$3" in block
    assert "tcg.materialize_recognition_provider_candidate($1,$2,$3)" in block
    assert "insert into tcg.catalogue_products" not in block
    assert "insert into tcg.catalogue_product_profiles" not in block
    assert "insert into tcg.provider_catalogue_mappings" not in block
    assert "update tcg.recognition_candidates" not in block


def test_db_materialization_function_is_narrowly_scoped_and_revalidates_identity() -> None:
    sql = MIGRATION.read_text()

    assert "security definer" in sql.lower()
    assert "set search_path=pg_catalog" in sql
    assert "v_user_id := tcg.current_user_id()" in sql
    assert "tcg.current_access_role()" in sql
    assert "tcg.owner_memberships" in sql
    assert "tcg.reference_cards" in sql
    assert "tcg.reference_sets" in sql
    assert "Provider candidate evidence is not exact enough" in sql
    assert "'NEEDS_REVIEW'" in sql
    assert "'VERIFIED'" in sql
    assert "'HUMAN'" in sql
    assert "verified_by_user_id" in sql
    assert "update tcg.recognition_candidates" not in sql
    assert "set top_catalogue_id" not in sql
    assert "requires_canonical_review" in sql
    assert "revoke all on function tcg.materialize_recognition_provider_candidate" in sql
    assert "from public,anon,authenticated,service_role" in sql
    assert "grant execute on function tcg.materialize_recognition_provider_candidate" in sql
    assert "to tcg_api" in sql
    assert "on conflict on constraint catalogue_product_profiles_pkey do nothing" in sql


def test_owner_scanner_displays_unmapped_provider_candidates_and_routes_confirmation() -> None:
    source = SCANNER.read_text()

    assert 'candidate.catalogue_id || candidate.source_kind === "PROVIDER"' in source
    assert "ownerScanCanMaterializeCandidate(candidate)" in source
    assert "This is my card · add to Drop Rate" in source
    assert "/materialize" in source
    assert "await ownerScanConfirmCandidate(data.run || run, updated)" in source


def test_run_payload_resolves_verified_provider_mapping_without_rewriting_candidate() -> None:
    source = API.read_text()

    assert "coalesce(rc.catalogue_id,provider_map.catalogue_id) as catalogue_id" in source
    assert "from tcg.provider_catalogue_mappings m" in source
    assert "m.match_status='VERIFIED'" in source
    assert "coalesce(rc.catalogue_id,provider_map.catalogue_id)" in source


def test_feedback_accepts_verified_mapping_for_immutable_provider_candidate() -> None:
    source = API.read_text()
    start = source.index('if payload.outcome == "CORRECTED_TO_CANDIDATE":')
    end = source.index('if payload.outcome == "CORRECTED_BY_SEARCH":', start)
    block = source[start:end]

    assert "c.catalogue_id is null" in block
    assert "c.source_kind='PROVIDER'" in block
    assert "tcg.provider_catalogue_mappings" in block
    assert "m.match_status='VERIFIED'" in block
