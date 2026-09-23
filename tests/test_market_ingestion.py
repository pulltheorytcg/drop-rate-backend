from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.market_adapters import NormalizedMarketObservation
from app.market_ingestion import derive_run_status, validate_provider_observation


ROOT = Path(__file__).parents[1]
INGESTION = ROOT / "backend" / "app" / "market_ingestion.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def observation(*, source: str = "EBAY", catalogue_id: str) -> NormalizedMarketObservation:
    return NormalizedMarketObservation(
        source=source,
        source_record_key="provider-record-1",
        observation_type="SOLD",
        observed_at=datetime.now(timezone.utc),
        price_minor=12500,
        currency="GBP",
        price_gbp_minor=12500,
        fx_rate_to_gbp=1.0,
        catalogue_id=catalogue_id,
        condition="Near Mint",
        language="English",
    )


def test_ingestion_rejects_wrong_catalogue_product() -> None:
    expected = uuid4()
    wrong = uuid4()
    with pytest.raises(ValueError, match="wrong catalogue"):
        validate_provider_observation(
            observation(catalogue_id=str(wrong)),
            expected_source="EBAY",
            expected_catalogue_id=expected,
        )


def test_ingestion_rejects_wrong_provider_source() -> None:
    catalogue_id = uuid4()
    with pytest.raises(ValueError, match="expected EBAY"):
        validate_provider_observation(
            observation(source="CARDMARKET", catalogue_id=str(catalogue_id)),
            expected_source="EBAY",
            expected_catalogue_id=catalogue_id,
        )


def test_ingestion_status_is_deterministic() -> None:
    assert derive_run_status(mapping_count=0, failed_mapping_count=0, accepted_count=0) == "BLOCKED"
    assert derive_run_status(mapping_count=3, failed_mapping_count=0, accepted_count=8) == "SUCCEEDED"
    assert derive_run_status(mapping_count=3, failed_mapping_count=1, accepted_count=5) == "PARTIAL"
    assert derive_run_status(mapping_count=3, failed_mapping_count=3, accepted_count=0) == "FAILED"


def test_ingestion_only_uses_verified_mappings_and_deduplicates_records() -> None:
    source = INGESTION.read_text()
    assert "match_status = 'VERIFIED'" in source
    assert "on conflict (source, source_record_key) do nothing" in source
    assert "Adapter returned an observation for the wrong catalogue product" in source


def test_market_ingestion_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_ingestion import router as market_ingestion_router" in main
    assert "app.include_router(market_ingestion_router)" in main
