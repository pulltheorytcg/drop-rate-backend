from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any, Protocol


SUPPORTED_MARKET_SOURCES = {"EBAY", "COLLECTR", "TCGPLAYER", "CARDMARKET", "CARDTRADER"}
SUPPORTED_OBSERVATION_TYPES = {"SOLD", "ACTIVE", "MARKET_AGGREGATE", "PRICE_GUIDE"}


@dataclass(frozen=True, slots=True)
class NormalizedMarketObservation:
    source: str
    source_record_key: str
    observation_type: str
    observed_at: datetime
    price_minor: int
    currency: str
    price_gbp_minor: int
    fx_rate_to_gbp: float
    catalogue_id: str
    shipping_minor: int | None = None
    shipping_gbp_minor: int | None = None
    condition: str | None = None
    grading_company: str | None = None
    grade: str | None = None
    language: str | None = None
    seal_status: str | None = None
    source_country: str | None = None
    sample_size: int = 1
    evidence_quality: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "NormalizedMarketObservation":
        if self.source not in SUPPORTED_MARKET_SOURCES:
            raise ValueError(f"Unsupported market source: {self.source}")
        if self.observation_type not in SUPPORTED_OBSERVATION_TYPES:
            raise ValueError(f"Unsupported observation type: {self.observation_type}")
        if not self.source_record_key.strip():
            raise ValueError("source_record_key is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.price_minor <= 0 or self.price_gbp_minor <= 0:
            raise ValueError("Market prices must be positive")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a 3-letter code")
        if self.fx_rate_to_gbp <= 0:
            raise ValueError("fx_rate_to_gbp must be positive")
        if self.sample_size < 1:
            raise ValueError("sample_size must be at least 1")
        if not 0 <= self.evidence_quality <= 1:
            raise ValueError("evidence_quality must be between 0 and 1")
        if (self.grading_company is None) != (self.grade is None):
            raise ValueError("grading_company and grade must be supplied together")
        if self.seal_status not in (None, "SEALED", "UNSEALED"):
            raise ValueError("seal_status must be SEALED, UNSEALED or null")
        if self.source_country is not None and len(self.source_country.strip()) != 2:
            raise ValueError("source_country must be a 2-letter code")
        return self


class MarketDataAdapter(Protocol):
    source: str

    async def fetch_observations(
        self,
        *,
        catalogue_id: str,
        source_product_id: str,
        source_variant_id: str | None,
    ) -> list[NormalizedMarketObservation]:
        """Fetch permitted provider data and normalize it into Drop Rate observations."""
        ...


_ADAPTERS: dict[str, MarketDataAdapter] = {}
_PROVIDER_NOTES = {
    "EBAY": "Use only official/permitted eBay developer data or user-provided exports.",
    "COLLECTR": "Adapter slot reserved for permitted Collectr export/API access.",
    "TCGPLAYER": "TCGplayer currently requires existing approved API access.",
    "CARDMARKET": "Cardmarket currently requires existing approved API access.",
    "CARDTRADER": "Official CardTrader API active listings for verified exact product mappings.",
}


def register_adapter(adapter: MarketDataAdapter) -> None:
    source = adapter.source.upper().strip()
    if source not in SUPPORTED_MARKET_SOURCES:
        raise ValueError(f"Unsupported market source: {source}")
    _ADAPTERS[source] = adapter


def get_adapter(source: str) -> MarketDataAdapter | None:
    return _ADAPTERS.get(source.upper().strip())


def stable_source_record_key(*parts: object) -> str:
    """Create a deterministic provider-record key when a provider lacks one."""
    material = "|".join(str(part).strip() for part in parts)
    return sha256(material.encode("utf-8")).hexdigest()


def adapter_availability() -> list[dict[str, str | bool]]:
    """Describe live-adapter readiness without pretending credentials/access exist."""
    items: list[dict[str, str | bool]] = []
    for source in ("EBAY", "COLLECTR", "TCGPLAYER", "CARDMARKET", "CARDTRADER"):
        implemented = source in _ADAPTERS
        items.append(
            {
                "source": source,
                "implemented": implemented,
                "status": "READY" if implemented else "ACCESS_REQUIRED",
                "note": _PROVIDER_NOTES[source],
            }
        )
    return items
