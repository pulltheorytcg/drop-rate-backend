from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKBENCH = ROOT / "backend" / "app" / "static" / "market-mapping-workbench.js"
SHELL = ROOT / "backend" / "app" / "static" / "dashboard-shell.js"
MAIN = ROOT / "backend" / "app" / "main.py"
INGESTION = ROOT / "backend" / "app" / "market_ingestion.py"


def test_market_mapping_workbench_is_loaded_in_dashboard() -> None:
    main = MAIN.read_text()
    assert 'market-mapping-workbench.js' in main


def test_market_mapping_workbench_uses_review_then_explicit_decision() -> None:
    source = WORKBENCH.read_text()
    assert "Create REVIEW mapping" in source
    assert "/api/v1/market/mappings" in source
    assert "/verify" in source
    assert "/reject" in source
    assert "discovery_signals" in source


def test_market_mapping_discovery_never_calls_ingestion() -> None:
    source = WORKBENCH.read_text()
    assert "/api/v1/market/discovery/" in source
    assert "/api/v1/market/ingestion/" not in source
    assert "eBay sold discovery remains excluded" in source


def test_provider_status_exposes_ingestion_gate_and_dashboard_labels_it() -> None:
    ingestion = INGESTION.read_text()
    shell = SHELL.read_text()
    assert '"ingestion_enabled": get_settings().market_ingestion_enabled' in ingestion
    assert "DIAGNOSTIC ONLY" in shell
    assert "marketData.ingestion_enabled" in shell
