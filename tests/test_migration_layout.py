from pathlib import Path
import re


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
