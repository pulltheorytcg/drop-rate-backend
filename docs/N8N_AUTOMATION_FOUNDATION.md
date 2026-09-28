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

## AI Experimentation Engine — SEO + CRO

Drop Rate should not use AI only to generate ideas. The target state is a governed closed-loop experimentation system where AI can propose, launch, measure, stop and promote experiments within explicit authority boundaries.

### Architecture

Flow:

verified storefront/business data
→ AI hypothesis
→ deterministic experiment validator
→ experiment registry in Postgres
→ variant assignment
→ Shopify theme/app-extension rendering
→ Shopify Web Pixel / customer-event measurement
→ experiment metrics in Postgres
→ statistical decision engine
→ AI interpretation
→ governed action
→ audit log

n8n orchestrates the loop but does not own experiment truth or statistical rules.

### Canonical experiment record

The source of truth should ultimately track:

- experiment_id
- experiment_type: CRO | SEO | MERCHANDISING | CONTENT
- hypothesis
- target surface
- target population
- primary metric
- guardrail metrics
- control definition
- treatment definitions
- traffic allocation
- start/end rules
- minimum sample / observation window
- statistical method/version
- status
- AI proposal provenance
- approval level
- winning variant
- decision evidence
- rollout state
- rollback state
- created/updated timestamps
- full audit history

n8n execution history is not the experiment database.

### CRO experiments

Safe autonomous candidates include:

- product-card copy
- CTA wording
- CTA prominence
- PDP information ordering
- image ordering
- trust/reassurance block position
- shipping-message presentation when factually accurate
- collection sort strategy
- recommendation placement
- search-result presentation
- filter defaults
- homepage section order
- merchandising modules
- mobile navigation treatments
- Sell/Consign CTA presentation
- factual badges derived from backend data

Core metrics may include:

- product view → add-to-cart rate
- add-to-cart → checkout rate
- checkout → purchase rate
- overall conversion rate
- revenue per eligible session
- search success
- zero-result search rate
- PDP-to-cart rate
- collection-to-PDP click-through
- return/refund guardrails
- page-speed / performance guardrails

### AI authority levels

**LEVEL 0 — observe only**
AI analyses data and proposes experiments.

**LEVEL 1 — generate**
AI creates variants, but a founder approves launch and winner rollout.

**LEVEL 2 — controlled autonomy**
AI may launch pre-approved low-risk experiment classes, monitor them, stop harmful variants and promote a statistically valid winner.

**LEVEL 3 — continuous optimization**
AI continuously rotates and optimizes approved low-risk surfaces under hard experiment budgets, statistical rules and performance guardrails.

Drop Rate should launch at Level 1, graduate selected experiment classes to Level 2 after repeated safe operation, and never assume Level 3 authority globally.

### Actions AI may eventually take autonomously

Subject to the experiment policy:

- create a new low-risk variant
- allocate bounded traffic
- start an experiment
- pause an experiment
- stop a variant breaching a guardrail
- extend an experiment when evidence is inconclusive
- declare a winner only through the deterministic decision engine
- roll the winning variant to 100%
- restore the control if post-rollout metrics deteriorate
- queue the next experiment based on validated learning
- update merchandising placement
- update approved content fields
- record learning for future hypotheses

### Actions AI may NOT take autonomously

Without a separate deterministic/human approval path:

- arbitrary Store Price changes
- acquisition-cost changes
- owner/consignor economics
- commission changes
- settlement/payout changes
- invented scarcity
- fake countdown timers
- false social proof
- misleading discount claims
- authenticity/grade claims unsupported by data
- legal/privacy text changes
- consent-banner weakening
- checkout/payment behavior changes
- high-risk claims about investment/value appreciation
- destructive theme changes

Price testing, if ever introduced, must go through the deterministic pricing engine and a separate approved experiment policy. AI must not invent prices.

### Statistical decision boundary

AI does not decide that a variant "won" because it looks better.

FastAPI/statistics code should determine:

- minimum observation window
- sample-size sufficiency
- confidence / posterior threshold
- minimum practical effect
- guardrail breaches
- novelty/seasonality controls
- winner / loser / inconclusive state

The statistical method and version must be stored with each experiment.

AI may explain the result and choose the next hypothesis from the permitted action set.

### Shopify implementation

Use:

- Shopify Online Store 2.0 / theme app extensions for controlled variant surfaces
- Web Pixels/customer events for analytics and conversion measurement
- custom storefront events where Drop Rate-specific interactions need tracking
- stable experiment assignment stored in a privacy-aware first-party identifier where permitted
- server-side order truth for final purchase/revenue outcomes

Experiments must not depend solely on third-party analytics attribution.

### SEO experimentation is different from CRO

Do not run SEO tests by serving Googlebot one version and human users another.

SEO experiments should use:

- page/template cohorts
- comparable collection/set groups
- sequential before/after tests when cohorts are impossible
- stable public URLs
- normal crawlable content
- consistent canonical rules
- no crawler-specific treatment

Potential SEO variables:

- title tags
- meta descriptions
- collection intro copy
- internal linking
- headings
- structured-data completeness
- image alt text
- set/category information architecture
- indexable landing-page templates
- content depth where it adds genuine user value

SEO metrics:

- impressions
- clicks
- search CTR
- average position
- organic sessions
- organic conversion
- organic revenue
- indexed coverage
- query/category coverage
- multimodal / visual-search performance when available

Search Console data should be ingested into the analytics layer and evaluated over sufficiently long windows rather than reacting to daily noise.

### DR experiment workflows

Planned n8n workflow family:

- `DR-40 Experiment Opportunity Detector`
- `DR-41 AI Hypothesis + Variant Generator`
- `DR-42 Experiment Preflight`
- `DR-43 Experiment Launch`
- `DR-44 Experiment Monitor`
- `DR-45 Experiment Decision`
- `DR-46 Winner Rollout / Rollback`
- `DR-47 SEO Experiment Monitor`
- `DR-48 Learning Registry`

Each workflow calls FastAPI. None of them independently mutates canonical experiment truth.

### Experiment preflight

Before launch, automatically verify:

- surface is on the approved autonomous allowlist
- experiment does not alter canonical card facts
- experiment does not alter ownership/settlement/pricing rules
- factual copy matches backend data
- no deceptive urgency/scarcity claim
- traffic allocation is within policy
- no conflicting experiment owns the same surface
- required analytics events are live
- control and rollback versions exist
- mobile + desktop rendering passes
- accessibility/performance guardrails pass

If any check fails: do not launch; create Action Required.

### Autonomous stopping / rollback

An autonomous experiment may be stopped early when:

- checkout errors rise
- conversion drops beyond a configured safety boundary
- page performance materially degrades
- refund/cancellation rate rises unexpectedly
- tracking becomes incomplete
- data integrity fails
- a storefront deployment changes the tested surface unexpectedly

Rollback should restore a known version, not ask AI to reconstruct the previous page from memory.

### Learning loop

After each experiment:

result
→ structured learning
→ feature/surface/context
→ winning/losing mechanism
→ confidence
→ applicable games/categories/devices
→ next hypotheses

This produces a durable Drop Rate optimization corpus rather than a pile of disconnected A/B tests.

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
