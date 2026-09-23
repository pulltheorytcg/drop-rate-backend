from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import httpx

from .tcgplayer_parse_adapter import FxQuote


ECB_HISTORICAL_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
ECB_SOURCE_NAME = "ECB_EURO_REFERENCE_RATES"
ECB_CUBE_NAMESPACE = "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"


class EcbFxRateProvider:
    """Auditable ECB reference-rate provider for Drop Rate market normalisation.

    ECB publishes rates with EUR as the base currency. EUR->GBP therefore uses
    the GBP reference rate directly, while USD->GBP is derived as GBP/USD from
    the same dated ECB table. For weekends/holidays the latest published rate
    on or before the observation date is used.
    """

    def __init__(
        self,
        *,
        url: str = ECB_HISTORICAL_RATES_URL,
        timeout_seconds: float = 15.0,
        cache_ttl: timedelta = timedelta(hours=6),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if cache_ttl.total_seconds() <= 0:
            raise ValueError("cache_ttl must be positive")
        self._url = url
        self._timeout = httpx.Timeout(timeout_seconds)
        self._cache_ttl = cache_ttl
        self._rates_by_date: dict[date, dict[str, Decimal]] = {}
        self._retrieved_at: datetime | None = None
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
            raise ValueError("ECB provider currently supports GBP quote currency only")
        if base not in {"USD", "EUR"}:
            raise ValueError("ECB provider currently supports USD or EUR base currency")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("FX quote timestamp must be timezone-aware")

        await self._ensure_rates()
        target_date = at.astimezone(timezone.utc).date()
        effective_date = self._latest_available_date(target_date)
        rates = self._rates_by_date[effective_date]

        gbp_per_eur = rates.get("GBP")
        if gbp_per_eur is None or gbp_per_eur <= 0:
            raise RuntimeError("ECB GBP reference rate is unavailable")

        if base == "EUR":
            rate = gbp_per_eur
        else:
            usd_per_eur = rates.get("USD")
            if usd_per_eur is None or usd_per_eur <= 0:
                raise RuntimeError("ECB USD reference rate is unavailable")
            rate = gbp_per_eur / usd_per_eur

        retrieved_at = self._retrieved_at
        if retrieved_at is None:
            raise RuntimeError("ECB FX cache has no retrieval timestamp")

        return FxQuote(
            base_currency=base,
            quote_currency="GBP",
            rate=rate,
            effective_at=datetime(
                effective_date.year,
                effective_date.month,
                effective_date.day,
                tzinfo=timezone.utc,
            ),
            retrieved_at=retrieved_at,
            source=ECB_SOURCE_NAME,
        ).validate()

    async def _ensure_rates(self) -> None:
        now = datetime.now(timezone.utc)
        if (
            self._rates_by_date
            and self._retrieved_at is not None
            and now - self._retrieved_at < self._cache_ttl
        ):
            return

        async with self._lock:
            now = datetime.now(timezone.utc)
            if (
                self._rates_by_date
                and self._retrieved_at is not None
                and now - self._retrieved_at < self._cache_ttl
            ):
                return

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        self._url,
                        headers={"Accept": "application/xml,text/xml"},
                    )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError("ECB FX request timed out") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError("ECB FX request failed") from exc

            parsed = self._parse_history(response.text)
            if not parsed:
                raise RuntimeError("ECB FX response contained no dated rates")
            self._rates_by_date = parsed
            self._retrieved_at = now

    def _latest_available_date(self, target_date: date) -> date:
        eligible = [item for item in self._rates_by_date if item <= target_date]
        if not eligible:
            raise RuntimeError("No ECB FX rate is available on or before the observation date")
        return max(eligible)

    @staticmethod
    def _parse_history(xml_text: str) -> dict[date, dict[str, Decimal]]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise RuntimeError("ECB FX response was invalid XML") from exc

        parsed: dict[date, dict[str, Decimal]] = {}
        cube_tag = f"{{{ECB_CUBE_NAMESPACE}}}Cube"
        for time_cube in root.iter(cube_tag):
            raw_time = time_cube.attrib.get("time")
            if not raw_time:
                continue
            try:
                effective_date = date.fromisoformat(raw_time)
            except ValueError:
                continue

            rates: dict[str, Decimal] = {}
            for currency_cube in list(time_cube):
                currency = currency_cube.attrib.get("currency", "").upper().strip()
                raw_rate = currency_cube.attrib.get("rate")
                if not currency or not raw_rate:
                    continue
                try:
                    rate = Decimal(raw_rate)
                except InvalidOperation:
                    continue
                if rate > 0:
                    rates[currency] = rate
            if rates:
                parsed[effective_date] = rates
        return parsed
