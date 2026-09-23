from __future__ import annotations

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
    """Register provider adapters only when every required dependency exists.

    The official ECB historical reference-rate provider is used by default when
    Parse access exists, keeping USD/EUR normalisation deterministic and auditable.
    Tests can inject a fake FX provider instead.
    """

    configured = {"TCGPLAYER": False}

    if settings.parse_api_key:
        provider = fx_provider or EcbHistoricalFxProvider()
        register_adapter(
            TcgplayerParseAdapter(
                client=ParseHttpClient(api_key=settings.parse_api_key),
                fx_provider=provider,
            )
        )
        configured["TCGPLAYER"] = True

    return configured
