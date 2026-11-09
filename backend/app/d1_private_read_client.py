"""INACTIVE signed FastAPI -> private Cloudflare D1 owner-inventory reader.

NO production route calls this. Current require_user, PostgreSQL RLS and
Supabase Auth remain authoritative. A future FastAPI route must pass only
user.user_id derived from a verified authenticated session (NOT a client
owner_id, query argument or unverified JWT role).

Never accept arbitrary SQL, D1 credentials, a caller-chosen source generation,
owner_id, display name, external session token, or browser-supplied secret.
This is a narrow HMAC-authenticated backend-to-backend read transport only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx

_PATH = "/internal/v1/owner-inventory"
_SECRET = re.compile(r"[0-9a-f]{64}\Z")
MAX_PAGE = 50


class D1PrivateReadGuard(ValueError):
    """Private read refused; error never contains source row/user/secret values."""


@dataclass(frozen=True, slots=True)
class OwnerInventoryPage:
    owner_id: UUID
    owner_type: str
    items: tuple[dict, ...]
    next_cursor: UUID | None


def _canonical_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise D1PrivateReadGuard("Invalid private UUID")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise D1PrivateReadGuard("Invalid private UUID") from None
    if str(parsed) != value:
        raise D1PrivateReadGuard("Noncanonical private UUID")
    return parsed


def validate_internal_endpoint(url: str) -> str:
    """Only the approved Cloudflare Worker/custom Drop Rate HTTPS origin.

    This URL is injected by trusted backend configuration, never a client.
    A generic HTTPS/hostname regex alone is insufficient: shortened decimal
    loopback names such as 127.1 are not recognised by ipaddress.ip_address.
    """
    if not isinstance(url, str) or len(url) > 1024:
        raise D1PrivateReadGuard("Invalid private Cloudflare endpoint")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise D1PrivateReadGuard("Invalid private Cloudflare endpoint") from None
    if (parsed.scheme != "https" or not host or parsed.path != _PATH
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or parsed.query or parsed.fragment
            or host.lower() in {"localhost", "0.0.0.0", "127.0.0.1"}
            or not re.fullmatch(r"[a-z0-9.-]{3,253}", host.lower())
            or host.endswith(".local")):
        raise D1PrivateReadGuard("Private endpoint must be a fixed HTTPS host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise D1PrivateReadGuard("IP-literal Cloudflare endpoint not allowed")
    # Explicit DNS families, not arbitrary HTTPS destinations. Rejects
    # shortened/decimal loopback names, DNS rebinding helper domains, and
    # accidental internal endpoints without relying on DNS resolution.
    hostname = host.lower()
    trusted_worker = hostname.endswith(".workers.dev")
    trusted_drop_rate = hostname.endswith(".droprate.co.uk")
    if not (trusted_worker or trusted_drop_rate):
        raise D1PrivateReadGuard("Unapproved private Cloudflare endpoint hostname")
    return url


def signed_owner_inventory_request(*, endpoint: str, secret_hex: str,
                                   verified_legacy_user_id: UUID,
                                   cursor: UUID | None = None,
                                   limit: int = 50,
                                   now: datetime | None = None,
                                   ) -> tuple[str, bytes, dict[str, str]]:
    """Produce deterministic wire data with an exact SHA-256 HMAC transport key."""
    validate_internal_endpoint(endpoint)
    if not isinstance(secret_hex, str) or _SECRET.fullmatch(secret_hex) is None:
        raise D1PrivateReadGuard("Invalid private Worker HMAC configuration")
    if type(verified_legacy_user_id) is not UUID:
        raise D1PrivateReadGuard("Verified internal user UUID required")
    if cursor is not None and type(cursor) is not UUID:
        raise D1PrivateReadGuard("Invalid private pagination cursor")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise D1PrivateReadGuard("Page size outside bounded contract")
    instant = now or datetime.now(timezone.utc)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise D1PrivateReadGuard("UTC timestamp required")
    timestamp = str(int(instant.timestamp()))
    body = json.dumps({
        "legacy_user_id": str(verified_legacy_user_id),
        "cursor": str(cursor) if cursor else None,
        "limit": limit,
    }, separators=(",",":"), sort_keys=True).encode("utf-8")
    envelope = ("POST\n" + _PATH + "\n" + timestamp + "\n").encode() + body
    signature = hmac.new(bytes.fromhex(secret_hex), envelope, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-DR-Timestamp": timestamp,
        "X-DR-Signature": "sha256=" + signature,
    }
    return endpoint, body, headers


def validate_private_inventory_response(data: object, *,
                                        page_limit: int,
                                        cursor: UUID | None) -> OwnerInventoryPage:
    """Do not accidentally expose corrupt/mixed-owner D1 data in FastAPI."""
    if not isinstance(data, dict) or set(data) != {
        "status", "owner_id", "owner_type", "founder_hq_allowed",
        "business_allowed", "inventory", "next_cursor",
    }:
        raise D1PrivateReadGuard("Unexpected private D1 response")
    if (data["status"] != "VERIFIED_READ_ONLY"
            or data["founder_hq_allowed"] is not False
            or data["business_allowed"] is not False
            or data["owner_type"] not in ("FOUNDER", "CONSIGNOR")):
        raise D1PrivateReadGuard("Unapproved private authorization response")
    owner_id = _canonical_uuid(data["owner_id"])
    rows = data["inventory"]
    if not isinstance(rows, list) or len(rows) > page_limit:
        raise D1PrivateReadGuard("Private D1 response exceeds page bounds")
    previous = str(cursor) if cursor else ""
    for entry in rows:
        if (not isinstance(entry, dict)
                or set(entry) != {
                    "id", "inventory_code", "catalogue_id", "owner_id",
                    "condition", "grade", "language", "status", "version",
                    "acquisition_cost_minor", "market_value_minor",
                    "store_price_minor", "currency",
                } or entry["owner_id"] != str(owner_id)):
            raise D1PrivateReadGuard("Private inventory owner/columns mismatch")
        row_id = _canonical_uuid(entry["id"])
        if (str(row_id) <= previous or entry["currency"] != "GBP"
                or type(entry["version"]) is not int
                or entry["version"] < 1
                or not isinstance(entry["inventory_code"], str)
                or not entry["inventory_code"]):
            raise D1PrivateReadGuard("Invalid private inventory identity/order")
        for field in ("acquisition_cost_minor", "market_value_minor", "store_price_minor"):
            number = entry[field]
            if number is not None and (
                type(number) is not int or not 0 <= number <= 9_000_000_000_000_000
            ):
                raise D1PrivateReadGuard("Invalid private inventory pennies")
        previous = str(row_id)
    next_value = data["next_cursor"]
    if next_value is None:
        if len(rows) == page_limit and page_limit > 0:
            # The Worker signals possible further pages whenever full.
            raise D1PrivateReadGuard("Full page lost its continuation cursor")
        next_cursor = None
    else:
        next_cursor = _canonical_uuid(next_value)
        if len(rows) != page_limit or str(next_cursor) != previous:
            raise D1PrivateReadGuard("Unexpected private pagination cursor")
    return OwnerInventoryPage(
        owner_id=owner_id, owner_type=data["owner_type"],
        items=tuple(rows), next_cursor=next_cursor,
    )


async def fetch_verified_owner_inventory(*, client: httpx.AsyncClient,
                                         endpoint: str, secret_hex: str,
                                         verified_legacy_user_id: UUID,
                                         cursor: UUID | None = None,
                                         limit: int = 50,
                                         now: datetime | None = None,
                                         ) -> OwnerInventoryPage:
    """One HMAC-protected, no-redirect request; never automatic silent fallback."""
    url, body, headers = signed_owner_inventory_request(
        endpoint=endpoint,secret_hex=secret_hex,
        verified_legacy_user_id=verified_legacy_user_id,
        cursor=cursor,limit=limit,now=now,
    )
    try:
        response = await client.post(url,content=body,headers=headers,
                                     follow_redirects=False,timeout=10.0)
        if response.status_code != 200:
            raise D1PrivateReadGuard("Verified private D1 owner read rejected")
        if len(response.content) > 100_000:
            raise D1PrivateReadGuard("Oversized private D1 response")
        page=response.json()
    except D1PrivateReadGuard:
        raise
    except (httpx.HTTPError,ValueError,UnicodeError,TypeError):
        raise D1PrivateReadGuard("Private D1 transport or response unavailable") from None
    return validate_private_inventory_response(page,page_limit=limit,cursor=cursor)
