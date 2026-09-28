from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_supabase_migrations.py"
MANIFEST = ROOT / "database" / "migration_history_baseline.json"
WORKFLOW = ROOT / ".github" / "workflows" / "supabase-migrations.yml"

spec = importlib.util.spec_from_file_location("stage_supabase_migrations", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_production_staging_aligns_historical_supabase_versions(tmp_path: Path) -> None:
    result = module.stage(tmp_path)

    names = {path.name for path in tmp_path.glob("*.sql")}
    assert "20260923000948_inventory_workflow.sql" in names
    assert "202609230001_inventory_workflow.sql" not in names
    assert "20260926204548_scheduled_payout_worker.sql" in names
    assert "20260926210000_scheduled_payout_worker.sql" not in names
    assert result["remapped"] >= 30


def test_remote_only_history_versions_are_represented_as_noop_placeholders(
    tmp_path: Path,
) -> None:
    module.stage(tmp_path)
    placeholder = tmp_path / "20260921114400_foundation_and_inventory.sql"
    source = placeholder.read_text()
    assert "production migration-history baseline" in source
    assert "Intentionally no SQL" in source
    assert "create table" not in source.lower()


def test_schema_verified_unrecorded_migrations_are_not_replayed(tmp_path: Path) -> None:
    module.stage(tmp_path)

    for filename in (
        "20260925233000_store_price_floor.sql",
        "20260926001000_identity_import_exact_method.sql",
        "20260926002000_media_live_side_uniqueness.sql",
    ):
        source = (tmp_path / filename).read_text()
        assert "schema effect was independently verified" in source
        assert "canonical_source_sha256:" in source

    assert "add constraint inventory_items_store_price_floor_check" not in (
        tmp_path / "20260925233000_store_price_floor.sql"
    ).read_text().lower()


def test_modern_aligned_migrations_are_staged_byte_for_byte(tmp_path: Path) -> None:
    module.stage(tmp_path)
    filename = "20260928061929_fix_owner_invite_ambiguous_email_column.sql"
    assert (tmp_path / filename).read_bytes() == (
        ROOT / "database" / "migrations" / filename
    ).read_bytes()


def test_staged_versions_are_unique(tmp_path: Path) -> None:
    result = module.stage(tmp_path)
    versions = [
        re.match(r"^(\d+)_", path.name).group(1)
        for path in tmp_path.glob("*.sql")
    ]
    assert len(versions) == len(set(versions))
    assert result["staged"] == len(versions)


def test_history_manifest_has_no_duplicate_names_or_versions() -> None:
    manifest = json.loads(MANIFEST.read_text())
    remote_only = manifest["remote_only_applied"]
    unrecorded = manifest["schema_verified_unrecorded"]

    assert len({item["name"] for item in remote_only}) == len(remote_only)
    assert len({item["version"] for item in remote_only}) == len(remote_only)
    assert len({item["name"] for item in unrecorded}) == len(unrecorded)
    assert len({item["version"] for item in unrecorded}) == len(unrecorded)


def test_production_workflow_uses_history_aware_staging() -> None:
    workflow = WORKFLOW.read_text()
    assert "scripts/stage_supabase_migrations.py" in workflow
    assert "cp database/migrations/*.sql" not in workflow
    assert "supabase db push --dry-run" in workflow
