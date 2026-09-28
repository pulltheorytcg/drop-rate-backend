# Drop Rate — n8n Automation Foundation

_Last updated: 28 September 2026_

## Purpose

n8n is the orchestration layer for Drop Rate.

It is the nervous system of the business, not the source of truth and not the deterministic business-rule engine.

The authoritative responsibilities remain:

- PostgreSQL/Supabase: canonical data and durable state
- FastAPI: deterministic rules and permissioned operations
- Shopify: storefront, checkout, customer/order surface
- n8n: event routing, scheduling, external integrations, AI/content orchestration, notifications and retryable workflow coordination

n8n must never calculate ownership, settlements, final pricing or exact card identity independently.

## Launch architecture

The initial integration uses a transactional event outbox.

Flow:

PostgreSQL/FastAPI state change
→ `tcg.automation_events`
→ Railway automation dispatcher
→ signed HTTPS webhook
→ n8n workflow
→ FastAPI / approved external services
→ durable result / exception

The outbox exists so a business event cannot be lost merely because n8n or the network is temporarily unavailable.

## Event outbox

Migration:

`database/migrations/20260928033000_automation_event_outbox.sql`

Each event has:

- event ID
- event type
- schema version
- aggregate type
- aggregate ID
- owner ID where relevant
- idempotency key
- sanitized payload
- status
- attempt count
- maximum attempts
- lease owner/time
- retry timestamp
- error code
- delivered/dead-letter timestamps

Statuses:

`PENDING → DISPATCHING → DELIVERED`

or:

`PENDING/DISPATCHING → DEAD_LETTER`

Expired leases return to PENDING unless retry budget is exhausted.

## Security

The dispatcher sends only explicitly constructed event envelopes.

It does not forward arbitrary database rows.

Webhook requests are signed using HMAC-SHA256.

Headers:

- `X-Drop-Rate-Event-Id`
- `X-Drop-Rate-Event-Type`
- `X-Drop-Rate-Schema-Version`
- `X-Drop-Rate-Timestamp`
- `X-Drop-Rate-Signature`

Signature input:

`<unix timestamp>.<exact request body>`

n8n must reject:

- missing signature
- invalid signature
- stale timestamp outside the accepted replay window
- unsupported schema version
- missing event ID
- malformed JSON

The shared webhook secret must be at least 32 characters and must remain in Railway/n8n secret storage, never source control.

## Retry behavior

Dispatcher failure handling:

- HTTP 2xx: ACK and mark DELIVERED
- timeout/network error: retry
- HTTP 429: retry
- HTTP 5xx: retry
- HTTP 4xx: dead-letter immediately because this normally indicates authentication, configuration or event-contract failure

Retry backoff is deterministic exponential backoff capped at 30 minutes.

Default maximum attempts: 8.

Dead-letter events must eventually surface in Founder HQ Action Required.

## First event

### `inventory.approved` v1

Emitted transactionally when a physical inventory item enters APPROVED.

Aggregate:

`INVENTORY_ITEM`

Payload intentionally contains only:

- inventory_id
- inventory_code
- catalogue_id
- status
- version

It deliberately excludes:

- acquisition cost
- owner financial information
- private notes
- settlement data
- customer data
- market-provider secrets

Consumers needing fresh facts must call FastAPI.

This event does **not** mean "publish to Shopify".

It means:

"an inventory item entered the APPROVED business state; orchestration may now evaluate downstream work."

FastAPI/Shopify readiness gates still decide whether publication is legal and complete.

## First launch workflow families

The first workflows should be built in this order.

### 1. System / exception alerts

Purpose:
- make failures visible immediately

Events/schedules:
- Shopify sync failure
- eBay sync failure
- dead-letter automation event
- provider outage
- recognition high-value review
- missing owner
- settlement discrepancy
- media mismatch

Actions:
- create/update Action Required item
- send founder notification
- optionally email/Slack later

No business-state override.

### 2. Inventory → Shopify orchestration

Trigger:
- `inventory.approved`

Flow:
1. verify webhook signature
2. de-duplicate event ID
3. call FastAPI for current Shopify readiness
4. if blocked:
   - record/route blocker
   - do not publish
5. if ready:
   - call approved FastAPI sync endpoint
6. verify resulting state through FastAPI
7. finish workflow

n8n does not create Shopify products directly if a governed FastAPI operation exists.

### 3. Scheduled market/pricing refresh

Trigger:
- schedule

Flow:
1. request eligible refresh candidates from FastAPI
2. invoke provider-ingestion jobs through FastAPI
3. wait/retry bounded provider failures
4. request deterministic pricing recalculation
5. request safe Shopify price resync
6. surface exceptions

n8n never calculates final price.

### 4. SEO / storefront content events

Triggers:
- new set reaches sufficient stock
- meaningful new inventory cluster
- product/collection data changed
- new graded/grail inventory

