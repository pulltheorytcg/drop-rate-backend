# Base44 TCG Value Track → Drop Rate: read-only transport staging (13 Nov 2026)

## Current state
This change prepares a strictly **disabled-by-default** HTTP transport for an independent Base44 API. It deliberately does not register Base44 as a sold-price source, add database constraints, update valuations, alter Shopify or request any paid scraping service.

**BLOCKER**: The connected Base44 account currently reports no accessible apps, including `TCG Value Track`. The existing app's real endpoint, production publication, method, JSON request/response and access to provider-compliant completed-sale data remain **unverified**. The request body below is a **proposed interface**, not a confirmed Base44 contract.

## Supported target categories
Pokémon; One Piece; Naruto; Dragon Ball Masters/Fusion World; Riftbound; Disney Lorcana; Yu-Gi-Oh!; Magic: The Gathering; comics; manga; Funko Pops; licensed figurines; sealed products. Identity must keep language, print/variant, condition, grading company, exact grade and product type distinct.

## Proposed transport contract (must reconcile with actual published Base44 API)
- POST to the **actual** HTTPS Base44 function URL provided by the connected app.
- Header: `x-api-key: <secret generated in Base44>`
- Request JSON: `{"lookup":{"game":"Pokemon","name":"Charizard","set_name":"Base Set","card_number":"4/102"}}`
- Response: one JSON object; structure must be learned and tested from the deployed app before writing an ingestion mapper.

## Intended Railway service
Project: `drop-rate-backend`
Service: `drop-rate-api-live`
Secrets / variables (do not put values in GitHub):
- `BASE44_MARKET_API_URL` = **exact** verified Base44 endpoint URL.
- `BASE44_MARKET_API_KEY` = same secret as `MARKET_API_KEY` in Base44.
- `BASE44_MARKET_READ_ONLY_ENABLED=false` until method, schema, authentication and access permissions have been tested.

No live variables are set by this PR.

## Release gates
1. Verify Base44 plugin app access and inspect existing backend function rather than creating a duplicate app.
2. Verify the free plan permits the needed server-to-server backend function and publishing.
3. Test valid/invalid auth, unknown card and provider failure against Base44's **real** endpoint; update the proposed transport contract to match it.
4. Read-only pilot for a real Pokémon, One Piece, graded card and the remaining collectible categories.
5. Validate identity, variant, country, condition, source record ID, actual paid price, timestamp and licensing independently; active asking prices are never sold evidence.
6. Only after verified: adapt into existing FastAPI source admission and deterministic pricing, with append-only Supabase Pro history and no duplication.
7. Keep Railway, Supabase Pro, GitHub, Shopify as the Drop Rate stack; Base44 is external source. No Cloudflare migration, new scraper subscription or competing valuation engine.

`backend/app/base44_market_client.py` makes **no persistent writes**. It fails closed for redirects, HTTP errors, timeouts, invalid JSON and oversized payloads; the diagnostic preview omits prices and private provider data. It is intentionally not used by a production pricing workflow until the upstream contract is known.
