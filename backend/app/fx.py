from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx


ECB_HISTORICAL_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
ECB_SOURCE = "ECB_EURO_REFERENCE_RATES"
_MAX_FALLBACK_DAYS = 7


@dataclass(frozen=True, slots=True)
class FxQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_at: datetime
    retrieved_at: datetime
    source: str

    def validate(self) -> "FxQuote":
        if len(self.base_currency.strip()) != 3 or len(self.quote_currency.strip()) != 3:
            raise ValueError("FX currencies must be 3-letter codes")
        if self.rate <= 0:
            raise ValueError("FX rate must be positive")
        if self.effective_at.tzinfo is None or self.retrieved_at.tzinfo is None:
            raise ValueError("FX timestamps must be timezone-aware")
        if not self.source.strip():
            raise ValueError("FX source is required")
        return self


class FxRateProvider(Protocol):
    async def quote(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> FxQuote:
        """Return an auditable FX quote for the requested observation time."""
        ...


class EcbHistoricalFxProvider:
    """Historical GBP normalisation using official ECB euro reference rates.

    ECB rows quote each currency as units per EUR. EUR->GBP is therefore the
    published GBP rate, while USD->GBP is derived as GBP-per-EUR / USD-per-EUR.
    Missing weekends/TARGET closing days fall back to the most recent published
    day within seven calendar days.
    """

    def __init__(
        self,
        *,
        url: str = ECB_HISTORICAL_RATES_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._url = url
        self._timeout = httpx.Timeout(timeout_seconds)
        self._rates: dict[date, dict[str, Decimal]] | None = None
        self._retrieved_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def quote(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> FxQuote:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("FX quote time must be timezone-aware")

        base = base_currency.upper().strip()
        quote = quote_currency.upper().strip()
        if quote != "GBP":
            raise ValueError("ECB provider currently supports GBP quote currency only")
        if base not in {"USD", "EUR", "GBP"}:
            raise ValueError(f"Unsupported ECB FX base currency: {base}")

        if base == "GBP":
            now = datetime.now(timezone.utc)
            return FxQuote(
                base_currency="GBP",
                quote_currency="GBP",
                rate=Decimal("1"),
                effective_at=at,
                retrieved_at=now,
                source=ECB_SOURCE,
            ).validate()

        await self._ensure_loaded()
        assert self._rates is not None
        assert self._retrieved_at is not None

        requested_day = at.astimezone(timezone.utc).date()
        effective_day, row = self._find_rate_day(requested_day)
        gbp_per_eur = row.get("GBP")
        if gbp_per_eur is None or gbp_per_eur <= 0:
            raise RuntimeError("ECB GBP reference rate is unavailable")

        if base == "EUR":
            rate = gbp_per_eur
        else:
            usd_per_eur = row.get("USD")
            if usd_per_eur is None or usd_per_eur <= 0:
                raise RuntimeError("ECB USD reference rate is unavailable")
            rate = gbp_per_eur / usd_per_eur

        ecb_tz = ZoneInfo("Europe/Berlin")
        effective_at = datetime.combine(effective_day, time(16, 0), tzinfo=ecb_tz)
        return FxQuote(
            base_currency=base,
            quote_currency="GBP",
            rate=rate,
            effective_at=effective_at,
            retrieved_at=self._retrieved_at,
            source=ECB_SOURCE,
        ).validate()

    async def _ensure_loaded(self) -> None:
        if self._rates is not None:
            return
        async with self._lock:
            if self._rates is not None:
                return
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(self._url, headers={"Accept": "application/xml,text/xml"})
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError("ECB FX request timed out") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError("ECB FX request failed") from exc

            try:
                rates = self._parse_rates(response.content)
            except (ElementTree.ParseError, ValueError) as exc:
                raise RuntimeError("ECB FX response was invalid") from exc
            if not rates:
                raise RuntimeError("ECB FX response contained no rates")
            self._rates = rates
            self._retrieved_at = datetime.now(timezone.utc)

    @staticmethod
    def _parse_rates(payload: bytes) -> dict[date, dict[str, Decimal]]:
        root = ElementTree.fromstring(payload)
        result: dict[date, dict[str, Decimal]] = {}
        for element in root.iter():
            time_value = element.attrib.get("time")
            if not time_value:
                continue
            try:
                day = date.fromisoformat(time_value)
            except ValueError:
                continue
            row: dict[str, Decimal] = {}
            for child in element:
                currency = child.attrib.get("currency", "").upper().strip()
                raw_rate = child.attrib.get("rate")
                if not currency or raw_rate is None:
                    continue
                rate = Decimal(raw_rate)
                if rate > 0:
                    row[currency] = rate
            if row:
                result[day] = row
        return result

    def _find_rate_day(self, requested_day: date) -> tuple[date, dict[str, Decimal]]:
        assert self._rates is not None
        for offset in range(_MAX_FALLBACK_DAYS + 1):
            candidate = requested_day - timedelta(days=offset)
            row = self._rates.get(candidate)
            if row is not None:
                return candidate, row
        raise RuntimeError("No recent ECB FX reference rate is available")
