from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

# Deployment marker: eBay Production RuName configured.


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


_SHOPIFY_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$", re.IGNORECASE)
_SHOPIFY_API_VERSION_RE = re.compile(r"^\d{4}-(?:01|04|07|10)$")


def _shopify_domain(name: str) -> str | None:
    value = _optional(name)
    if value is None:
        return None
    normalized = value.casefold()
    if not _SHOPIFY_DOMAIN_RE.fullmatch(normalized):
        raise RuntimeError(
            f"{name} must be a canonical *.myshopify.com domain without a scheme or path"
        )
    return normalized


def _shopify_api_version(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not _SHOPIFY_API_VERSION_RE.fullmatch(value):
        raise RuntimeError(f"{name} must use Shopify YYYY-MM quarterly version format")
    return value


def _https_endpoint(name: str) -> str | None:
    value = _optional(name)
    if value is None:
        return None
    if not value.startswith("https://"):
        raise RuntimeError(f"{name} must be an https:// URL")
    if "?" in value or "#" in value:
        raise RuntimeError(f"{name} must not include query parameters or fragments")
    return value.rstrip("/")


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    auth_issuer: str
    auth_audience: str
    jwks_url: str
    supabase_url: str
    supabase_publishable_key: str
    environment: str
    db_pool_min: int
    db_pool_max: int
    parse_api_key: str | None
    ebay_client_id: str | None
    ebay_client_secret: str | None
    ebay_marketplace_id: str
    public_app_url: str | None = None
    resend_api_key: str | None = None
    seller_invite_from_email: str | None = None
    seller_invite_reply_to: str | None = None
    resend_webhook_secret: str | None = None
    trawl_api_key: str | None = None
    ebay_deletion_verification_token: str | None = None
    ebay_deletion_endpoint: str | None = None
    ebay_user_refresh_token: str | None = None
    ebay_runame: str | None = None
    ebay_oauth_callback_endpoint: str | None = None
    ebay_oauth_encryption_key: str | None = None
    ebay_payment_policy_id: str | None = None
    ebay_return_policy_id: str | None = None
    ebay_fulfillment_policy_id: str | None = None
    ebay_merchant_location_key: str | None = None
    ebay_notification_endpoint: str | None = None
    ebay_notification_verification_token: str | None = None
    ebay_shared_store_owner_id: str | None = None
    shopify_seller_sync_enabled: bool = False
    ebay_seller_sync_enabled: bool = False
    ebay_publish_enabled: bool = False
    ebay_price_markup_bps: int = 0
    ebay_origin_postcode: str | None = None
    ebay_alert_email: str | None = None
    ebay_standard_shipping_minor: int = 499
    ebay_handling_days: int = 2
    ebay_shipping_carrier_code: str = "RoyalMail"
    ebay_shipping_service_code: str = "UK_RoyalMailTracked"
    market_ingestion_enabled: bool = False
    shopify_shop_domain: str | None = None
    shopify_client_id: str | None = None
    shopify_client_secret: str | None = None
    shopify_api_version: str = "2026-07"
    shopify_webhook_endpoint: str | None = None
    shopify_location_gid: str | None = None
    shopify_publication_gid: str | None = None
    shopify_test_publish_enabled: bool = False
    shopify_publish_enabled: bool = False
    automation_command_secret: str | None = None
    editorial_storefront_origin: str | None = None
    shopify_catalogue_bootstrap_enabled: bool = False
    shopify_catalogue_bootstrap_actor_user_id: str | None = None
    shopify_linked_draft_reconciliation_enabled: bool = False
    shopify_linked_draft_reconciliation_apply: bool = False
    shopify_linked_draft_reconciliation_batch_id: str | None = None
    shopify_linked_draft_language_map_json: str | None = None
    shopify_linked_draft_reconciliation_limit: int = 500
    media_physical_photo_threshold_minor: int = 5_000
    tcggraph_api_key: str | None = None
    tcggraph_max_concurrency: int = 8
    cardtrader_api_token: str | None = None
    cardtrader_max_concurrency: int = 8
    psa_public_api_token: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_connect_country: str = "GB"
    stripe_connect_return_url: str | None = None
    stripe_connect_refresh_url: str | None = None
    stripe_connect_live_enabled: bool = False
    stripe_payout_execution_enabled: bool = False
    openai_api_key: str | None = None
    recognition_model: str = "gpt-5.6-sol"
    recognition_exact_threshold_bps: int = 8200
    recognition_min_margin_bps: int = 1000
    recognition_high_value_review_minor: int = 50_000
    recognition_max_image_bytes: int = 8_000_000

    @classmethod
    def from_env(cls) -> "Settings":
        issuer = _required("TCG_AUTH_ISSUER").rstrip("/")
        pool_min = _positive_int("TCG_DB_POOL_MIN", 1)
        pool_max = _positive_int("TCG_DB_POOL_MAX", 5)
        if pool_min > pool_max:
            raise RuntimeError("TCG_DB_POOL_MIN cannot exceed TCG_DB_POOL_MAX")
        if not issuer.endswith("/auth/v1"):
            raise RuntimeError("TCG_AUTH_ISSUER must end with /auth/v1")
        return cls(
            database_url=_required("TCG_DATABASE_URL"),
            auth_issuer=issuer,
            auth_audience=_required("TCG_AUTH_AUDIENCE"),
            jwks_url=os.getenv("TCG_JWKS_URL", f"{issuer}/.well-known/jwks.json").strip(),
            supabase_url=issuer.removesuffix("/auth/v1"),
            supabase_publishable_key=_required("TCG_SUPABASE_PUBLISHABLE_KEY"),
            environment=os.getenv("TCG_ENVIRONMENT", "development").strip(),
            db_pool_min=pool_min,
            db_pool_max=pool_max,
            public_app_url=_https_endpoint("TCG_PUBLIC_APP_URL"),
            resend_api_key=_optional("TCG_RESEND_API_KEY"),
            seller_invite_from_email=_optional("TCG_SELLER_INVITE_FROM_EMAIL"),
            seller_invite_reply_to=_optional("TCG_SELLER_INVITE_REPLY_TO"),
            resend_webhook_secret=_optional("TCG_RESEND_WEBHOOK_SECRET"),
            parse_api_key=_optional("TCG_PARSE_API_KEY"),
            ebay_client_id=_optional("TCG_EBAY_CLIENT_ID"),
            ebay_client_secret=_optional("TCG_EBAY_CLIENT_SECRET"),
            ebay_marketplace_id=os.getenv("TCG_EBAY_MARKETPLACE_ID", "EBAY_GB").strip() or "EBAY_GB",
            trawl_api_key=_optional("TCG_TRAWL_API_KEY"),
            ebay_deletion_verification_token=_optional("TCG_EBAY_DELETION_VERIFICATION_TOKEN"),
            ebay_deletion_endpoint=_optional("TCG_EBAY_DELETION_ENDPOINT"),
            ebay_user_refresh_token=_optional("TCG_EBAY_USER_REFRESH_TOKEN"),
            ebay_runame=_optional("TCG_EBAY_RUNAME"),
            ebay_oauth_callback_endpoint=_https_endpoint("TCG_EBAY_OAUTH_CALLBACK_ENDPOINT"),
            ebay_oauth_encryption_key=_optional("TCG_EBAY_OAUTH_ENCRYPTION_KEY"),
            ebay_payment_policy_id=_optional("TCG_EBAY_PAYMENT_POLICY_ID"),
            ebay_return_policy_id=_optional("TCG_EBAY_RETURN_POLICY_ID"),
            ebay_fulfillment_policy_id=_optional("TCG_EBAY_FULFILLMENT_POLICY_ID"),
            ebay_merchant_location_key=_optional("TCG_EBAY_MERCHANT_LOCATION_KEY"),
            ebay_notification_endpoint=_https_endpoint("TCG_EBAY_NOTIFICATION_ENDPOINT"),
            ebay_notification_verification_token=_optional(
                "TCG_EBAY_NOTIFICATION_VERIFICATION_TOKEN"
            ),
            ebay_shared_store_owner_id=_optional("TCG_EBAY_SHARED_STORE_OWNER_ID"),
            shopify_seller_sync_enabled=_boolean("TCG_SHOPIFY_SELLER_SYNC_ENABLED", False),
            ebay_seller_sync_enabled=_boolean("TCG_EBAY_SELLER_SYNC_ENABLED", False),
            ebay_publish_enabled=_boolean("TCG_EBAY_PUBLISH_ENABLED", False),
            ebay_price_markup_bps=_bounded_int(
                "TCG_EBAY_PRICE_MARKUP_BPS", 0, minimum=0, maximum=10000
            ),
            ebay_origin_postcode=_optional("TCG_EBAY_ORIGIN_POSTCODE"),
            ebay_alert_email=_optional("TCG_EBAY_ALERT_EMAIL"),
            ebay_standard_shipping_minor=_bounded_int(
                "TCG_EBAY_STANDARD_SHIPPING_MINOR", 499, minimum=0, maximum=50000
            ),
            ebay_handling_days=_bounded_int(
                "TCG_EBAY_HANDLING_DAYS", 2, minimum=0, maximum=30
            ),
            ebay_shipping_carrier_code=(
                os.getenv("TCG_EBAY_SHIPPING_CARRIER_CODE", "RoyalMail").strip()
                or "RoyalMail"
            ),
            ebay_shipping_service_code=(
                os.getenv("TCG_EBAY_SHIPPING_SERVICE_CODE", "UK_RoyalMailTracked").strip()
                or "UK_RoyalMailTracked"
            ),
            market_ingestion_enabled=_boolean("TCG_MARKET_INGESTION_ENABLED", False),
            shopify_shop_domain=_shopify_domain("TCG_SHOPIFY_SHOP_DOMAIN"),
            shopify_client_id=_optional("TCG_SHOPIFY_CLIENT_ID"),
            shopify_client_secret=_optional("TCG_SHOPIFY_CLIENT_SECRET"),
            shopify_api_version=_shopify_api_version("TCG_SHOPIFY_API_VERSION", "2026-07"),
            shopify_webhook_endpoint=_https_endpoint("TCG_SHOPIFY_WEBHOOK_ENDPOINT"),
            shopify_location_gid=_optional("TCG_SHOPIFY_LOCATION_GID"),
            shopify_publication_gid=_optional("TCG_SHOPIFY_PUBLICATION_GID"),
            shopify_test_publish_enabled=_boolean("TCG_SHOPIFY_TEST_PUBLISH_ENABLED", False),
            shopify_publish_enabled=_boolean("TCG_SHOPIFY_PUBLISH_ENABLED", False),
            automation_command_secret=_optional("TCG_AUTOMATION_COMMAND_SECRET"),
            editorial_storefront_origin=_optional("TCG_EDITORIAL_STOREFRONT_ORIGIN"),
            shopify_catalogue_bootstrap_enabled=_boolean(
                "TCG_SHOPIFY_CATALOGUE_BOOTSTRAP_ENABLED", False
            ),
            shopify_catalogue_bootstrap_actor_user_id=_optional(
                "TCG_SHOPIFY_CATALOGUE_BOOTSTRAP_ACTOR_USER_ID"
            ),
            shopify_linked_draft_reconciliation_enabled=_boolean(
                "TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_ENABLED", False
            ),
            shopify_linked_draft_reconciliation_apply=_boolean(
                "TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_APPLY", False
            ),
            shopify_linked_draft_reconciliation_batch_id=_optional(
                "TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_BATCH_ID"
            ),
            shopify_linked_draft_language_map_json=_optional(
                "TCG_SHOPIFY_LINKED_DRAFT_LANGUAGE_MAP_JSON"
            ),
            shopify_linked_draft_reconciliation_limit=_bounded_int(
                "TCG_SHOPIFY_LINKED_DRAFT_RECONCILIATION_LIMIT",
                500,
                minimum=1,
                maximum=5000,
            ),
            media_physical_photo_threshold_minor=_bounded_int(
                "TCG_MEDIA_PHYSICAL_PHOTO_THRESHOLD_MINOR",
                5_000,
                minimum=100,
                maximum=10_000_000,
            ),
            tcggraph_api_key=_optional("TCG_TCGGRAPH_API_KEY"),
            tcggraph_max_concurrency=_bounded_int(
                "TCG_TCGGRAPH_MAX_CONCURRENCY",
                8,
                minimum=1,
                maximum=20,
            ),
            cardtrader_api_token=_optional("TCG_CARDTRADER_API_TOKEN"),
            cardtrader_max_concurrency=_bounded_int(
                "TCG_CARDTRADER_MAX_CONCURRENCY",
                8,
                minimum=1,
                maximum=20,
            ),
            psa_public_api_token=_optional("TCG_PSA_PUBLIC_API_TOKEN"),
            stripe_secret_key=_optional("TCG_STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_optional("TCG_STRIPE_WEBHOOK_SECRET"),
            stripe_connect_country=(
                os.getenv("TCG_STRIPE_CONNECT_COUNTRY", "GB").strip().upper() or "GB"
            ),
            stripe_connect_return_url=_https_endpoint("TCG_STRIPE_CONNECT_RETURN_URL"),
            stripe_connect_refresh_url=_https_endpoint("TCG_STRIPE_CONNECT_REFRESH_URL"),
            stripe_connect_live_enabled=_boolean("TCG_STRIPE_CONNECT_LIVE_ENABLED", False),
            stripe_payout_execution_enabled=_boolean(
                "TCG_STRIPE_PAYOUT_EXECUTION_ENABLED", False
            ),
            openai_api_key=_optional("TCG_OPENAI_API_KEY"),
            recognition_model=(
                os.getenv("TCG_RECOGNITION_MODEL", "gpt-5.6-sol").strip()
                or "gpt-5.6-sol"
            ),
            recognition_exact_threshold_bps=_bounded_int(
                "TCG_RECOGNITION_EXACT_THRESHOLD_BPS",
                8200,
                minimum=5000,
                maximum=10000,
            ),
            recognition_min_margin_bps=_bounded_int(
                "TCG_RECOGNITION_MIN_MARGIN_BPS",
                1000,
                minimum=0,
                maximum=5000,
            ),
            recognition_high_value_review_minor=_bounded_int(
                "TCG_RECOGNITION_HIGH_VALUE_REVIEW_MINOR",
                50_000,
                minimum=100,
                maximum=100_000_000,
            ),
            recognition_max_image_bytes=_bounded_int(
                "TCG_RECOGNITION_MAX_IMAGE_BYTES",
                8_000_000,
                minimum=100_000,
                maximum=20_000_000,
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
