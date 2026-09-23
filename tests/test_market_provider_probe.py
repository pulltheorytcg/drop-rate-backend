from pathlib import Path

from app.market_provider_probe import PROBES, _summarise_payload


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
PROBE = ROOT / "backend" / "app" / "market_provider_probe.py"


def test_probe_matrix_is_exactly_five_free_tier_calls() -> None:
    assert len(PROBES) == 5
    assert [probe["label"] for probe in PROBES] == [
        "eBay UK active",
        "eBay UK sold",
        "Cardmarket search",
        "TCGPlayer search",
        "Collectr search",
    ]


def test_probe_summary_returns_counts_and_safe_samples_only() -> None:
    summary = _summarise_payload(
        {
            "items": [
                {
                    "title": "Charizard 4/102",
                    "price": "£100.00",
                    "secret": "must-not-leak",
                }
            ],
            "query": "Charizard",
        }
    )
    assert summary["list_counts"] == {"items": 1}
    assert summary["samples"] == [{"title": "Charizard 4/102", "price": "£100.00"}]
    assert "secret" not in summary["samples"][0]


def test_probe_uses_current_parse_release_and_never_persists() -> None:
    source = PROBE.read_text()
    assert "snapshot_version=None" in source
    assert '"persisted": False' in source
    assert "market_observations" not in source
    assert "pricing_snapshots" not in source


def test_probe_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_provider_probe import router as market_provider_probe_router" in main
    assert "app.include_router(market_provider_probe_router)" in main
