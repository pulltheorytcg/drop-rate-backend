"""Sanitized read-only timing instrumentation for expensive catalogue browsing."""
import ast
from pathlib import Path

import pytest

from app.catalogue_browser import _catalogue_latency_ms

ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "backend" / "app" / "catalogue_browser.py"


def test_each_stage_and_total_are_reported_in_milliseconds():
    stamps = (100.0, 100.005, 100.012, 100.045, 101.05, 101.2, 101.215)
    assert _catalogue_latency_ms(stamps) == (
        5, 7, 33, 1005, 150, 15, 1215
    )


def test_clock_adjustments_never_produce_negative_stage_metrics():
    metrics = _catalogue_latency_ms((2.0, 2.1, 2.1, 2.0, 2.0, 2.2, 2.4))
    assert all(item >= 0 for item in metrics)
    with pytest.raises(ValueError, match="seven"):
        _catalogue_latency_ms((0.0, 1.0))


def test_products_telemetry_is_slow_only_and_never_logs_private_search_inputs():
    source = BROWSER.read_text()
    assert "if total_ms >= 1500:" in source
    assert "CATALOGUE_PRODUCTS_TIMING" in source
    assert "live is not None, snapshot is not None, len(selected_rows)" in source
    # Inspect the actual logger argument AST, not string comments. These names
    # must never become timing parameters (PII, inventory, search or watchlists).
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "info"
        and node.args and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith("CATALOGUE_PRODUCTS_TIMING")
    ]
    assert len(calls) == 1
    names = {n.id for arg in calls[0].args[1:] for n in ast.walk(arg)
             if isinstance(n, ast.Name)}
    assert not names.intersection({
        "user", "access", "q", "keys", "key_list", "provider", "provider_id",
        "owner_id", "request", "rows", "query", "params",
    })
    assert all(f"{field}_ms=%s" in calls[0].args[0].value for field in
               ("total","pool","shared","index","sql","enrich","serialize"))
