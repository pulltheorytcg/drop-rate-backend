from datetime import datetime, timezone

import pytest

from app.market_adapters import NormalizedMarketObservation, adapter_availability, stable_source_record_key


@pytest.fixture(autouse=True)
def isolated_adapter_registry(monkeypatch):
    # App construction registers adapters when deployment credentials exist.
    # Unit tests must define their own registry instead of relying on test order.
    monkeypatch.setattr("app.market_adapters._ADAPTERS", {})


def test_stable_market_record_key_is_deterministic() -> None:
    first = stable_source_record_key("EBAY", "item-123", "2026-09-23", 9999)
    second = stable_source_record_key("EBAY", "item-123", "2026-09-23", 9999)
    assert first == second
    assert len(first) == 64


def test_normalized_market_observation_validates() -> None:
    observation = NormalizedMarketObservation(
        source="EBAY",
        source_record_key="sale-1",
        observation_type="SOLD",
        observed_at=datetime.now(timezone.utc),
        price_minor=10000,
        currency="GBP",
        price_gbp_minor=10000,
        fx_rate_to_gbp=1.0,
        catalogue_id="catalogue-1",
        condition="Near Mint",
        language="English",
    )
    assert observation.validate() is observation


def test_market_observation_rejects_grade_without_company() -> None:
    observation = NormalizedMarketObservation(
        source="EBAY",
        source_record_key="sale-1",
        observation_type="SOLD",
        observed_at=datetime.now(timezone.utc),
        price_minor=10000,
        currency="GBP",
        price_gbp_minor=10000,
        fx_rate_to_gbp=1.0,
        catalogue_id="catalogue-1",
        grade="10",
    )
    with pytest.raises(ValueError, match="supplied together"):
        observation.validate()


def test_provider_availability_does_not_pretend_live_access() -> None:
    items = adapter_availability()
    assert {item["source"] for item in items} == {"EBAY", "COLLECTR", "TCGPLAYER", "CARDMARKET", "CARDTRADER"}
    assert all(item["implemented"] is False for item in items)
    assert all(item["status"] == "ACCESS_REQUIRED" for item in items)


def test_provider_availability_reports_only_registered_adapters() -> None:
    from app.market_adapters import register_adapter

    class ConfiguredAdapter:
        source = "CARDTRADER"

        async def fetch_observations(self, **kwargs):
            raise AssertionError("Availability checks must not call the provider")

    register_adapter(ConfiguredAdapter())
    items = {item["source"]: item for item in adapter_availability()}
    assert items["CARDTRADER"]["implemented"] is True
    assert items["CARDTRADER"]["status"] == "READY"
    assert all(
        item["implemented"] is False and item["status"] == "ACCESS_REQUIRED"
        for source, item in items.items() if source != "CARDTRADER"
    )
