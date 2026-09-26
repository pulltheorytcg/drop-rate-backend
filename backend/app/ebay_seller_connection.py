from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from .ebay_sell_client import EbaySellClient
from .settings import Settings


@dataclass(frozen=True, slots=True)
class EbayEffectiveSellerConfig:
    refresh_token: str | None
    payment_policy_id: str | None
    fulfillment_policy_id: str | None
    return_policy_id: str | None
    merchant_location_key: str | None
    notification_destination_id: str | None
    notification_subscription_id: str | None
    connection_id: UUID | None
    owner_id: UUID | None
    status: str | None
    granted_scopes: tuple[str, ...]


def _fernet(settings: Settings) -> Fernet:
    key = (settings.ebay_oauth_encryption_key or "").strip()
    if not key:
        raise RuntimeError("TCG_EBAY_OAUTH_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("TCG_EBAY_OAUTH_ENCRYPTION_KEY is invalid") from exc


def encrypt_refresh_token(settings: Settings, refresh_token: str) -> str:
    token = refresh_token.strip()
    if not token:
        raise ValueError("eBay refresh token is empty")
    return _fernet(settings).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(settings: Settings, ciphertext: str) -> str:
    value = ciphertext.strip()
    if not value:
        raise RuntimeError("Stored eBay refresh token is empty")
    try:
        decoded = _fernet(settings).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Stored eBay refresh token cannot be decrypted") from exc
    if not decoded.strip():
        raise RuntimeError("Stored eBay refresh token decrypted to an empty value")
    return decoded.strip()


async def _load_connection_row(
    pool: Any,
    *,
    owner_id: UUID | None,
) -> dict[str, Any] | None:
    async with pool.acquire() as connection:
        if owner_id is not None:
            row = await connection.fetchrow(
                """
                select id,owner_id,refresh_token_ciphertext,granted_scopes,status,
                       payment_policy_id,fulfillment_policy_id,return_policy_id,
                       merchant_location_key,notification_destination_id,
                       notification_subscription_id
                from tcg.ebay_seller_connections
                where owner_id=$1 and status <> 'DISCONNECTED'
                """,
                owner_id,
            )
            return dict(row) if row else None

        rows = await connection.fetch(
            """
            select id,owner_id,refresh_token_ciphertext,granted_scopes,status,
                   payment_policy_id,fulfillment_policy_id,return_policy_id,
                   merchant_location_key,notification_destination_id,
                   notification_subscription_id
            from tcg.ebay_seller_connections
            where status <> 'DISCONNECTED'
            order by connected_at desc
            limit 2
            """
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise RuntimeError(
                "Multiple active eBay seller connections require explicit owner selection"
            )
        return dict(rows[0])


async def load_effective_seller_config(
    pool: Any,
    settings: Settings,
    *,
    owner_id: UUID | None = None,
) -> EbayEffectiveSellerConfig:
    row = await _load_connection_row(pool, owner_id=owner_id)

    refresh_token = settings.ebay_user_refresh_token
    if not refresh_token and row:
        refresh_token = decrypt_refresh_token(
            settings, str(row["refresh_token_ciphertext"])
        )

    return EbayEffectiveSellerConfig(
        refresh_token=refresh_token,
        payment_policy_id=(
            settings.ebay_payment_policy_id
            or (str(row["payment_policy_id"]) if row and row["payment_policy_id"] else None)
        ),
        fulfillment_policy_id=(
            settings.ebay_fulfillment_policy_id
            or (
                str(row["fulfillment_policy_id"])
                if row and row["fulfillment_policy_id"]
                else None
            )
        ),
        return_policy_id=(
            settings.ebay_return_policy_id
            or (str(row["return_policy_id"]) if row and row["return_policy_id"] else None)
        ),
        merchant_location_key=(
            settings.ebay_merchant_location_key
            or (
                str(row["merchant_location_key"])
                if row and row["merchant_location_key"]
                else None
            )
        ),
        notification_destination_id=(
            str(row["notification_destination_id"])
            if row and row["notification_destination_id"]
            else None
        ),
        notification_subscription_id=(
            str(row["notification_subscription_id"])
            if row and row["notification_subscription_id"]
            else None
        ),
        connection_id=UUID(str(row["id"])) if row else None,
        owner_id=UUID(str(row["owner_id"])) if row else owner_id,
        status=str(row["status"]) if row else None,
        granted_scopes=tuple(row["granted_scopes"] or ()) if row else (),
    )


def client_from_effective_config(
    settings: Settings,
    effective: EbayEffectiveSellerConfig,
) -> EbaySellClient:
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        raise RuntimeError("eBay application credentials are incomplete")
    if not effective.refresh_token:
        raise RuntimeError("eBay seller authorisation is incomplete")
    return EbaySellClient(
        client_id=settings.ebay_client_id,
        client_secret=settings.ebay_client_secret,
        refresh_token=effective.refresh_token,
        marketplace_id=settings.ebay_marketplace_id,
    )


async def seller_client(
    pool: Any,
    settings: Settings,
    *,
    owner_id: UUID | None = None,
) -> tuple[EbaySellClient, EbayEffectiveSellerConfig]:
    effective = await load_effective_seller_config(
        pool, settings, owner_id=owner_id
    )
    return client_from_effective_config(settings, effective), effective
