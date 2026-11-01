from pathlib import Path
import re

from scripts.stage_supabase_migrations import stage


ROOT = Path(__file__).parents[1]
LEGACY_MIGRATIONS = ROOT / "migrations"
CANONICAL_MIGRATIONS = ROOT / "database" / "migrations"


def test_new_migrations_live_in_canonical_directory() -> None:
    legacy = {path.name for path in LEGACY_MIGRATIONS.glob("*.sql")}
    legacy_numbered = {
        int(match.group(1))
        for name in legacy
        if (match := re.match(r"^(\d+)_", name))
    }
    assert legacy_numbered <= {3, 4, 5, 6, 7}
    assert any(
        path.name.endswith("_normalize_explicit_card_languages.sql")
        for path in CANONICAL_MIGRATIONS.glob("*.sql")
    )


def test_expanded_collectibles_release_history_is_staged_without_replaying_old_sql(tmp_path):
    """Release checkpoint: the old production versions are stage placeholders
    or renamed sources, while the new catalogue migration stays independent.

    This protects against silently applying historical SQL alongside the
    additive catalogue expansion. A live dry-run is still a separate gate.
    """
    result = stage(tmp_path)
    assert result["schema_verified_baselines"] == 3
    assert result["remote_only_placeholders"] == 5
    assert result["remapped"] == 90
    assert (tmp_path / "20261101205040_collectible_catalogue_expansion.sql").is_file()
    assert (tmp_path / "20261101203926_platform_comic_photo_review.sql").is_file()
    assert (tmp_path / "20261009074311_current_ebay_reference_values.sql").is_file()
    assert (tmp_path / "20261025112656_pokewallet_dragon_ball_job.sql").is_file()
    # Supabase had two recorded payout heartbeat versions; only the earlier
    # duplicate gets a no-op history placeholder, not executable old SQL.
    assert "Intentionally no SQL" in (
        tmp_path / "20260929003954_payout_scheduler_heartbeat.sql").read_text()
    assert "create table" in (
        tmp_path / "20261101205040_collectible_catalogue_expansion.sql").read_text()
    assert not any(p.stem.startswith("20261101205")
                   for p in tmp_path.glob("*.sql")
                   if p.name != "20261101205040_collectible_catalogue_expansion.sql")