Flow:
1. fetch verified public facts from FastAPI
2. AI generates title/meta/copy suggestions
3. deterministic validation
4. approval initially
5. write through the governed storefront/Shopify path
6. record result

Avoid mass-generation of low-value pages.

### 5. Marketing content engine

Triggers:
- NEW_GRAIL
- NEW_STOCK
- NEW_SET
- MAJOR_PRICE_MOVE
- TRENDING_CARD
- SIGNIFICANT_SALE
- LOW_STOCK
- COLLECTION_DROP

Flow:
event
→ verified marketing payload
→ AI brief
→ creative generation
→ caption/CTA
→ factual/brand validation
→ human approval initially
→ publish
→ record post/platform IDs
→ collect performance

### 6. Social publishing

Target platforms depend on available official API permissions.

Potential channels:
- Instagram
- TikTok
- Facebook
- X
- Pinterest
- YouTube Shorts where appropriate

Do not build workflows that depend on prohibited scraping or credential sharing.

### 7. Email/customer lifecycle

Potential workflows:
- welcome
- abandoned cart
- back in stock
- new drop
- set-specific new stock
- price-drop/watchlist alert
- post-purchase related-card recommendation
- consignor lifecycle notifications

Consent/privacy must be respected.

### 8. Merchandising intelligence

Potential inputs:
- search volume
- product views
- conversion
- stock depth
- market movement
- sell-through
- time-on-site
- wishlist/back-in-stock interest

Output should initially be:
- suggestions or collection-placement decisions under deterministic rules

Do not allow AI alone to change price or ownership.

## Workflow idempotency

Every n8n workflow receiving Drop Rate events must de-duplicate by `event_id` and/or the supplied `idempotency_key`.

Any FastAPI mutation endpoint called by n8n must also be idempotent.

n8n workflow retries must therefore be safe even when:
- it received the same event twice
- n8n timed out after FastAPI succeeded
- FastAPI timed out after an external provider succeeded
- the dispatcher resent after losing an ACK
- the workflow was manually replayed

## n8n data rules

n8n may hold:
- workflow configuration
- transient execution context
- event IDs
- external response IDs
- retry context

n8n must not become the canonical store for:
- card identity
- inventory
- ownership
- price
- market observations
- settlement
- payouts
- consignments
- customer order truth

Durable business facts return to FastAPI/Postgres.

## n8n credentials

Credentials should be stored in n8n's encrypted credential store / secrets, not workflow JSON.

Never commit:
- API keys
- social tokens
- Shopify secrets
- Supabase service-role keys
- Railway tokens
- AI keys
- webhook secrets

## Deployment

The dispatcher image is:

`Dockerfile.automation`

Entry point:

`backend/scripts/run_automation_dispatcher.py`

Required environment variables:

- `TCG_DATABASE_URL`
- `TCG_N8N_WEBHOOK_URL`
- `TCG_N8N_WEBHOOK_SECRET`

Optional tuning:

- `TCG_AUTOMATION_WORKER_ID`
- `TCG_AUTOMATION_POLL_SECONDS`
- `TCG_AUTOMATION_BATCH_SIZE`
- `TCG_AUTOMATION_LEASE_SECONDS`
- `TCG_AUTOMATION_HTTP_TIMEOUT_SECONDS`

Do not deploy the dispatcher until:
1. migration tests pass
2. dispatcher tests pass
3. the n8n webhook exists
4. signature verification is implemented in the n8n entry workflow
5. a development/test event has been delivered successfully
6. duplicate delivery has been proven safe
7. dead-letter behavior has been tested

## Initial n8n workflow contract

Recommended first entry workflow:

`DR-00 Event Gateway`

Responsibilities:
1. receive signed webhook
2. verify timestamp/signature
3. validate envelope
4. deduplicate event
5. route by event type
6. reject unsupported schema versions
7. call the appropriate sub-workflow
8. return 2xx only once the event has been safely accepted

Sub-workflow naming convention:

- `DR-01 Inventory Approved`
- `DR-02 Shopify Sync Exception`
- `DR-03 Market Refresh`
- `DR-10 SEO Event`
- `DR-20 Marketing Brief`
- `DR-21 Social Publish`
- `DR-30 Customer Lifecycle`
- `DR-90 Error / Dead Letter Alert`

This keeps workflows modular rather than creating one enormous n8n graph.

## Current status

As of 28 September 2026:

- transactional outbox code: feature branch
- signed dispatcher worker: feature branch
- first event `inventory.approved`: feature branch
- tests: feature branch
- production migration: NOT APPLIED
- Railway dispatcher service: NOT CREATED
- real n8n webhook: NOT CONNECTED
- automated Shopify publication from n8n: NOT ENABLED
- social auto-posting: NOT ENABLED

This is deliberate. The foundation must pass CI and be verified before production activation.
