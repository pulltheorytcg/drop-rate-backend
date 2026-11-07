"""Prevent misleading retail labels and conflicting founder-hub asset cache versions.

The production readback workflow must enforce the actual Market Value UI.
Never silently weaken the exact-byte deployment check or substitute retail
recommendations/guide estimates for current Market Value.
"""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1] / "backend" / "app"
ASSETS=(
    "reference-value-display.js","owner-inventory.js","owner-portal.js",
    "market-value-column.js","founder-accounts.js","dashboard-shell.js",
    "owner-portal.css","hub-session.js","app.js","owner-imports.js",
)


def test_shared_market_value_hubs_use_one_version_per_asset():
    source=(ROOT/"static"/"owner.html").read_text(encoding="utf8")
    source+=(ROOT/"main.py").read_text(encoding="utf8")
    source+=(ROOT/"static"/"index.html").read_text(encoding="utf8")
    for name in ASSETS:
        versions=set(re.findall(
            r"/assets/"+re.escape(name)+r"\?v=([A-Za-z0-9._-]+)",source))
        assert len(versions)==1,("Conflicting/missing cache version",name,versions)


def test_owner_storefront_valuation_does_not_call_retail_market_value():
    owner=(ROOT/"static"/"owner.html").read_text(encoding="utf8")
    assert "<span>Market value</span>" in owner
    assert "<span>Recommended retail</span>" not in owner
    assert "<span>Guide estimate</span>" not in owner
