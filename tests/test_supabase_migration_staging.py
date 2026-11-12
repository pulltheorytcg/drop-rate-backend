from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


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


def test_later_production_history_versions_do_not_replay_as_new_migrations(
    tmp_path: Path,
) -> None:
    # Observed from production's existing migration history on 2026-11-03.
    # Two history names differ from the canonical source names: current eBay
    # values includes its old timestamp, and Dragon Ball ends in "_receipt".
    expected = {
        "payout_scheduler_heartbeat": "20260929003954",
        "shopify_order_reconciliation": "20260929010042",
        "shopify_raw_pool_published_audit": "20260929193013",
        "automation_event_superseded_state": "20260930035920",
        "automation_outbox_health": "20260930040529",
        "repair_automation_supersede_audit": "20260930040455",
        "automation_dead_letter_recovery": "20260930041649",
        "fix_automation_replay_history": "20260930042821",
        "automation_runs_n8n_contract": "20260930043033",
        "n8n_runtime_heartbeat": "20260930044501",
        "shopify_price_reconciliation": "20261009152041",
        "action_required_automation_category": "20260930163143",
        "public_owner_self_registration": "20260930204126",
        "owner_profile_settings": "20260930230108",
        "owner_username_login": "20261001000317",
        "fix_recognition_provider_materialization": "20261001135146",
        "fix_recognition_materialization_immutability": "20261001143426",
        "reference_cards_global_number_key_index": "20261001150024",
        "one_piece_op17_sealed_reference": "20261001160226",
        "provider_reference_visual_index": "20261001162213",
        "op17_english_display_identity": "20261001181220",
        "add_cardtrader_market_source": "20261001182814",
        "unified_founder_app_access": "20261002031304",
        "shared_ebay_order_allocation": "20261002031335",
        "reference_market_prices": "20261008183306",
        "current_ebay_reference_values": "20261009074311",
        "catalogue_daily_maintenance": "20261009151002",
        "catalogue_market_evidence": "20261009184315",
        "independent_catalogue_valuations": "20261009185711",
        "activate_catalogue_reference_values": "20261009191726",
        "cardmarket_valuation_fallback": "20261009195635",
        "cardmarket_multigame_guard": "20261010011236",
        "database_wide_reference_guides": "20261010122202",
        "seller_held_sealed_publication": "20261010145452",
        "inventory_op17_reference_artwork": "20261010141736",
        "shopify_publication_actor": "20261010154057",
        "shopify_variant_pool_aliases": "20261010194525",
        "shared_canonical_product_images": "20261011212102",
        "reference_history_fx_refresh_guard": "20261014155218",
        "reference_history_archive_registry": "20261014165937",
        "pokewallet_price_guides": "20261024215110",
        "pokewallet_dragon_ball_job": "20261025112656",
        "pokewallet_pokemon_job": "20261025132241",
        "r2_verified_media_delivery": "20261025172435",
        "founder_import_preview_rebuild": "20261027192257",
        "automation_control_runtime_repair": "20261027173335",
        "one_piece_official_base_recovery_job": "20261029124806",
        "cardtrader_expansion_job_allowlist": "20261029195050",
        "drop_rate_daily_model_job": "20261029231744",
        "r2_relevant_change_invalidation": "20261030090527",
        "r2_pokemon_official_reference_images": "20261031232331",
        "tcgdex_reviewed_low_artwork": "20261101150559",
    }
    manifest = json.loads(MANIFEST.read_text())
    module.stage(tmp_path)
    canonical = ROOT / "database" / "migrations"
    for name, applied_version in expected.items():
        assert manifest["historical_version_overrides"][name] == applied_version
        sources = list(canonical.glob(f"*_{name}.sql"))
        assert len(sources) == 1
        source = sources[0]
        staged = tmp_path / f"{applied_version}_{name}.sql"
        assert staged.read_bytes() == source.read_bytes()
        assert source.name != staged.name
        assert not (tmp_path / source.name).exists()


def test_later_remote_only_history_rows_remain_non_executable(tmp_path: Path) -> None:
    module.stage(tmp_path)
    for filename in (
        "20260929004242_payout_scheduler_heartbeat.sql",
        "20261101205040_collectible_catalogue_expansion.sql",
    ):
        source = (tmp_path / filename).read_text()
        assert "Intentionally no SQL" in source
        assert all(not line.strip() or line.startswith("--") for line in source.splitlines())

    # The earlier heartbeat is the canonical SQL; the identical second history
    # entry must be present too, without a second executable copy.
    earlier = tmp_path / "20260929003954_payout_scheduler_heartbeat.sql"
    assert "create or replace function tcg.check_payout_scheduler_heartbeat" in earlier.read_text()


