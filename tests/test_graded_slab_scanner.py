from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OWNER_API = ROOT / "backend" / "app" / "owner_portal_api.py"
GRADING = ROOT / "backend" / "app" / "grading_certificates.py"
SCANNER = ROOT / "backend" / "app" / "static" / "owner-recognition.js"
OWNER_HTML = ROOT / "backend" / "app" / "static" / "owner.html"
MIGRATION = ROOT / "database" / "migrations" / "20261001034000_unique_graded_certificate.sql"


def test_graded_slab_scanner_is_qr_first_with_photo_fallback() -> None:
    source = SCANNER.read_text()
    html = OWNER_HTML.read_text()

    assert 'name="owner-scan-mode"' in html
    assert 'value="graded"' in html
    assert 'id="owner-slab-certificate"' in html
    assert 'id="owner-slab-lookup"' in html
    assert '"BarcodeDetector" in globalThis' in source
    assert 'formats: ["qr_code"]' in source
    assert '"/api/v1/grading-certificates/qr/resolve"' in source
    assert '"/api/v1/grading-certificates/scan"' in source
    assert '"/api/v1/grading-certificates/lookup"' in source
    assert 'ownerScanMode() === "raw" && ownerBatchIsMobile()' in source


def test_graded_scanner_keeps_raw_recognition_path_intact() -> None:
    source = SCANNER.read_text()

    assert '"/api/v1/recognition/resolve"' in source
    assert 'if (ownerScanMode() === "graded")' in source
    assert "await ownerSlabScanPhoto()" in source
    assert '"/api/v1/owner/graded-certificate-intake"' in source
    assert '"/api/v1/owner/recognition-intake"' in source


def test_graded_inventory_intake_reverifies_provider_server_side_and_stays_draft() -> None:
    source = OWNER_API.read_text()
    start = source.index('@router.post("/graded-certificate-intake"')
    end = source.index('@router.post("/recognition-intake"', start)
    block = source[start:end]

    assert "Depends(require_owner_portal_request)" in block
    assert "lookup_grading_certificate(" in block
    assert "normalize_grading_provider" in source
    assert "normalize_certificate_number" in source
    assert "provider_result.verified" in block
    assert "The selected card number conflicts" in block
    assert "The slab label grade conflicts" in block
    assert "false,'DRAFT'" in block
    assert "identity_confirmed" in block
    assert "OWNER_GRADED_CERTIFICATE_SCAN" in source
    assert "provider_evidence" in block


def test_one_grader_certificate_cannot_create_duplicate_physical_inventory() -> None:
    sql = MIGRATION.read_text()

    assert "create unique index" in sql.lower()
    assert "inventory_items_grader_certificate_unique" in sql
    assert "upper(btrim(grading_company))" in sql
    assert "regexp_replace(btrim(certificate_number)" in sql


def test_qr_parser_only_accepts_supported_official_domains_or_numeric_hint() -> None:
    source = GRADING.read_text()

    for host in (
        '"psacard.com"',
        '"www.psacard.com"',
        '"acegrading.com"',
        '"cgccards.com"',
        '"beckett.com"',
        '"marketplace.beckett.com"',
    ):
        assert host in source

    assert "QR code does not point to a supported official grading domain" in source
    assert "Numeric QR payload requires a grading-company hint" in source
    assert "requires_human_confirmation" in source
