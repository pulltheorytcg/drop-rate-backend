from __future__ import annotations

from .market_adapters import register_adapter
from .parse_client import ParseHttpClient
from .settings import Settings
from .tcgplayer_parse_adapter import FxRateProvider, TcgplayerParseAdapter


def configure_market_adapters(
    settings: Settings,
    *,
    fx_provider: FxRateProvider | None = None,
) -> dict[str, bool]:
    """Register provider adapters only when every required dependency exists.

    Parse credentials alone are intentionally insufficient for TCGPlayer because
    USD observations must never be normalised using a guessed FX rate.
    """

    configured = {"TCGPLAYER": False}

    if settings.parse_api_key and fx_provider is not None:
        register_adapter(
            TcgplayerParseAdapter(
                client=ParseHttpClient(api_key=settings.parse_api_key),
                fx_provider=fx_provider,
            )
        )
        configured["TCGPLAYER"] = True

    return configured
