"""Consent-scoped Seller Hub waitlist → tagged Shopify Customer outbox.

Supabase keeps the consent evidence; Shopify receives only an email and one
audience tag. This worker never changes Shopify's broader email-marketing state.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from .settings import Settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError

logger = logging.getLogger(__name__)

SELLER_HUB_SHOPIFY_TAG = "Drop Rate Seller Hub - Launch List"


async def upsert_tagged_shopify_contact(client: ShopifyAdminClient, email: str) -> str:
    """Upsert by unique email and append our tag without touching any other data."""
    data = await client.graphql(
        query="""
        mutation SellerHubContactUpsert($identifier: CustomerSetIdentifiers,
                                        $input: CustomerSetInput!) {
          customerSet(identifier: $identifier, input: $input) {
            customer { id }
            userErrors { field message }
          }
        }
        """,
        variables={"identifier": {"email": email}, "input": {"email": email}},
    )
    result = data.get("customerSet")
    if not isinstance(result, dict) or result.get("userErrors"):
        raise ShopifyApiError("Shopify customer upsert was rejected")
    customer = result.get("customer")
    customer_gid = customer.get("id") if isinstance(customer, dict) else None
    if not isinstance(customer_gid, str) or not _valid_customer_gid(customer_gid):
        raise ShopifyApiError("Shopify customer upsert returned no valid customer ID")

    # tagsAdd is additive. Passing tags to customerSet would ERASE existing
    # customer tags, including those used for Shopify store marketing.
    data = await client.graphql(
        query="""
        mutation SellerHubContactTag($id: ID!, $tags: [String!]!) {
          tagsAdd(id: $id, tags: $tags) {
            node { id }
            userErrors { message }
          }
        }
        """,
        variables={"id": customer_gid, "tags": [SELLER_HUB_SHOPIFY_TAG]},
    )
    result = data.get("tagsAdd")
    if not isinstance(result, dict) or result.get("userErrors"):
        raise ShopifyApiError("Shopify customer tag addition was rejected")
    tagged = result.get("node")
    if not isinstance(tagged, dict) or tagged.get("id") != customer_gid:
        raise ShopifyApiError("Shopify did not confirm the tagged customer")
    return customer_gid


def _valid_customer_gid(value: str) -> bool:
    prefix = "gid://shopify/Customer/"
    return value.startswith(prefix) and value[len(prefix):].isascii() and value[len(prefix):].isdigit()


async def process_shopify_waitlist_batch(
    pool: asyncpg.Pool, client: ShopifyAdminClient, *, limit: int = 10,
) -> tuple[int, int]:
    """Claim at most ten contacts; safely retry partial/ambiguous Shopify calls."""
    if not 1 <= limit <= 10:
        raise ValueError("Shopify waitlist batch must be between 1 and 10")

    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "select * from tcg_private.claim_seller_hub_shopify_sync($1)", limit,
        )

    successful = 0
    for row in rows:
        customer_gid: str | None = None
        try:
            customer_gid = await upsert_tagged_shopify_contact(client, row["contact_email"])
        except (ShopifyApiError, OSError, TimeoutError) as exc:
            # Provider errors can contain PII. Never log exception text or the
            # customer's email; the retry is durable in the database.
            logger.warning("Seller Hub Shopify contact sync retry: %s", type(exc).__name__)

        async with pool.acquire() as connection:
            acknowledged = await connection.fetchval(
                "select tcg_private.finish_seller_hub_shopify_sync($1, $2, $3)",
                row["waitlist_id"], row["lease_token"], customer_gid,
            )
        if customer_gid and acknowledged:
            successful += 1
        elif not acknowledged:
            logger.warning("Seller Hub Shopify contact acknowledgement had stale lease")

    return len(rows), successful


async def run_shopify_waitlist_sync(pool: asyncpg.Pool, settings: Settings) -> None:
    """Disabled by default until write_customers and data access are approved."""
    if not all((settings.shopify_shop_domain, settings.shopify_client_id, settings.shopify_client_secret)):
        logger.error("Seller Hub Shopify sync enabled without Shopify credentials; worker not started")
        return

    client = ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )
    while True:
        try:
            claimed, synced = await process_shopify_waitlist_batch(pool, client)
            if claimed:
                logger.info("Seller Hub Shopify contact sync processed=%d successful=%d", claimed, synced)
            await asyncio.sleep(2 if claimed == 10 else 60)
        except asyncio.CancelledError:
            raise
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
            logger.warning("Seller Hub Shopify contact sync unavailable: %s", type(exc).__name__)
            await asyncio.sleep(60)
