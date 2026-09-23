from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
PANEL = ROOT / "backend" / "app" / "static" / "market-smoke-panel.js"


def test_smoke_panel_is_loaded_by_dashboard() -> None:
    main = MAIN.read_text()
    assert '/assets/market-smoke-panel.js' in main


def test_smoke_panel_covers_mixed_real_inventory_cases() -> None:
    panel = PANEL.read_text()
    assert "pokemon-raw-normal" in panel
    assert "pokemon-raw-reverse" in panel
    assert "pokemon-graded" in panel
    assert "one-piece-raw" in panel
    assert "one-piece-graded" in panel
    assert "Charizard V 019/189" in panel
    assert "OP05-119" in panel
    assert "ST10-006" in panel


def test_collection_smoke_cases_fail_closed_without_seal_status() -> None:
    panel = PANEL.read_text()
    assert "one-piece-collection-ace" in panel
    assert "one-piece-collection-premium" in panel
    assert "Missing seal_status in inventory" in panel
    assert "Provider query deliberately skipped" in panel
