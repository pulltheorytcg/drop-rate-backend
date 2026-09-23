from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import InventoryPatch


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"
MIGRATION = ROOT / "database" / "migrations" / "202609230003_inventory_condition_and_seal_status.sql"


def test_inventory_patch_accepts_seal_status() -> None:
    patch = InventoryPatch(version=1, seal_status="SEALED")
    assert patch.seal_status == "SEALED"


def test_inventory_patch_rejects_invalid_seal_status() -> None:
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, seal_status="OPEN")


def test_dashboard_uses_tcgplayer_condition_scale() -> None:
    js = (STATIC / "inventory-state.js").read_text()
    for condition in (
        "Near Mint",
        "Lightly Played",
        "Moderately Played",
        "Heavily Played",
        "Damaged",
    ):
        assert condition in js
    assert "Mint" not in js.replace("Near Mint", "")
    assert "Gem Mint" not in js


def test_dashboard_supports_sealed_and_unsealed_merchandise() -> None:
    js = (STATIC / "inventory-state.js").read_text()
    assert '"SEALED"' in js
    assert '"UNSEALED"' in js


def test_database_guard_restricts_raw_card_conditions() -> None:
    sql = MIGRATION.read_text()
    assert "Invalid raw card condition" in sql
    assert "'Near Mint'" in sql
    assert "'Lightly Played'" in sql
    assert "'Moderately Played'" in sql
    assert "'Heavily Played'" in sql
    assert "'Damaged'" in sql
