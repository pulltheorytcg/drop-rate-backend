from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx


ECB_HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
ECB_SOURCE_NAME = "ECB_REFERENCE_RATES"


class FxRateError(RuntimeError):
    """Sanitised FX-provider error safe to surface in operational logs."""


@dataclass(frozen=True, slots=True)
class FxQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_at: datetime
    retrieved_at: datetime
    source: str

    def validate(self) -> "FxQuote":
        base = self.base_currency.upper().strip()
        quote = self.quote_currency.upper().strip()
        if len(base) != 3 or len(quote) != 3:
            raise ValueError("FX currencies must be three-letter codes")
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
        """Return an auditable FX quote effective on or before ``at``."""
        ...


class EcbFxRateProvider:
    """Historical ECB reference-rate provider for USD/EUR to GBP normalisation.

    ECB publishes currencies against EUR. Therefore:
    - EUR -> GBP = ECB GBP rate
    - USD -> GBP = ECB GBP rate / ECB USD rate

    Weekend and TARGET-closing-day observations use the most recent published
    ECB reference date on or before the observation date. The downloaded
    history is cached in memory for a bounded period to avoid unnecessary
    network traffic during ingestion batches.
    """

    def __init__(
        self,
        *,
        history_url: str = ECB_HISTORY_URL,
        timeout_seconds: float = 20.0,
        cache_ttl: timedelta = timedelta(hours=6),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if cache_ttl.total_seconds() <= 0:
            raise ValueError("cache_ttl must be positive")
        self._history_url = history_url
        self._timeout = httpx.Timeout(timeout_seconds)
        self._cache_ttl = cache_ttl
        self._rows: dict[datetime, tuple[Decimal, Decimal]] | None = None
        self._cache_loaded_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def quote(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> FxQuote:
        base = base_currency.upper().strip()
        quote = quote_currency.upper().strip()
        if quote != "GBP":
            raise ValueError("ECB FX provider currently supports GBP as quote currency")
        if base not in {"USD", "EUR"}:
            raise ValueError("ECB FX provider currently supports USD or EUR as base currency")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("FX quote timestamp must be timezone-aware")

        rows = await self._history()
        target_date = at.astimezone(timezone.utc).date()
        eligible = [stamp for stamp in rows if stamp.date() <= target_date]
        if not eligible:
            raise FxRateError("No ECB reference rate is available for the requested date")
        effective_at = max(eligible)
        usd_per_eur, gbp_per_eur = rows[effective_at]

        rate = gbp_per_eur if base == "EUR" else gbp_per_eur / usd_per_eur
        return FxQuote(
            base_currency=base,
            quote_currency="GBP",
            rate=rate,
            effective_at=effective_at,
            retrieved_at=datetime.now(timezone.utc),
            source=ECB_SOURCE_NAME,
        ).validate()

    async def _history(self) -> dict[datetime, tuple[Decimal, Decimal]]:
        now = datetime.now(timezone.utc)
        if (
            self._rows is not None
            and self._cache_loaded_at is not None
            and now - self._cache_loaded_at < self._cache_ttl
        ):
            return self._rows

        async with self._lock:
            now = datetime.now(timezone.utc)
            if (
                self._rows is not None
                and self._cache_loaded_at is not None
                and now - self._cache_loaded_at < self._cache_ttl
            ):
                return self._rows

            rows = await self._download_history()
            self._rows = rows
            self._cache_loaded_at = now
            return rows

    async def _download_history(self) -> dict[datetime, tuple[Decimal, Decimal]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._history_url, headers={"Accept": "application/zip"})
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FxRateError("ECB FX history request timed out") from exc
        except httpx.HTTPError as exc:
            raise FxRateError("ECB FX history request failed") from exc

        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                if len(csv_names) != 1:
                    raise FxRateError("ECB FX archive contained an unexpected file layout")
                text = archive.read(csv_names[0]).decode("utf-8-sig")
        except FxRateError:
            raise
        except (zipfile.BadZipFile, UnicodeDecodeError, KeyError) as exc:
            raise FxRateError("ECB FX history archive could not be read") from exc

        parsed: dict[datetime, tuple[Decimal, Decimal]] = {}
        try:
            reader = csv.DictReader(io.StringIO(text))
            for raw in reader:
                row = {str(key).strip(): (value.strip() if isinstance(value, str) else value) for key, value in raw.items() if key}
                date_text = row.get("Date")
                usd_text = row.get("USD")
                gbp_text = row.get("GBP")
                if not date_text or not usd_text or not gbp_text:
                    continue
                if usd_text == "N/A" or gbp_text == "N/A":
                    continue
                try:
                    usd = Decimal(usd_text)
                    gbp = Decimal(gbp_text)
                except InvalidOperation:
                    continue
                if usd <= 0 or gbp <= 0:
                    continue
                effective_date = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
                parsed[effective_date] = (usd, gbp)
        except (csv.Error, ValueError) as exc:
            raise FxRateError("ECB FX history CSV could not be parsed") from exc

        if not parsed:
            raise FxRateError("ECB FX history contained no usable USD/GBP rates")
        return parsed
