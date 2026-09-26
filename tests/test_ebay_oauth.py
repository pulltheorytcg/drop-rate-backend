from __future__ import annotations

from pathlib import Path

import pytest

from app.ebay_oauth import AUTHORIZE_URL, _oauth_missing
from app.ebay_sell_client import REQUIRED_SELLER_SCOPES
from app.ebay_seller_connection import decrypt_refresh_token, encrypt_refresh_token
from app.settings import Settings


ROOT = Path(__file__).parents[1]
OAUTH_SOURCE = ROOT / "backend" / "app" / "ebay_oauth.py"
CLIENT_SOURCE = ROOT / "backend" / "app" / "ebay_sell_client.py"
SALES_SOURCE = ROOT / "backend" / "app" / "ebay_sales.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260926152429_ebay_seller_oauth_connection.sql"
)


def _settings(**overrides) -> Settings:
    values = dict(
        database_url="postgresql://example",
        auth_issuer="https://example.test/auth/v1",
        auth_audience="authenticated",
        jwks_url="https://example.test/jwks",
        supabase_url="https://example.test",
        supabase_publishable_key="sb_publishable_test",
        environment="test",
        db_pool_min=1,
        db_pool_max=2,
        parse_api_key=None,
        ebay_client_id="client",
        ebay_client_secret="secret",
        ebay_marketplace_id="EBAY_GB",
        ebay_runame="DropRate-DropRate-PRD-oauth",
        ebay_oauth_callback_endpoint=(
            "https://drop-rate.example/api/v1/ebay/oauth/callback"
        ),
        ebay_oauth_encryption_key=(
            "j0p7YGA6TJjVOubPYgYhUxD4BVzi75Ht07Y9ODTiWk0="
        ),
    )
    values.update(overrides)
    return Settings(**values)


def test_oauth_requires_runame_callback_and_separate_encryption_key() -> None:
    missing = _oauth_missing(
        _settings(
            ebay_runame=None,
            ebay_oauth_callback_endpoint=None,
            ebay_oauth_encryption_key=None,
        )
    )
    assert "TCG_EBAY_RUNAME" in missing
    assert "TCG_EBAY_OAUTH_CALLBACK_ENDPOINT" in missing
    assert "TCG_EBAY_OAUTH_ENCRYPTION_KEY" in missing


def test_seller_refresh_token_is_encrypted_at_rest() -> None:
    settings = _settings()
    refresh_token = "v^1.1#seller-refresh-token"
    ciphertext = encrypt_refresh_token(settings, refresh_token)
    assert refresh_token not in ciphertext
    assert decrypt_refresh_token(settings, ciphertext) == refresh_token


def test_wrong_encryption_key_cannot_decrypt_seller_token() -> None:
    ciphertext = encrypt_refresh_token(_settings(), "refresh-secret")
    other = _settings(
        ebay_oauth_encryption_key=(
            "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZY="
        )
    )
    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        decrypt_refresh_token(other, ciphertext)


def test_oauth_start_uses_ebay_production_authorize_url_and_csrf_state() -> None:
    source = OAUTH_SOURCE.read_text()
    assert AUTHORIZE_URL == "https://auth.ebay.com/oauth2/authorize"
    assert "secrets.token_urlsafe(32)" in source
    assert "hashlib.sha256(state.encode" in source
    assert '"state": state' in source
    assert '"prompt": "login"' in source
    assert '"locale": "en-GB"' in source
    assert '"scope": " ".join(REQUIRED_SELLER_SCOPES)' in source


def test_oauth_callback_exchanges_code_and_never_persists_plaintext_refresh_token() -> None:
    oauth = OAUTH_SOURCE.read_text()
    client = CLIENT_SOURCE.read_text()
    assert "exchange_authorization_code(" in oauth
    assert "encrypt_refresh_token(settings, refresh_token)" in oauth
    assert "refresh_token_ciphertext" in oauth
    assert "grant_type" in client
    assert '"authorization_code"' in client
    assert '"redirect_uri": redirect_uri.strip()' in client


def test_oauth_attempt_is_single_use_and_expires() -> None:
    source = OAUTH_SOURCE.read_text()
    assert "consumed_at is null" in source
    assert "expires_at > clock_timestamp()" in source
    assert "set consumed_at=clock_timestamp()" in source
    assert "STATE_TTL_MINUTES = 10" in source


def test_oauth_connection_schema_hides_token_from_audit_payload() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "create table tcg.ebay_seller_connections" in sql
    assert "refresh_token_ciphertext text not null" in sql
    assert "force row level security" in sql
    assert "revoke delete on table tcg.ebay_seller_connections from tcg_api" in sql
    assert "- 'refresh_token_ciphertext'" in sql
    assert "ebay seller connection ownership is immutable" in sql


def test_cross_channel_sales_can_resolve_encrypted_seller_connection() -> None:
    source = SALES_SOURCE.read_text()
    assert "load_effective_seller_config" in source
    assert "seller_client(" in source
    assert "_seller_config_missing" not in source
    assert "_seller_auth_missing" not in source


def test_connection_auto_selects_only_unambiguous_policy_and_location() -> None:
    source = OAUTH_SOURCE.read_text()
    assert "if len(values) != 1:" in source
    assert "SELLER_CONFIGURATION_SELECTION_REQUIRED" in source
    assert "row.get(\"immediatePay\") is True" in source
    assert "_normalise_location_status(row) == \"ENABLED\"" in source
