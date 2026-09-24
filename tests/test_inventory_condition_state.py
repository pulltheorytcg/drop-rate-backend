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


def test_inventory_table_keeps_condition_grading_and_seal_in_separate_columns() -> None:
    index = (STATIC / "index.html").read_text()
    app = (STATIC / "app.js").read_text()
    assert "<th>Condition</th><th>Grading</th><th>Seal</th>" in index
    assert 'textCell("Condition"' in app
    assert 'textCell("Grading"' in app
    assert 'textCell("Seal"' in app
    assert '"Sealed product"' in app


def test_inventory_editor_has_explicit_raw_and_graded_modes() -> None:
    js = (STATIC / "inventory-state.js").read_text()
    assert '"RAW", "Raw card"' in js
    assert '"GRADED", "Graded card"' in js
    assert "Graded cards require both grading company and grade." in js
    assert "payload.condition = null" in js
    assert "payload.seal_status" in js


def test_manual_intake_has_explicit_card_state_selector() -> None:
    js = (STATIC / "inventory-intake.js").read_text()
    assert 'id="intake-card-state"' in js
    assert '<option value="RAW">Raw card</option>' in js
    assert '<option value="GRADED">Graded card</option>' in js
    assert "const isGraded" in js
