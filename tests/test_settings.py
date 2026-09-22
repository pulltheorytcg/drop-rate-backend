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
