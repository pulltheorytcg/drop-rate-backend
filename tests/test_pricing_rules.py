"""Owner pricing rules (27 Nov 2026), docs/PRICING_RULES.md."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import drop_rate_daily_model as model

ROOT = Path(__file__).parents[1] / "backend" / "app"
NOW = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


def _record(source, amount=500):
    return dict(provider="Bandai Official", system_code="DRAGON_BALL_SUPER_MASTERS", language="English",
                set_id="BT13", provider_id="BT13-001", card_number="BT13-001", rarity="Common[C]",
                detail_minor=amount, detail_at=NOW - timedelta(days=1), detail_source=source,
                catalogue_minor=None, catalogue_at=None, catalogue_source=None)


@pytest.mark.parametrize("source", ["TCGCSV_TCGPLAYER_CATALOGUE", "TCGDEX_TCGPLAYER", "tcgplayer_market"])
def test_rule3_us_prices_never_feed_the_daily_model(source):
    assert model._peer(_record(source), NOW) is None


@pytest.mark.parametrize("source", ["TCGDEX_CARDMARKET", "CARDMARKET_BULK_SINGLES"])
def test_rule3_eu_guides_remain_model_peers(source):
    assert model._peer(_record(source), NOW) is not None


def test_rule3_model_still_never_feeds_itself():
    assert model._peer(_record("DROP_RATE_COMPUTED_MARKET_V1"), NOW) is None


def test_rule4_stored_sold_values_clear_after_the_90_day_window():
    source = (ROOT / "live_market_refresh.py").read_text(encoding="utf-8")
    assert "and s.newest_observation_at>=now()-interval '90 days')" in source


def test_rule2_browse_order_is_sold_then_uk_asks_then_eu_guide():
    js = (ROOT / "static" / "catalogue-browser.js").read_text(encoding="utf-8")
    start = js.index("const marketPrice = row => {")
    body = js[start:js.index("const historicalPrice", start)]
    order = [body.index(marker) for marker in ("ukSold(row)", "askingEstimate(row)", "regionalSales(row)", "euGuide(row)")]
    assert order == sorted(order)
    assert '"UK asking median: "' in body and "Cardmarket EU guide" in js


def test_rule1_display_gate_labels_eu_guides_and_hides_models():
    js = (ROOT / "static" / "reference-value-display.js").read_text(encoding="utf-8")
    assert '"CATALOGUE_CARDMARKET_V1", "CARDMARKET_CATALOGUE_GUIDE"' in js
    assert '"Estimate: " + range + " · Cardmarket EU guide"' in js
    assert "DROP_RATE_COMPUTED_MARKET_V1" in js  # still in the never-money set
