"""The Railway pre-deploy process must not burn eBay sold-data credits."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "backend/scripts/social_market_evidence_probe.py"
SPEC = importlib.util.spec_from_file_location("social_market_evidence_probe", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_predeploy_probe_is_opt_in_and_spends_no_provider_credits(monkeypatch):
    monkeypatch.setenv("TCG_TRAWL_API_KEY", "synthetic-key-not-real")
    monkeypatch.delenv("DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN", raising=False)
    called = []
    class UnsafeClient:
        def __init__(self, *args, **kwargs):
            called.append("client")
            raise AssertionError("Paid provider must not be contacted on deployment")
    monkeypatch.setattr(MODULE, "TrawlEbaySoldClient", UnsafeClient)
    result = asyncio.run(MODULE.run())
    assert result == {
        "probe_version": "social-market-evidence-v1",
        "status": "SKIPPED",
        "reason": "PAID_PROVIDER_PROBE_NOT_OPTED_IN",
        "evidence_only": True,
        "persisted": False,
        "requested_targets": [],
        "results": [],
    }
    assert not called


def test_probe_opt_in_remains_explicit_and_missing_credentials_fail_closed(monkeypatch):
    monkeypatch.setenv("DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN", "1")
    monkeypatch.delenv("TCG_TRAWL_API_KEY", raising=False)
    result = asyncio.run(MODULE.run())
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "TRAWL_RUNTIME_CREDENTIAL_MISSING"
    assert result["results"] == []


def test_no_paid_calls_in_default_railway_predeploy_settings():
    source = SCRIPT.read_text()
    assert 'os.environ.get("DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN", "").strip() != "1"' in source
    assert source.index("DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN") < source.index("TrawlEbaySoldClient(api_key=key)")
    assert 'if __name__ == "__main__":' in source
