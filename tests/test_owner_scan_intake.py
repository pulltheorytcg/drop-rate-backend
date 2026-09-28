from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "app" / "owner_portal_api.py"


def _scan_intake_source() -> str:
    source = SOURCE.read_text()
    start = source.index('@router.post("/recognition-intake"')
    return source[start:]


def test_owner_scan_intake_is_restricted_to_owner_portal() -> None:
    source = _scan_intake_source()

    assert "Depends(require_owner_portal_request)" in source
    assert 'owner_id = UUID(str(access["owner_id"]))' in source
    assert "payload.owner_id" not in source


def test_owner_scan_intake_requires_human_confirmed_or_searched_identity() -> None:
    source = _scan_intake_source()

    assert "tcg.recognition_runs" in source
    assert "tcg.recognition_candidates" in source
    assert "r.owner_id=$2" in source
    assert 'run["candidate_id"] is not None and run["hard_rejected"]' in source
    assert "tcg.recognition_feedback" in source
    assert '"CONFIRMED_TOP"' in source
    assert '"CORRECTED_TO_CANDIDATE"' in source
    assert '"CORRECTED_BY_SEARCH"' in source
    assert "Confirm or correct the recognition result before adding it to inventory" in source
    assert 'feedback["selected_catalogue_id"] != payload.selected_catalogue_id' in source


def test_owner_scan_intake_cannot_self_approve_identity_or_inventory() -> None:
    source = _scan_intake_source()

    assert "false,'DRAFT'" in source
    assert '"SELLER_CONFIRMED_PENDING_DROP_RATE_VERIFICATION"' in SOURCE.read_text()
    assert "'APPROVED'" not in source.split("insert into tcg.inventory_items(", 1)[1].split("returning *", 1)[0]
    assert "identity_confirmed,status" in source


def test_owner_scan_intake_has_no_founder_only_intake_fields() -> None:
    source = _scan_intake_source()

    for forbidden in (
        "acquisition_cost_minor",
        "acquisition_date",
        "storage_location_id",
        "purchase_lot_id",
        "imported_price_override_minor",
        "notes,",
        "store_price_minor,identity_confirmed",
    ):
        assert forbidden not in source


def test_owner_scan_intake_is_idempotent_and_payload_bound() -> None:
    source = _scan_intake_source()

    assert 'Header(alias="Idempotency-Key"' in source
    assert "payload_hash = _owner_scan_payload_hash(payload)" in source
    assert "i.intake_request_key=$2" in source
    assert 'source_record.get("payload_hash") != payload_hash' in source
    assert "on conflict (intake_request_key) do nothing" in source


def test_owner_scan_intake_runs_same_deterministic_pricing_engine() -> None:
    source = SOURCE.read_text()

    assert "from .pricing import _recalculate_one" in source
    assert "valuation = await _recalculate_one(connection, owner_id, inventory_id)" in source
    assert '"recommended_retail_minor"' in source
    assert '"store_value_minor"' in source


def test_owner_inventory_exposes_recommended_retail_without_internal_cost() -> None:
    source = SOURCE.read_text()
    route_start = source.index('@router.get("/inventory")')
    route = source[route_start:]
    start = route.index("rows = await connection.fetch(")
    end = route.index("return jsonable_encoder(", start)
    query = route[start:end]

    assert "i.recommended_retail_minor" in query
    assert "acquisition_cost_minor" not in query
    assert "storage_location_id" not in query
