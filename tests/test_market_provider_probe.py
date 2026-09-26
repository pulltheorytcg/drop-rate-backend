from pathlib import Path

import pytest

from app.market_provider_probe import COLLECTR_PROBE_SCRAPER_ID, SUPPORTING_PROBES, _summarise_payload


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
PROBE = ROOT / "backend" / "app" / "market_provider_probe.py"


def test_supporting_probe_matrix_is_three_parse_calls() -> None:
    assert len(SUPPORTING_PROBES) == 3
    assert [probe["label"] for probe in SUPPORTING_PROBES] == [
        "Cardmarket search",
        "TCGPlayer search",
        "Collectr search",
    ]
    assert [probe["result_key"] for probe in SUPPORTING_PROBES] == [
        "results",
        "cards",
        "items",
    ]


def test_collectr_probe_uses_published_scraper_id() -> None:
    assert COLLECTR_PROBE_SCRAPER_ID == "deec24d2-ffc5-41bd-b3fd-99cd817443e2"
    collectr = next(probe for probe in SUPPORTING_PROBES if probe["source"] == "COLLECTR")
    assert collectr["scraper_id"] == COLLECTR_PROBE_SCRAPER_ID
    assert collectr["endpoint"] == "search_cards"


def test_probe_summary_counts_only_canonical_result_array() -> None:
    summary = _summarise_payload(
        {
            "available_sets": [{"name": f"set-{index}"} for index in range(151)],
            "cards": [
                {
                    "name": "Charizard",
                    "market_price": 100,
                    "secret": "must-not-leak",
                }
                for _ in range(10)
            ],
        },
        result_key="cards",
    )
    assert summary["list_counts"] == {"available_sets": 151, "cards": 10}
    assert summary["result_key"] == "cards"
    assert summary["result_count"] == 10
    assert len(summary["samples"]) == 3
    assert summary["samples"][0] == {"name": "Charizard", "market_price": 100}
    assert "secret" not in summary["samples"][0]


def test_probe_summary_rejects_unexpected_response_shape() -> None:
    with pytest.raises(ValueError, match="expected result array"):
        _summarise_payload({"available_sets": []}, result_key="cards")


def test_probe_uses_current_parse_release_and_never_persists() -> None:
    source = PROBE.read_text()
    assert "snapshot_version=None" in source
    assert '"persisted": False' in source
    assert "market_observations" not in source
    assert "pricing_snapshots" not in source


def test_probe_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_provider_probe import router as market_provider_probe_router" in main
    assert "app.include_router(market_provider_probe_router, dependencies=[Depends(require_platform_admin_request)])" in main


def test_probe_uses_official_ebay_and_never_infers_sold_history() -> None:
    source = PROBE.read_text()
    assert "EbayOfficialClient" in source
    assert "eBay UK active · official Browse" in source
    assert '"status": "RESTRICTED"' in source
    assert "Sold history is not inferred from Browse" in source
