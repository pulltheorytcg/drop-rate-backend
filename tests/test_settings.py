import pytest

from app.settings import Settings


def _base_env(monkeypatch) -> None:
    monkeypatch.setenv("TCG_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.setenv("TCG_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")


def test_settings_reject_invalid_pool(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("TCG_DB_POOL_MIN", "5")
    monkeypatch.setenv("TCG_DB_POOL_MAX", "2")
    with pytest.raises(RuntimeError, match="cannot exceed"):
        Settings.from_env()


def test_default_jwks_url(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1/")
    monkeypatch.delenv("TCG_JWKS_URL", raising=False)
    settings = Settings.from_env()
    assert settings.jwks_url == "https://example.test/auth/v1/.well-known/jwks.json"
    assert settings.supabase_url == "https://example.test"


def test_publishable_key_is_required(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("TCG_SUPABASE_PUBLISHABLE_KEY")
    with pytest.raises(RuntimeError, match="TCG_SUPABASE_PUBLISHABLE_KEY"):
        Settings.from_env()


def test_ebay_settings_default_to_gb_and_optional_credentials(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("TCG_EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("TCG_EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TCG_EBAY_MARKETPLACE_ID", raising=False)
    settings = Settings.from_env()
    assert settings.ebay_client_id is None
    assert settings.ebay_client_secret is None
    assert settings.ebay_marketplace_id == "EBAY_GB"


def test_ebay_settings_read_production_credentials(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("TCG_EBAY_CLIENT_ID", "client")
    monkeypatch.setenv("TCG_EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TCG_EBAY_MARKETPLACE_ID", "EBAY_GB")
    settings = Settings.from_env()
    assert settings.ebay_client_id == "client"
    assert settings.ebay_client_secret == "secret"
    assert settings.ebay_marketplace_id == "EBAY_GB"


def test_shopify_settings_are_optional_and_publishing_defaults_off(monkeypatch):
    _base_env(monkeypatch)
    for name in (
        "TCG_SHOPIFY_SHOP_DOMAIN",
        "TCG_SHOPIFY_CLIENT_ID",
        "TCG_SHOPIFY_CLIENT_SECRET",
        "TCG_SHOPIFY_API_VERSION",
        "TCG_SHOPIFY_PUBLISH_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.shopify_shop_domain is None
    assert settings.shopify_client_id is None
    assert settings.shopify_client_secret is None
    assert settings.shopify_api_version == "2026-07"
    assert settings.shopify_publish_enabled is False


def test_shopify_domain_requires_canonical_myshopify_domain(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("TCG_SHOPIFY_SHOP_DOMAIN", "https://drop-rate.myshopify.com/admin")
    with pytest.raises(RuntimeError, match="canonical"):
        Settings.from_env()


def test_shopify_settings_read_server_side_credentials(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("TCG_SHOPIFY_SHOP_DOMAIN", "Drop-Rate.myshopify.com")
    monkeypatch.setenv("TCG_SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("TCG_SHOPIFY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TCG_SHOPIFY_API_VERSION", "2026-07")
    monkeypatch.setenv("TCG_SHOPIFY_PUBLISH_ENABLED", "false")
    settings = Settings.from_env()
    assert settings.shopify_shop_domain == "drop-rate.myshopify.com"
    assert settings.shopify_client_id == "client-id"
    assert settings.shopify_client_secret == "secret"
    assert settings.shopify_api_version == "2026-07"
    assert settings.shopify_publish_enabled is False
