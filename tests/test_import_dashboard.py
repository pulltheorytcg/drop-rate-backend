from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"


def test_import_dashboard_asset_exists_and_has_safe_preview_flow() -> None:
    js = (STATIC / "inventory-imports.js").read_text()
    assert "Import inventory" in js
    assert "/api/v1/imports/preview" in js
    assert "/commit" in js
    assert "Action Required" in js
    assert "file.text()" in js
    assert "8_000_000" in js


def test_import_dashboard_supports_manual_review_resolution() -> None:
    js = (STATIC / "inventory-imports.js").read_text()
    assert "/api/v1/catalogue/search" in js
    assert "/resolve" in js
    assert "/skip" in js
    assert "Resolve match" in js
    assert "Skip row" in js
    assert "Use this match" in js
    assert "stored.candidates" in js
    assert "activeImportPreview.version" in js


def test_import_migration_preserves_raw_rows_and_file_fingerprint() -> None:
    sql = (ROOT / "database" / "migrations" / "202609230006_import_framework.sql").read_text()
    assert "source_sha256" in sql
    assert "raw_record jsonb not null" in sql
    assert "normalized_record jsonb not null" in sql
    assert "unique (owner_id, source_sha256)" in sql
    assert "PREVIEW" in sql and "COMMITTED" in sql


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_inventory_import_javascript_has_valid_syntax() -> None:
    subprocess.run(["node", "--check", str(STATIC / "inventory-imports.js")], check=True)
