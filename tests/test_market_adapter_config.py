from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.cardmarket_parse_adapter import CardmarketParseAdapter
from app.collectr_parse_adapter import CollectrParseAdapter
from app.ebay_official_adapter import EbayOfficialBrowseAdapter
from app.ebay_uk_parse_adapter import EbayUkParseAdapter
from app.fx import FxQuote
from app.market_adapter_config import configure_market_adapters
from app.settings import Settings
from app.tcgplayer_parse_adapter import TcgplayerParseAdapter


class FakeFxProvider:
    async def quote(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> FxQuote:
        return FxQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=Decimal("0.75"),
            effective_at=at,
            retrieved_at=datetime.now(timezone.utc),
            source="TEST_FX",
        )


def settings(
    *,
    parse_api_key: str | None,
    ebay_client_id: str | None = None,
    ebay_client_secret: str | None = None,
) -> Settings:
    return Settings(
        database_url="postgresql://example",
        auth_issuer="https://example.supabase.co/auth/v1",
        auth_audience="authenticated",
        jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="publishable-test-key",
        environment="test",
        db_pool_min=1,
        db_pool_max=2,
        parse_api_key=parse_api_key,
        ebay_client_id=ebay_client_id,
        ebay_client_secret=ebay_client_secret,
        ebay_marketplace_id="EBAY_GB",
    )


def test_parse_key_absent_keeps_parse_adapters_unregistered(monkeypatch) -> None:
    registered = []
    monkeypatch.setattr(
        "app.market_adapter_config.register_adapter",
        lambda adapter: registered.append(adapter),
    )

    result = configure_market_adapters(settings(parse_api_key=None), fx_provider=FakeFxProvider())

    assert result == {
        "EBAY": False,
        "TCGPLAYER": False,
        "CARDMARKET": False,
        "COLLECTR": False,
    }
    assert registered == []


def test_parse_key_and_fx_provider_register_market_adapters(monkeypatch) -> None:
    registered = []
    monkeypatch.setattr(
        "app.market_adapter_config.register_adapter",
        lambda adapter: registered.append(adapter),
    )

    result = configure_market_adapters(
        settings(parse_api_key="secret-test-key"),
        fx_provider=FakeFxProvider(),
    )

    assert result == {
        "EBAY": True,
        "TCGPLAYER": True,
        "CARDMARKET": True,
        "COLLECTR": True,
    }
    assert len(registered) == 4
    assert isinstance(registered[0], EbayUkParseAdapter)
    assert isinstance(registered[1], TcgplayerParseAdapter)
    assert isinstance(registered[2], CardmarketParseAdapter)
    assert isinstance(registered[3], CollectrParseAdapter)


def test_default_ecb_provider_is_lazy_and_does_not_call_network_at_configuration(monkeypatch) -> None:
    registered = []
    network_calls = []

    monkeypatch.setattr(
        "app.market_adapter_config.register_adapter",
        lambda adapter: registered.append(adapter),
    )

    class ExplodingAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            network_calls.append("constructed")
            raise AssertionError("network client must not be created during adapter configuration")

    monkeypatch.setattr("app.fx.httpx.AsyncClient", ExplodingAsyncClient)

    result = configure_market_adapters(settings(parse_api_key="secret-test-key"))

    assert result == {
        "EBAY": True,
        "TCGPLAYER": True,
        "CARDMARKET": True,
        "COLLECTR": True,
    }
    assert len(registered) == 4
    assert isinstance(registered[0], EbayUkParseAdapter)
    assert isinstance(registered[1], TcgplayerParseAdapter)
    assert isinstance(registered[2], CardmarketParseAdapter)
    assert isinstance(registered[3], CollectrParseAdapter)
    assert network_calls == []


def test_official_ebay_credentials_take_precedence_over_parse_ebay(monkeypatch) -> None:
    registered = []
    monkeypatch.setattr(
        "app.market_adapter_config.register_adapter",
        lambda adapter: registered.append(adapter),
    )

    result = configure_market_adapters(
        settings(
            parse_api_key="parse-test-key",
            ebay_client_id="ebay-client",
            ebay_client_secret="ebay-secret",
        ),
        fx_provider=FakeFxProvider(),
    )

    assert result["EBAY"] is True
    assert len(registered) == 4
    assert isinstance(registered[0], EbayOfficialBrowseAdapter)
    assert not any(isinstance(adapter, EbayUkParseAdapter) for adapter in registered)
