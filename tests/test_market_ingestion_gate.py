from pathlib import Path

import pytest

from app.settings import _boolean


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
SETTINGS = ROOT / "backend" / "app" / "settings.py"


def test_market_ingestion_gate_defaults_to_disabled(monkeypatch) -> None:
    monkeypatch.delenv("TCG_MARKET_INGESTION_ENABLED", raising=False)
    assert _boolean("TCG_MARKET_INGESTION_ENABLED", False) is False


def test_market_ingestion_gate_accepts_explicit_true(monkeypatch) -> None:
    monkeypatch.setenv("TCG_MARKET_INGESTION_ENABLED", "true")
    assert _boolean("TCG_MARKET_INGESTION_ENABLED", False) is True


def test_market_ingestion_gate_rejects_ambiguous_values(monkeypatch) -> None:
    monkeypatch.setenv("TCG_MARKET_INGESTION_ENABLED", "maybe")
    with pytest.raises(RuntimeError, match="must be a boolean"):
        _boolean("TCG_MARKET_INGESTION_ENABLED", False)


def test_real_ingestion_is_blocked_but_diagnostics_are_not() -> None:
    main = MAIN.read_text()
    settings = SETTINGS.read_text()
    assert 'TCG_MARKET_INGESTION_ENABLED' in settings
    assert 'request.url.path.startswith("/api/v1/market/ingestion/")' in main
    assert 'Production market ingestion is disabled until provider access is explicitly approved' in main
    assert '/api/v1/market/provider-probe' not in main.split('request.url.path.startswith("/api/v1/market/ingestion/")', 1)[1].split('else:', 1)[0]
    assert '/api/v1/market/smoke-test/' not in main.split('request.url.path.startswith("/api/v1/market/ingestion/")', 1)[1].split('else:', 1)[0]
