from __future__ import annotations

from .cardmarket_parse_adapter import CardmarketParseAdapter
from .collectr_parse_adapter import CollectrParseAdapter
from .ebay_official_adapter import EbayOfficialBrowseAdapter
from .ebay_official_client import EbayOfficialClient
from .ebay_uk_parse_adapter import EbayUkParseAdapter
from .fx import EcbHistoricalFxProvider, FxRateProvider
from .market_adapters import register_adapter
from .parse_client import ParseHttpClient
from .settings import Settings
from .tcgplayer_parse_adapter import TcgplayerParseAdapter


def configure_market_adapters(
    settings: Settings,
    *,
    fx_provider: FxRateProvider | None = None,
) -> dict[str, bool]:
    """Register market adapters from explicitly configured provider access.

    Official eBay credentials take precedence over the legacy Parse-backed eBay
    diagnostic adapter. Parse remains available for Cardmarket/TCGPlayer/Collectr
    while those provider integrations are validated independently.
    """

    configured = {
        "EBAY": False,
        "TCGPLAYER": False,
        "CARDMARKET": False,
        "COLLECTR": False,
    }

    if settings.ebay_client_id and settings.ebay_client_secret:
        register_adapter(
            EbayOfficialBrowseAdapter(
                client=EbayOfficialClient(
                    client_id=settings.ebay_client_id,
                    client_secret=settings.ebay_client_secret,
                    marketplace_id=settings.ebay_marketplace_id,
                )
            )
        )
        configured["EBAY"] = True

    if settings.parse_api_key:
        provider = fx_provider or EcbHistoricalFxProvider()
        client = ParseHttpClient(api_key=settings.parse_api_key)

        if not configured["EBAY"]:
            register_adapter(EbayUkParseAdapter(client=client))
            configured["EBAY"] = True

        register_adapter(
            TcgplayerParseAdapter(
                client=client,
                fx_provider=provider,
            )
        )
        configured["TCGPLAYER"] = True

        register_adapter(
            CardmarketParseAdapter(
                client=client,
                fx_provider=provider,
            )
        )
        configured["CARDMARKET"] = True

        register_adapter(
            CollectrParseAdapter(
                client=client,
                fx_provider=provider,
            )
        )
        configured["COLLECTR"] = True

    return configured
