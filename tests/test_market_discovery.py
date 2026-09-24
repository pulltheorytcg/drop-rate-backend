from pathlib import Path

from app.market_discovery import DISCOVERY_SOURCES, _candidate
from app.collectr_parse_adapter import COLLECTR_PARSE_SCRAPER_ID


ROOT = Path(__file__).parents[1]
DISCOVERY = ROOT / "backend" / "app" / "market_discovery.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def catalogue() -> dict:
    return {
        "name": "Absol",
        "set_name": "Phantasmal Flames",
        "card_number": "063/094",
    }


def test_candidate_scoring_is_deterministic_and_identity_based() -> None:
    exact = _candidate(
        source="COLLECTR",
        source_product_id="123",
        name="Absol",
        set_name="Phantasmal Flames",
        card_number="063/094",
        catalogue=catalogue(),
    )
    wrong = _candidate(
        source="COLLECTR",
        source_product_id="456",
        name="Absol",
        set_name="Another Set",
        card_number="999/999",
        catalogue=catalogue(),
    )

    assert exact is not None
    assert exact["suggested_confidence"] == 1.0
    assert exact["match_signals"] == ["name", "set", "card_number"]
    assert wrong is not None
    assert wrong["suggested_confidence"] == 0.35
    assert wrong["match_signals"] == ["name"]


def test_discovery_sources_do_not_include_ebay_sold_path() -> None:
    assert DISCOVERY_SOURCES == {"CARDMARKET", "TCGPLAYER", "COLLECTR"}


def test_collectr_discovery_reuses_adapter_scraper_identity() -> None:
    source = DISCOVERY.read_text()
    assert "COLLECTR_PARSE_SCRAPER_ID" in source
    assert COLLECTR_PARSE_SCRAPER_ID in (ROOT / "backend" / "app" / "collectr_parse_adapter.py").read_text()


def test_discovery_is_non_persistent_and_releases_db_before_provider_io() -> None:
    source = DISCOVERY.read_text()
    assert '"persisted": False' in source
    assert "market_observations" not in source
    assert "pricing_snapshots" not in source
    assert "catalogue = await _catalogue_snapshot" in source
    assert "client = ParseHttpClient" in source


def test_discovery_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_discovery import router as market_discovery_router" in main
    assert "app.include_router(market_discovery_router)" in main
