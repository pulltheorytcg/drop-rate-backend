import pytest

from app.settings import Settings


def test_settings_reject_invalid_pool(monkeypatch):
    monkeypatch.setenv("TCG_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.setenv("TCG_DB_POOL_MIN", "5")
    monkeypatch.setenv("TCG_DB_POOL_MAX", "2")
    with pytest.raises(RuntimeError, match="cannot exceed"):
        Settings.from_env()


def test_default_jwks_url(monkeypatch):
    monkeypatch.setenv("TCG_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1/")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.delenv("TCG_JWKS_URL", raising=False)
    settings = Settings.from_env()
    assert settings.jwks_url == "https://example.test/auth/v1/.well-known/jwks.json"