def test_seller_hub_release_migrations_keep_canonical_versions_and_sql(
    tmp_path: Path,
) -> None:
    module.stage(tmp_path)
    for filename in (
        "20261103143718_catalogue_saved_references.sql",
        "20261103145218_seller_sports_figures_intake.sql",
        "20261103150140_catalogue_review_visibility_r2.sql",
    ):
        canonical = ROOT / "database" / "migrations" / filename
        staged = tmp_path / filename
        assert staged.read_bytes() == canonical.read_bytes()
        assert "Intentionally no SQL" not in staged.read_text()


def _pooler_setup_code() -> str:
    step = WORKFLOW.read_text().split(
        "- name: Prepare masked IPv4 session-pooler connection\n", 1
    )[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(
        step.split("python - <<'PY'\n", 1)[1].rsplit("\n          PY", 1)[0]
    )


def test_production_workflow_routes_all_database_commands_through_session_pooler() -> None:
    workflow = WORKFLOW.read_text()
    commands = re.findall(
        r'^\s+run: (supabase (?:migration list|db push)[^\n]*)$',
        workflow,
        flags=re.MULTILINE,
    )
    assert len(commands) == 4
    assert all('--db-url "${SUPABASE_POOLER_URL}"' in command for command in commands)
    assert sum("--dry-run" in command for command in commands) == 1
    assert "--include-all" not in workflow
    assert "tests/test_supabase_migration_staging.py" in workflow


def test_pooler_url_preserves_reserved_password_characters_and_masks_them(
    tmp_path: Path,
) -> None:
    # Synthetic credential only. Percent characters also require escaping in
    # GitHub's add-mask command, independently of URL percent-encoding.
    password = "synthetic:@/?#[] $%25&=example"
    env_file = tmp_path / "github-env"
    result = subprocess.run(
        [sys.executable, "-c", _pooler_setup_code()],
        env={
            "SUPABASE_PROJECT_ID": "ozrxenrdladkooixutmm",
            "SUPABASE_DB_PASSWORD": password,
            "GITHUB_ENV": str(env_file),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    exported = env_file.read_text()
    assert exported.count("\n") == 1
    assert exported.startswith("SUPABASE_POOLER_URL=")
    db_url = exported.removeprefix("SUPABASE_POOLER_URL=").rstrip("\n")
    parsed = urlsplit(db_url)
    assert parsed.username == "postgres.ozrxenrdladkooixutmm"
    assert unquote(parsed.password or "") == password
    assert parsed.hostname == "aws-0-eu-west-2.pooler.supabase.com"
    assert parsed.port == 5432
    assert parsed.path == "/postgres"
    assert parsed.query == "sslmode=require"
    mask_lines = result.stdout.splitlines()
    assert len(mask_lines) == 2
    assert all(line.startswith("::add-mask::") for line in mask_lines)
    # Decode the workflow command protocol in the same order as GitHub Actions.
    masked_values = {
        line.removeprefix("::add-mask::")
        .replace("%0D", "\r")
        .replace("%0A", "\n")
        .replace("%25", "%")
        for line in mask_lines
    }
    assert masked_values == {quote(password, safe=""), db_url}
    assert result.stderr == ""


def test_pooler_setup_rejects_line_breaks_before_exporting_credentials(
    tmp_path: Path,
) -> None:
    for password in ("synthetic\npassword", "synthetic\rpassword"):
        env_file = tmp_path / "github-env"
        result = subprocess.run(
            [sys.executable, "-c", _pooler_setup_code()],
            env={
                "SUPABASE_PROJECT_ID": "ozrxenrdladkooixutmm",
                "SUPABASE_DB_PASSWORD": password,
                "GITHUB_ENV": str(env_file),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Database password must not contain a newline" in result.stderr
        assert result.stdout == ""
        assert not env_file.exists()


def test_database_only_migration_workflow_uses_explicit_authenticated_target() -> None:
    workflow = WORKFLOW.read_text()
    assert "supabase link --project-ref" not in workflow
    assert "SUPABASE_ACCESS_TOKEN:" not in workflow
    assert 'test -n "${SUPABASE_DB_PASSWORD}"' in workflow
    assert 'supabase migration list --db-url "${SUPABASE_POOLER_URL}"' in workflow
    assert 'supabase db push --dry-run --db-url "${SUPABASE_POOLER_URL}"' in workflow
    assert 'supabase db push --db-url "${SUPABASE_POOLER_URL}"' in workflow
    assert "environment: production" in workflow


def test_verified_r2_registry_version_is_staged_without_replaying_existing_schema(tmp_path: Path) -> None:
    module.stage(tmp_path)
    assert not (tmp_path / "20261103222018_r2_first_catalogue_registry.sql").exists()
    assert (tmp_path / "20261103224740_r2_first_catalogue_registry.sql").read_bytes() == (ROOT / "database/migrations/20261103222018_r2_first_catalogue_registry.sql").read_bytes()
