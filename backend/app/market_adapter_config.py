from __future__ import annotations

from .cardmarket_parse_adapter import CardmarketParseAdapter
from .collectr_parse_adapter import CollectrParseAdapter
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
    """Register Parse-backed market adapters when required dependencies exist.

    The official ECB historical reference-rate provider is used by default when
    Parse access exists, keeping USD/EUR normalisation deterministic and auditable.
    Tests can inject a fake FX provider instead.
    """

    configured = {"TCGPLAYER": False, "CARDMARKET": False, "COLLECTR": False}

    if settings.parse_api_key:
        provider = fx_provider or EcbHistoricalFxProvider()
        client = ParseHttpClient(api_key=settings.parse_api_key)

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
