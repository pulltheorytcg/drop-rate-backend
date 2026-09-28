from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260928224759_sealed_product_media.sql"
)


def test_sealed_media_migration_adds_canonical_product_scope() -> None:
    sql = MIGRATION.read_text()

    assert "'CANONICAL_PRODUCT'" in sql
    assert "scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')" in sql
    assert "catalogue_id is not null" in sql
    assert "inventory_id is null" in sql


def test_sealed_media_migration_adds_physical_packaging_context() -> None:
    sql = MIGRATION.read_text()

    assert "'SEALED_PRODUCT'" in sql
    assert "media_assets_capture_context_check" in sql
    assert "FIRST_PARTY_CAPTURE" not in sql or "media_assets_first_party_scope_check" not in sql


def test_sealed_canonical_storefront_media_keeps_rights_gate() -> None:
    sql = MIGRATION.read_text()

    assert "rights_tier='STOREFRONT_ALLOWED'" in sql
    assert "approval_status='APPROVED'" in sql
    assert "nullif(btrim(media_language),'') is not null" in sql
    assert "rights_basis" in sql
    assert "permission_evidence_url" in sql
