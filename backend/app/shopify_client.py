from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx


class ShopifyApiError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


class ShopifyMediaScopeRequired(ShopifyApiError):
    def __init__(self) -> None:
        super().__init__(
            "Shopify app requires write_files to attach new approved media",
            status_code=403,
        )


class ShopifyAdminClient:
    """Server-side Shopify GraphQL Admin API client using client credentials.

    The app exchanges its Client ID + Client Secret for a short-lived Admin API
    token, caches it in memory, and refreshes it before expiry. Credentials and
    access tokens never leave the server process.
    """

    def __init__(
        self,
        *,
        shop_domain: str,
        client_id: str,
        client_secret: str,
        api_version: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        domain = shop_domain.strip().casefold()
        app_id = client_id.strip()
        app_secret = client_secret.strip()
        version = api_version.strip()

        if not domain.endswith(".myshopify.com"):
            raise ValueError("A canonical Shopify myshopify.com domain is required")
        if not app_id:
            raise ValueError("Shopify Client ID is required")
        if not app_secret:
            raise ValueError("Shopify Client Secret is required")
        if not version:
            raise ValueError("Shopify API version is required")

        self._shop_domain = domain
        self._client_id = app_id
        self._client_secret = app_secret
        self._api_version = version
        self._timeout = timeout_seconds
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def shop_domain(self) -> str:
        return self._shop_domain

    @property
    def api_version(self) -> str:
        return self._api_version

    async def _mint_access_token(self) -> tuple[str, int]:
        url = f"https://{self._shop_domain}/admin/oauth/access_token"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
        except httpx.TimeoutException as exc:
            raise ShopifyApiError(
                "Shopify OAuth token request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ShopifyApiError(
                "Shopify OAuth token request failed",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise ShopifyApiError(
                "Shopify OAuth rejected the app credentials or store access",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyApiError("Shopify OAuth returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify OAuth returned an invalid response shape")

        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(token, str) or not token.strip():
            raise ShopifyApiError("Shopify OAuth response is missing an access token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise ShopifyApiError("Shopify OAuth response has an invalid expiry")
        return token.strip(), expires_in

    async def access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._token_expires_at:
                return self._access_token

            token, expires_in = await self._mint_access_token()
            self._access_token = token
            # Shopify client-credentials tokens last 24 hours. Refresh at least
            # five minutes before expiry so a token never expires mid-request.
            margin = min(300, max(30, expires_in // 20))
            self._token_expires_at = time.monotonic() + max(1, expires_in - margin)
            return token

    async def graphql(
        self,
        *,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("Shopify GraphQL query is required")

        token = await self.access_token()
        url = (
            f"https://{self._shop_domain}/admin/api/"
            f"{self._api_version}/graphql.json"
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "X-Shopify-Access-Token": token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={"query": query, "variables": variables or {}},
                )
        except httpx.TimeoutException as exc:
            raise ShopifyApiError(
                "Shopify Admin API request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ShopifyApiError(
                "Shopify Admin API request failed",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise ShopifyApiError(
                "Shopify Admin API rejected the request",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyApiError("Shopify Admin API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify Admin API returned an invalid response shape")
        if payload.get("errors"):
            raise ShopifyApiError("Shopify Admin API returned GraphQL errors")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopifyApiError("Shopify Admin API response is missing data")
        return data

    async def probe_shop(self) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            query DropRateShopProbe {
              shop {
                id
                name
                myshopifyDomain
                currencyCode
              }
            }
            """
        )
        shop = data.get("shop")
        if not isinstance(shop, dict):
            raise ShopifyApiError("Shopify shop probe returned an invalid response")
        return {
            "id": shop.get("id"),
            "name": shop.get("name"),
            "myshopify_domain": shop.get("myshopifyDomain"),
            "currency_code": shop.get("currencyCode"),
        }


    async def get_order_transactions(self, order_id: str) -> list[dict[str, Any]]:
        data = await self.graphql(
            query="""
            query DropRateOrderTransactions($id: ID!) {
              order(id: $id) {
                id
                transactions(first: 100) {
                  id
                  kind
                  status
                  processedAt
                  fees {
                    id
                    type
                    amount { amount currencyCode }
                  }
                }
              }
            }
            """,
            variables={"id": order_id},
        )
        order = data.get("order")
        if not isinstance(order, dict):
            raise ShopifyApiError("Shopify order transaction query returned no order")
        transactions = order.get("transactions")
        if not isinstance(transactions, list):
            raise ShopifyApiError(
                "Shopify order transaction query returned an invalid response"
            )
        result: list[dict[str, Any]] = []
        for transaction in transactions:
            if not isinstance(transaction, dict):
                raise ShopifyApiError(
                    "Shopify order transaction query returned an invalid transaction"
                )
            fees = transaction.get("fees")
            if not isinstance(fees, list):
                raise ShopifyApiError(
                    "Shopify order transaction query returned invalid fees"
                )
            result.append(transaction)
        return result


    async def list_orders_for_reconciliation(
        self,
        *,
        created_at_gte: datetime,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        if created_at_gte.tzinfo is None or created_at_gte.utcoffset() is None:
            raise ValueError("created_at_gte must be timezone-aware")
        if max_pages < 1 or max_pages > 100:
            raise ValueError("max_pages must be between 1 and 100")

        timestamp = (
            created_at_gte.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        search_query = f"created_at:>='{timestamp}'"
        cursor: str | None = None
        orders: list[dict[str, Any]] = []

        for _page in range(max_pages):
            data = await self.graphql(
                query="""
                query DropRateOrderReconciliation(
                  $first: Int!,
                  $after: String,
                  $query: String!
                ) {
                  orders(
                    first: $first,
                    after: $after,
                    query: $query,
                    sortKey: CREATED_AT
                  ) {
                    nodes {
                      id
                      name
                      createdAt
                      cancelledAt
                      displayFinancialStatus
                    }
                    pageInfo {
                      hasNextPage
                      endCursor
                    }
                  }
                }
                """,
                variables={
                    "first": 100,
                    "after": cursor,
                    "query": search_query,
                },
            )
            connection = data.get("orders")
            if not isinstance(connection, dict):
                raise ShopifyApiError(
                    "Shopify order reconciliation query returned an invalid response"
                )
            nodes = connection.get("nodes")
            if not isinstance(nodes, list):
                raise ShopifyApiError(
                    "Shopify order reconciliation query is missing nodes"
                )
            for node in nodes:
                if not isinstance(node, dict):
                    raise ShopifyApiError(
                        "Shopify order reconciliation query returned an invalid order"
                    )
                gid = str(node.get("id") or "").strip()
                prefix = "gid://shopify/Order/"
                source_reference = gid.removeprefix(prefix)
                if (
                    not gid.startswith(prefix)
                    or not source_reference.isdigit()
                    or len(source_reference) > 32
                ):
                    raise ShopifyApiError(
                        "Shopify order reconciliation returned an invalid order ID"
                    )
                created_at = str(node.get("createdAt") or "").strip()
                if not created_at:
                    raise ShopifyApiError(
                        "Shopify order reconciliation returned an order without createdAt"
                    )
                orders.append(
                    {
                        "source_reference": source_reference,
                        "order_number": str(node.get("name") or "").strip() or None,
                        "created_at": created_at,
                        "cancelled_at": (
                            str(node.get("cancelledAt") or "").strip() or None
                        ),
                        "financial_status": (
                            str(node.get("displayFinancialStatus") or "").strip() or None
                        ),
                    }
                )

            page_info = connection.get("pageInfo")
            if not isinstance(page_info, dict):
                raise ShopifyApiError(
                    "Shopify order reconciliation query is missing pageInfo"
                )
            if not page_info.get("hasNextPage"):
                return orders
            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise ShopifyApiError(
                    "Shopify order reconciliation pagination is invalid"
                )

        raise ShopifyApiError(
            "Shopify order reconciliation exceeded the pagination safety limit"
        )


    async def list_webhook_subscriptions(self) -> list[dict[str, Any]]:
        subscriptions: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            data = await self.graphql(
                query="""
                query DropRateWebhookSubscriptions($first: Int!, $after: String) {
                  webhookSubscriptions(first: $first, after: $after) {
                    nodes {
                      id
                      topic
                      uri
                    }
                    pageInfo {
                      hasNextPage
                      endCursor
                    }
                  }
                }
                """,
                variables={"first": 100, "after": cursor},
            )
            connection = data.get("webhookSubscriptions")
            if not isinstance(connection, dict):
                raise ShopifyApiError(
                    "Shopify webhook subscription query returned an invalid response"
                )
            nodes = connection.get("nodes")
            if not isinstance(nodes, list):
                raise ShopifyApiError(
                    "Shopify webhook subscription query is missing nodes"
                )
            for node in nodes:
                if isinstance(node, dict):
                    subscriptions.append(
                        {
                            "id": node.get("id"),
                            "topic": node.get("topic"),
                            "uri": node.get("uri"),
                        }
                    )
            page_info = connection.get("pageInfo")
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise ShopifyApiError(
                    "Shopify webhook subscription pagination is invalid"
                )
        return subscriptions

    async def create_webhook_subscription(
        self,
        *,
        topic: str,
        uri: str,
    ) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            mutation DropRateWebhookSubscriptionCreate(
              $topic: WebhookSubscriptionTopic!,
              $webhookSubscription: WebhookSubscriptionInput!
            ) {
              webhookSubscriptionCreate(
                topic: $topic,
                webhookSubscription: $webhookSubscription
              ) {
                webhookSubscription {
                  id
                  topic
                  uri
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """,
            variables={
                "topic": topic,
                "webhookSubscription": {"uri": uri},
            },
        )
        payload = data.get("webhookSubscriptionCreate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify webhook subscription mutation returned an invalid response"
            )
        user_errors = payload.get("userErrors")
        if isinstance(user_errors, list) and user_errors:
            messages = [
                str(error.get("message") or "").strip()
                for error in user_errors
                if isinstance(error, dict)
            ]
            detail = "; ".join(message for message in messages if message)
            raise ShopifyApiError(
                detail or "Shopify rejected the webhook subscription"
            )
        subscription = payload.get("webhookSubscription")
        if not isinstance(subscription, dict):
            raise ShopifyApiError(
                "Shopify did not return the created webhook subscription"
            )
        return {
            "id": subscription.get("id"),
            "topic": subscription.get("topic"),
            "uri": subscription.get("uri"),
        }


    async def list_collections_by_title(self) -> dict[str, dict[str, Any]]:
        collections: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        while True:
            data = await self.graphql(
                query="""
                query DropRateCollections($first: Int!, $after: String) {
                  collections(first: $first, after: $after) {
                    nodes { id title handle ruleSet { appliedDisjunctively } }
                    pageInfo { hasNextPage endCursor }
                  }
                }
                """,
                variables={"first": 100, "after": cursor},
            )
            connection = data.get("collections")
            if not isinstance(connection, dict):
                raise ShopifyApiError(
                    "Shopify collection query returned an invalid response"
                )
            nodes = connection.get("nodes")
            if not isinstance(nodes, list):
                raise ShopifyApiError(
                    "Shopify collection query is missing nodes"
                )
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                title = str(node.get("title") or "").strip()
                collection_id = str(node.get("id") or "").strip()
                if title and collection_id:
                    collections[title] = {
                        "id": collection_id,
                        "title": title,
                        "handle": node.get("handle"),
                        "automated": isinstance(node.get("ruleSet"), dict),
                    }
            page_info = connection.get("pageInfo")
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise ShopifyApiError(
                    "Shopify collection pagination is invalid"
                )
        return collections

    async def list_collection_titles(self) -> set[str]:
        return set((await self.list_collections_by_title()).keys())

    async def add_product_to_collection(
        self,
        *,
        collection_id: str,
        product_id: str,
    ) -> None:
        data = await self.graphql(
            query="""
            mutation DropRateCollectionAddProducts(
              $id: ID!,
              $productIds: [ID!]!
            ) {
              collectionAddProducts(id: $id, productIds: $productIds) {
                collection { id title }
                userErrors { field message }
              }
            }
            """,
            variables={"id": collection_id, "productIds": [product_id]},
        )
        payload = data.get("collectionAddProducts")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify collection assignment returned an invalid response"
            )
        errors = payload.get("userErrors")
        if isinstance(errors, list) and errors:
            messages = " ".join(
                str(error.get("message") or "")
                for error in errors
                if isinstance(error, dict)
            ).casefold()
            if "already" not in messages:
                self._raise_user_errors(
                    payload,
                    "Shopify rejected collection assignment",
                )

    async def create_file_from_url(
        self,
        *,
        source_url: str,
        alt_text: str,
    ) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            mutation DropRateFileCreate($files: [FileCreateInput!]!) {
              fileCreate(files: $files) {
                files { id fileStatus alt image { url } }
                userErrors { field message }
              }
            }
            """,
            variables={
                "files": [{
                    "originalSource": source_url,
                    "alt": alt_text,
                    "contentType": "IMAGE",
                }]
            },
        )
        payload = data.get("fileCreate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify file creation returned an invalid response"
            )
        self._raise_user_errors(payload, "Shopify rejected file creation")
        files = payload.get("files")
        if (
            not isinstance(files, list)
            or len(files) != 1
            or not isinstance(files[0], dict)
        ):
            raise ShopifyApiError(
                "Shopify did not return exactly one created file"
            )
        return files[0]

    async def get_file(self, file_id: str) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            query DropRateFile($id: ID!) {
              node(id: $id) {
                ... on MediaImage {
                  id
                  fileStatus
                  alt
                  image { url }
                }
              }
            }
            """,
            variables={"id": file_id},
        )
        node = data.get("node")
        if not isinstance(node, dict) or not node.get("id"):
            raise ShopifyApiError("Shopify file could not be found")
        return node

    async def attach_file_to_product(
        self,
        *,
        file_id: str,
        product_id: str,
    ) -> None:
        # A previous attempt or authorized merchant may already have attached
        # the exact approved file. Read through the product permission first;
        # do not require a new file write for an association that already exists.
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            data = await self.graphql(
                query="""
                query DropRateProductMedia($id: ID!, $after: String) {
                  product(id: $id) {
                    id
                    media(first: 50, after: $after) {
                      nodes { id }
                      pageInfo { hasNextPage endCursor }
                    }
                  }
                }
                """,
                variables={"id": product_id, "after": cursor},
            )
            product = data.get("product")
            media = product.get("media") if isinstance(product, dict) else None
            if (
                not isinstance(product, dict)
                or product.get("id") != product_id
                or not isinstance(media, dict)
                or not isinstance(media.get("nodes"), list)
                or not isinstance(media.get("pageInfo"), dict)
            ):
                raise ShopifyApiError("Shopify product media readback is invalid")
            if any(isinstance(node, dict) and node.get("id") == file_id
                   for node in media["nodes"]):
                return
            if not media["pageInfo"].get("hasNextPage"):
                break
            cursor = media["pageInfo"].get("endCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ShopifyApiError("Shopify product media pagination is invalid")
            seen_cursors.add(cursor)
        if "write_files" not in await self.access_scopes():
            raise ShopifyMediaScopeRequired()
        data = await self.graphql(
            query="""
            mutation DropRateFileAttach($files: [FileUpdateInput!]!) {
              fileUpdate(files: $files) {
                files { id fileStatus alt }
                userErrors { field message }
              }
            }
            """,
            variables={
                "files": [{
                    "id": file_id,
                    "referencesToAdd": [product_id],
                }]
            },
        )
        payload = data.get("fileUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify file association returned an invalid response"
            )
        errors = payload.get("userErrors")
        if isinstance(errors, list) and errors:
            messages = " ".join(
                str(error.get("message") or "")
                for error in errors
                if isinstance(error, dict)
            ).casefold()
            if "already" not in messages:
                self._raise_user_errors(
                    payload,
                    "Shopify rejected file association",
                )


    async def access_scopes(self) -> set[str]:
        data = await self.graphql(
            query="""
            query DropRateAccessScopes {
              currentAppInstallation {
                accessScopes { handle }
              }
            }
            """,
        )
        installation = data.get("currentAppInstallation")
        if not isinstance(installation, dict):
            raise ShopifyApiError(
                "Shopify access-scope response is invalid"
            )
        rows = installation.get("accessScopes")
        if not isinstance(rows, list):
            raise ShopifyApiError(
                "Shopify access-scope response is missing scopes"
            )
        scopes: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            handle = str(row.get("handle") or "").strip()
            if handle:
                scopes.add(handle)
        return scopes

    async def create_staged_image_upload(
        self,
        *,
        filename: str,
        mime_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            mutation DropRateStagedUpload($input: [StagedUploadInput!]!) {
              stagedUploadsCreate(input: $input) {
                stagedTargets {
                  url
                  resourceUrl
                  parameters { name value }
                }
                userErrors { field message }
              }
            }
            """,
            variables={
                "input": [{
                    "filename": filename,
                    "mimeType": mime_type,
                    "httpMethod": "POST",
                    "resource": "IMAGE",
                    "fileSize": str(file_size),
                }]
            },
        )
        payload = data.get("stagedUploadsCreate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify staged upload returned an invalid response"
            )
        self._raise_user_errors(payload, "Shopify rejected staged image upload")
        targets = payload.get("stagedTargets")
        if (
            not isinstance(targets, list)
            or len(targets) != 1
            or not isinstance(targets[0], dict)
        ):
            raise ShopifyApiError(
                "Shopify did not return exactly one staged upload target"
            )
        target = targets[0]
        url = str(target.get("url") or "").strip()
        resource_url = str(target.get("resourceUrl") or "").strip()
        parameters = target.get("parameters")
        if (
            not url.startswith("https://")
            or not resource_url.startswith("https://")
            or not isinstance(parameters, list)
        ):
            raise ShopifyApiError(
                "Shopify staged upload target is incomplete"
            )
        normalized_parameters: list[dict[str, str]] = []
        for parameter in parameters:
            if not isinstance(parameter, dict):
                raise ShopifyApiError(
                    "Shopify staged upload parameters are invalid"
                )
            name = str(parameter.get("name") or "").strip()
            value = str(parameter.get("value") or "")
            if not name:
                raise ShopifyApiError(
                    "Shopify staged upload parameter is missing its name"
                )
            normalized_parameters.append({"name": name, "value": value})
        return {
            "url": url,
            "resourceUrl": resource_url,
            "parameters": normalized_parameters,
        }

    async def find_product_by_handle(self, handle: str) -> dict[str, Any] | None:
        safe_handle = handle.strip()
        data = await self.graphql(
            query="""
            query DropRateProductByHandle($query: String!) {
              products(first: 2, query: $query) {
                nodes {
                  id
                  handle
                  status
                  metafield(namespace: "drop_rate", key: "inventory_id") {
                    value
                  }
                  variants(first: 1) {
                    nodes {
                      id
                      price
                      inventoryItem {
                        id
                        sku
                        tracked
                      }
                    }
                  }
                }
              }
            }
            """,
            variables={"query": f"handle:{safe_handle}"},
        )
        products = data.get("products")
        if not isinstance(products, dict) or not isinstance(products.get("nodes"), list):
            raise ShopifyApiError("Shopify product lookup returned an invalid response")
        exact = [
            product
            for product in products["nodes"]
            if isinstance(product, dict) and product.get("handle") == safe_handle
        ]
        if not exact:
            return None
        if len(exact) != 1:
            raise ShopifyApiError("Shopify product handle is not unique")
        return exact[0]

    async def get_product_snapshot(self, product_id: str) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            query DropRateProductSnapshot($id: ID!) {
              product(id: $id) {
                id
                title
                descriptionHtml
                handle
                status
                vendor
                productType
                tags
                templateSuffix
                seo { title description }
                category { id }
                metafields(first: 50, namespace: "drop_rate") {
                  nodes { key value type }
                }
                collections(first: 100) {
                  nodes { id title }
                }
                media(first: 20) {
                  nodes { id }
                }
                variants(first: 2) {
                  nodes {
                    id
                    price
                    inventoryPolicy
                    inventoryQuantity
                    inventoryItem {
                      id
                      sku
                      tracked
                      requiresShipping
                      measurement {
                        weight { value unit }
                      }
                    }
                  }
                }
              }
            }
            """,
            variables={"id": product_id},
        )
        product = data.get("product")
        if not isinstance(product, dict):
            raise ShopifyApiError(
                "Shopify product verification returned no product"
            )
        return product


    async def product_published_on_publication(
        self,
        *,
        product_id: str,
        publication_id: str,
    ) -> bool:
        data = await self.graphql(
            query="""
            query DropRatePublicationCheck($id: ID!, $publicationId: ID!) {
              product(id: $id) {
                id
                publishedOnPublication(publicationId: $publicationId)
              }
            }
            """,
            variables={
                "id": product_id,
                "publicationId": publication_id,
            },
        )
        product = data.get("product")
        if not isinstance(product, dict):
            raise ShopifyApiError(
                "Shopify publication verification returned no product"
            )
        return product.get("publishedOnPublication") is True


    async def create_product(self, product: dict[str, Any]) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            mutation DropRateProductCreate($product: ProductCreateInput!) {
              productCreate(product: $product) {
                product {
                  id
                  handle
                  status
                  variants(first: 1) {
                    nodes {
                      id
                      inventoryItem { id sku tracked }
                    }
                  }
                }
                userErrors { field message }
              }
            }
            """,
            variables={"product": product},
        )
        payload = data.get("productCreate")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify product creation returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected product creation")
        product_row = payload.get("product")
        if not isinstance(product_row, dict):
            raise ShopifyApiError("Shopify did not return the created product")
        return product_row

    async def update_product(
        self,
        *,
        product_id: str,
        product: dict[str, Any],
    ) -> dict[str, Any]:
        payload_input = {"id": product_id, **product}
        data = await self.graphql(
            query="""
            mutation DropRateProductUpdate($product: ProductUpdateInput!) {
              productUpdate(product: $product) {
                product {
                  id
                  handle
                  status
                  variants(first: 1) {
                    nodes {
                      id
                      inventoryItem { id sku tracked }
                    }
                  }
                }
                userErrors { field message }
              }
            }
            """,
            variables={"product": payload_input},
        )
        payload = data.get("productUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify product update returned an invalid response"
            )
        self._raise_user_errors(payload, "Shopify rejected product update")
        product_row = payload.get("product")
        if not isinstance(product_row, dict):
            raise ShopifyApiError("Shopify did not return the updated product")
        return product_row


    async def update_variant(
        self,
        *,
        product_id: str,
        variant_id: str,
        price: str,
        sku: str,
        cost: str | None,
        shipping_spec: dict[str, Any],
    ) -> dict[str, Any]:
        weight = shipping_spec.get("weight")
        if not isinstance(weight, dict):
            raise ShopifyApiError("Shipping specification is missing a weight")
        inventory_item: dict[str, Any] = {
            "sku": sku,
            "tracked": True,
            "requiresShipping": True,
            "measurement": {
                "weight": {
                    "value": float(weight["value"]),
                    "unit": str(weight["unit"]),
                }
            },
        }
        package_id = shipping_spec.get("shippingPackageId")
        if package_id:
            inventory_item["measurement"]["shippingPackageId"] = str(package_id)
        if cost is not None:
            inventory_item["cost"] = cost
        data = await self.graphql(
            query="""
            mutation DropRateVariantUpdate(
              $productId: ID!,
              $variants: [ProductVariantsBulkInput!]!
            ) {
              productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                  id
                  price
                  inventoryPolicy
                  inventoryItem { id sku tracked }
                }
                userErrors { field message }
              }
            }
            """,
            variables={
                "productId": product_id,
                "variants": [{
                    "id": variant_id,
                    "price": price,
                    "inventoryPolicy": "DENY",
                    "inventoryItem": inventory_item,
                }],
            },
        )
        payload = data.get("productVariantsBulkUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify variant update returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected variant update")
        variants = payload.get("productVariants")
        if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], dict):
            raise ShopifyApiError("Shopify did not return exactly one updated variant")
        return variants[0]

    async def update_variant_pool_identity(
        self,
        *,
        product_id: str,
        variant_id: str,
        price: str,
        sku: str,
    ) -> dict[str, Any]:
        """Update the shared identity of a pooled Shopify variant.

        This deliberately changes only the offer-level fields that every
        physical member shares. Shipping measurements and per-item acquisition
        cost remain untouched.
        """
        clean_sku = sku.strip()
        if not clean_sku:
            raise ValueError("Pooled Shopify SKU is required")
        data = await self.graphql(
            query="""
            mutation DropRatePooledVariantUpdate(
              $productId: ID!,
              $variants: [ProductVariantsBulkInput!]!
            ) {
              productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                  id
                  price
                  inventoryPolicy
                  inventoryItem { id sku tracked }
                }
                userErrors { field message }
              }
            }
            """,
            variables={
                "productId": product_id,
                "variants": [{
                    "id": variant_id,
                    "price": price,
                    "inventoryPolicy": "DENY",
                    "inventoryItem": {
                        "sku": clean_sku,
                        "tracked": True,
                    },
                }],
            },
        )
        payload = data.get("productVariantsBulkUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify pooled variant update returned an invalid response"
            )
        self._raise_user_errors(payload, "Shopify rejected pooled variant update")
        variants = payload.get("productVariants")
        if (
            not isinstance(variants, list)
            or len(variants) != 1
            or not isinstance(variants[0], dict)
        ):
            raise ShopifyApiError(
                "Shopify did not return exactly one pooled variant"
            )
        return variants[0]


    async def update_variant_price(
        self,
        *,
        product_id: str,
        variant_id: str,
        price: str,
    ) -> dict[str, Any]:
        """Update only the Shopify variant price.

        Price resync deliberately avoids touching cost, shipping measurements,
        SKU, inventory policy or quantity.
        """
        data = await self.graphql(
            query="""
            mutation DropRateVariantPriceUpdate(
              $productId: ID!,
              $variants: [ProductVariantsBulkInput!]!
            ) {
              productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants { id price }
                userErrors { field message }
              }
            }
            """,
            variables={
                "productId": product_id,
                "variants": [{
                    "id": variant_id,
                    "price": price,
                }],
            },
        )
        payload = data.get("productVariantsBulkUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify variant price update returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected variant price update")
        variants = payload.get("productVariants")
        if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], dict):
            raise ShopifyApiError("Shopify did not return exactly one updated variant")
        return variants[0]


    async def activate_inventory(
        self,
        *,
        inventory_item_id: str,
        location_id: str,
        idempotency_key: str,
    ) -> None:
        data = await self.graphql(
            query="""
            mutation DropRateInventoryActivate(
              $inventoryItemId: ID!,
              $locationId: ID!,
              $idempotencyKey: String!
            ) {
              inventoryActivate(
                inventoryItemId: $inventoryItemId,
                locationId: $locationId
              ) @idempotent(key: $idempotencyKey) {
                inventoryLevel { id }
                userErrors { field message }
              }
            }
            """,
            variables={
                "inventoryItemId": inventory_item_id,
                "locationId": location_id,
                "idempotencyKey": idempotency_key,
            },
        )
        payload = data.get("inventoryActivate")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify inventory activation returned an invalid response")
        errors = payload.get("userErrors")
        if isinstance(errors, list) and errors:
            messages = " ".join(
                str(error.get("message") or "")
                for error in errors
                if isinstance(error, dict)
            ).casefold()
            if "already" not in messages and "activated" not in messages:
                self._raise_user_errors(payload, "Shopify rejected inventory activation")

    async def set_inventory_quantity(
        self,
        *,
        inventory_item_id: str,
        location_id: str,
        quantity: int,
        idempotency_key: str,
    ) -> None:
        data = await self.graphql(
            query="""
            mutation DropRateInventorySet(
              $input: InventorySetQuantitiesInput!,
              $idempotencyKey: String!
            ) {
              inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
                inventoryAdjustmentGroup {
                  changes { name delta quantityAfterChange }
                }
                userErrors { field message }
              }
            }
            """,
            variables={
                "input": {
                    "name": "available",
                    "reason": "correction",
                    "referenceDocumentUri": f"drop-rate://inventory/{idempotency_key}",
                    "quantities": [{
                        "inventoryItemId": inventory_item_id,
                        "locationId": location_id,
                        "quantity": quantity,
                        "changeFromQuantity": None,
                    }],
                },
                "idempotencyKey": idempotency_key,
            },
        )
        payload = data.get("inventorySetQuantities")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify inventory quantity update returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected inventory quantity update")

    async def set_product_status(self, *, product_id: str, status: str) -> None:
        data = await self.graphql(
            query="""
            mutation DropRateProductStatus($product: ProductUpdateInput!) {
              productUpdate(product: $product) {
                product { id status }
                userErrors { field message }
              }
            }
            """,
            variables={"product": {"id": product_id, "status": status}},
        )
        payload = data.get("productUpdate")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify product status update returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected product status update")

    async def publish_product(self, *, product_id: str, publication_id: str) -> None:
        data = await self.graphql(
            query="""
            mutation DropRatePublishProduct($id: ID!, $input: [PublicationInput!]!) {
              publishablePublish(id: $id, input: $input) {
                userErrors { field message }
              }
            }
            """,
            variables={"id": product_id, "input": [{"publicationId": publication_id}]},
        )
        payload = data.get("publishablePublish")
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify product publication returned an invalid response")
        self._raise_user_errors(payload, "Shopify rejected product publication")

    async def set_product_metafields(
        self,
        *,
        product_id: str,
        metafields: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not product_id.strip():
            raise ValueError("Shopify product ID is required")
        if not metafields:
            raise ValueError("At least one Shopify metafield is required")
        if len(metafields) > 25:
            raise ValueError("Shopify metafieldsSet supports at most 25 inputs per call")

        inputs: list[dict[str, str]] = []
        for metafield in metafields:
            namespace = str(metafield.get("namespace") or "").strip()
            key = str(metafield.get("key") or "").strip()
            type_name = str(metafield.get("type") or "").strip()
            value = str(metafield.get("value") or "")
            if not namespace or not key or not type_name:
                raise ValueError("Shopify metafield namespace, key and type are required")
            inputs.append(
                {
                    "ownerId": product_id,
                    "namespace": namespace,
                    "key": key,
                    "type": type_name,
                    "value": value,
                }
            )

        data = await self.graphql(
            query="""
            mutation DropRateProductMetafieldsSet(
              $metafields: [MetafieldsSetInput!]!
            ) {
              metafieldsSet(metafields: $metafields) {
                metafields {
                  id
                  namespace
                  key
                  type
                  value
                }
                userErrors {
                  field
                  message
                  code
                }
              }
            }
            """,
            variables={"metafields": inputs},
        )
        payload = data.get("metafieldsSet")
        if not isinstance(payload, dict):
            raise ShopifyApiError(
                "Shopify metafieldsSet returned an invalid response"
            )
        self._raise_user_errors(payload, "Shopify rejected product metafields")
        rows = payload.get("metafields")
        if not isinstance(rows, list):
            raise ShopifyApiError(
                "Shopify metafieldsSet response is missing metafields"
            )
        return [row for row in rows if isinstance(row, dict)]


    @staticmethod
    def _raise_user_errors(payload: dict[str, Any], default: str) -> None:
        errors = payload.get("userErrors")
        if not isinstance(errors, list) or not errors:
            return
        messages = [
            str(error.get("message") or "").strip()
            for error in errors
            if isinstance(error, dict)
        ]
        raise ShopifyApiError("; ".join(message for message in messages if message) or default)
