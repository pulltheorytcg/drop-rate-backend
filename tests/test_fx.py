from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.fx import ECB_SOURCE, EcbHistoricalFxProvider


NOW = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)


def provider_with_rates() -> EcbHistoricalFxProvider:
    provider = EcbHistoricalFxProvider()
    provider._rates = {
        date(2026, 9, 18): {"USD": Decimal("1.2000"), "GBP": Decimal("0.8400")},
        date(2026, 9, 21): {"USD": Decimal("1.2500"), "GBP": Decimal("0.8500")},
    }
    provider._retrieved_at = NOW
    return provider


def test_eur_to_gbp_uses_published_ecb_rate() -> None:
    provider = provider_with_rates()
    quote = asyncio.run(
        provider.quote(base_currency="EUR", quote_currency="GBP", at=NOW)
    )
    assert quote.rate == Decimal("0.8500")
    assert quote.source == ECB_SOURCE
    assert quote.effective_at.date() == date(2026, 9, 21)


def test_usd_to_gbp_uses_eur_cross() -> None:
    provider = provider_with_rates()
    quote = asyncio.run(
        provider.quote(base_currency="USD", quote_currency="GBP", at=NOW)
    )
    assert quote.rate == Decimal("0.8500") / Decimal("1.2500")
    assert quote.base_currency == "USD"
    assert quote.quote_currency == "GBP"


def test_weekend_falls_back_to_previous_published_day() -> None:
    provider = provider_with_rates()
    saturday = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    quote = asyncio.run(
        provider.quote(base_currency="USD", quote_currency="GBP", at=saturday)
    )
    assert quote.effective_at.date() == date(2026, 9, 18)
    assert quote.rate == Decimal("0.8400") / Decimal("1.2000")


def test_provider_fails_closed_when_recent_rate_is_missing() -> None:
    provider = provider_with_rates()
    stale_date = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="No recent ECB FX"):
        asyncio.run(
            provider.quote(base_currency="USD", quote_currency="GBP", at=stale_date)
        )


def test_only_supported_base_currencies_are_accepted() -> None:
    provider = provider_with_rates()
    with pytest.raises(ValueError, match="Unsupported ECB FX base currency"):
        asyncio.run(
            provider.quote(base_currency="JPY", quote_currency="GBP", at=NOW)
        )
