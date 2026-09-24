from pathlib import Path


ROOT = Path(__file__).parents[1]
LEGACY_MIGRATIONS = ROOT / "migrations"
CANONICAL_MIGRATIONS = ROOT / "database" / "migrations"


def test_new_migrations_live_in_canonical_directory() -> None:
    legacy = {path.name for path in LEGACY_MIGRATIONS.glob("*.sql")}
    assert not any(
        name.startswith(("008_", "009_", "010_", "011_", "012_", "013_", "014_", "015_", "016_", "017_", "018_", "019_", "020_"))
        for name in legacy
    )
    assert any(
        path.name.endswith("_normalize_explicit_card_languages.sql")
        for path in CANONICAL_MIGRATIONS.glob("*.sql")
    )
