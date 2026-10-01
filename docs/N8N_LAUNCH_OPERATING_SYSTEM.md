# Drop Rate — n8n Launch Operating System

_Status: founder-overridden Phase 2 strategy, 30 September 2026._

## Mission

The target operating model is not “use n8n for a few helper tasks.”

The target is a business that can be **run, operated and monetised with minimal founder intervention beyond physical stock acquisition, strategic decisions, relationship work and packing/dispatching orders**.

By launch, Drop Rate should behave like a coordinated operating machine:

`SENSE → NORMALISE → REASON → POLICY GATE → ACT → VERIFY → LEARN`

n8n is the orchestration nervous system across those steps.

PostgreSQL remains the durable source of truth.
FastAPI remains the deterministic business-rule and permission layer.
AI assists with interpretation, generation and prioritisation.
n8n connects the pieces, coordinates timing/retries/providers and closes the loop.

## Founder override to the earlier sequencing

The earlier Phase 2 recommendation to build one small workflow first was useful as a safety pattern, but it is **not the final delivery strategy**.

New rule:

> **Build broad before launch; activate narrow based on proof.**

This means:
- the full automation platform is now a parallel pre-launch workstream;
- multiple workflow families may be designed/built/tested before storefront launch;
- production activation is still per-workflow and evidence-gated;
- high-impact workflows remain inactive until their deterministic FastAPI contracts and failure tests are proven.

This avoids two bad outcomes:
1. launching with a manually operated business and “adding automation later”;
2. launching a huge untested autonomous workflow graph.

## Operating model

### 1. Sense

Inputs include:
- inventory/status events;
- recognition results;
- market data;
- Shopify/channel webhooks;
- orders/refunds;
- customer/account events;
- search/conversion analytics;
- SEO/search-console signals;
- content/social performance;
- system health;
- Action Required state.

### 2. Normalise

All provider-specific payloads are converted to stable Drop Rate contracts through FastAPI/adapters before decisions.

### 3. Reason

AI can:
- classify;
- summarise;
- rank;
- generate copy/briefs;
- identify anomalies;
- propose actions;
- explain why an action is useful.

AI cannot independently rewrite canonical identity, ownership, settlement truth or arbitrary final prices.

### 4. Policy gate

FastAPI/Postgres decides:
- is the item publishable?
- is this owner allowed?
- is this price valid?
- is the stock still available?
- is the experiment allowed?
- is a customer message permitted?
- is the action reversible?
- does this require human approval?

### 5. Act

n8n calls governed APIs or permitted provider integrations.

### 6. Verify

Every external mutation must be read back and reconciled.

Examples:
- Shopify product actually published;
- stock actually zeroed on all channels;
- email provider accepted the send;
- social post ID exists;
- Merchant Center diagnostics cleared;
- settlement report totals still reconcile.

### 7. Learn

Store structured results:
- success/failure;
- latency;
- conversion impact;
- customer response;
- content performance;
- false positive/negative;
- human correction;
- provider quality.

Learning may improve prompts, routing, ranking and experiment hypotheses. It must not silently change deterministic finance/ownership/identity rules.

## Control plane — required before aggressive activation

The control plane is mandatory infrastructure, not optional polish.

It includes:

1. **Workflow Registry**
   - stable workflow key;
   - purpose/domain;
   - owner/risk;
   - authority level;
   - version;
   - activation state;
   - backend contract;
   - required secrets/providers;
   - last proof/run status.

2. **Signed Event Gateway**
   - HMAC verification;
   - replay window;
   - schema validation;
   - unsupported-event rejection.

3. **Idempotency**
   - Drop Rate event ID/idempotency key reused;
   - backend mutation endpoints independently idempotent;
   - manual replay safe.

4. **Global Error Workflow**
   - receives n8n workflow errors;
   - normalises failure context;
   - creates/updates Action Required;
   - avoids recursive alert storms.

5. **Dead-letter / replay tooling**
   - failed outbox events remain visible;
   - replay is explicit and audited;
   - no silent dropping.

6. **Execution receipts**
   - important runs produce durable Postgres run/result records;
   - n8n execution history is not the business audit ledger.

7. **Health / heartbeat**
   - n8n health;
   - workflow heartbeat;
   - dispatcher backlog age;
   - provider failure rates;
   - dead-letter count;
   - stuck executions.

8. **Rate-limit / circuit-breaker policy**
   - provider-specific concurrency;
   - exponential backoff;
   - stop hammering an unhealthy provider;
   - alert rather than retry forever.

9. **Secrets**
   - n8n credential store / Railway secrets;
   - never workflow JSON;
   - least privilege per provider/workflow.

10. **Simulation / shadow mode**
   - workflows can calculate intended actions without mutating external state;
   - compare intended vs human action before granting autonomy.

## Authority model

### OBSERVE
May read, analyse, score and notify.

Examples:
- inventory intelligence;
- market movement detection;
- operational monitoring.

### ORCHESTRATE
May call deterministic backend operations.

Examples:
- recognition job;
- market ingestion;
- consignment state progression after backend validation.

### PUBLISH
May create customer/public outputs after validation.

Examples:
- Shopify publication;
- email;
- social post;
- SEO metadata.

### HIGH_IMPACT
May orchestrate actions with stock/finance/customer consequences **only through deterministic FastAPI controls**.

Examples:
- multi-owner allocation;
- refunds;
- settlement preparation;
- cross-channel stock withdrawal.

n8n never receives authority to independently invent the underlying business result.

## Intelligence architecture

The system should feel intelligent because it:
- notices important things without being asked;
- prioritises exceptions;
- knows what can safely be handled automatically;
- escalates only what genuinely needs a founder;
- learns from outcomes;
- compares expected vs actual results;
- uses context from the real database;
- adapts content/growth experiments within policy;
- produces concise daily/exception briefings.

The system should **not** feel intelligent merely because an LLM is inserted into every workflow.

Use AI where ambiguity/generation/interpretation exists.
Use deterministic code where correctness is knowable.

## Launch target

Before launch, the goal is to have:
- the control plane implemented;
- the 43-workflow registry source-controlled;
- every workflow at least DESIGNED;
- launch-critical workflows BUILT_INACTIVE or PROVEN;
- safe OBSERVE workflows activated where useful;
- high-impact workflows tested in simulation/shadow mode;
- global error/health monitoring active;
- no workflow existing only in the n8n UI;
- a clear remaining dependency list for provider accounts/permissions.

## Workflow programme

The canonical registry is:

`automation/n8n/workflow-registry.json`

The 43 current workflow families cover:
- inventory/intake;
- recognition;
- sealed;
- pricing/market data;
- Shopify;
- orders/refunds;
- ownership/settlement;
- consignments;
- cross-channel commerce;
- Seller Hub/customer portfolio;
- marketing triggers;
- AI listings;
- SEO/CRO;
- creative/social;
- email lifecycle;
- customer service;
- recommendations;
- inventory intelligence;
- founder briefings;
- analytics;
- image quality;
- errors;
- hardware;
- operational monitoring.

## Pre-launch build waves

### Wave A — Control Plane
Implementation status: **source-control complete; production activation intentionally gated**.

Implemented:
- registry;
- signed event ingress;
- global error workflow;
- reusable durable success receipt contract;
- Action Required integration;
- dead-letter/replay visibility;
- dispatcher backlog monitoring;
- canonical n8n runtime heartbeat;
- dispatcher-process heartbeat monitoring.

### Action Required bridge decision

Do **not** add a separate generic n8n “Action Required bridge” workflow.

The bridge is already deterministic:
- DR-90 sends an HMAC-signed FAILED execution receipt to FastAPI;
- FastAPI validates it, writes the durable `tcg.automation_runs` receipt and upserts a deduped `N8N_WORKFLOW_FAILED` Action Required item;
- backend/Postgres health monitors create and resolve their own deduped Action Required items for outbox, heartbeat and other system-health failures.

This preserves the architecture boundary: n8n orchestrates, FastAPI decides deterministic control behavior, Postgres stores durable truth.

Activation remains gated on migration/application proof, workflow publication proof, duplicate/retry tests and historical-backlog disposition.

### Wave B — Core Commerce Operations
Build before launch:
- inventory status orchestration;
- Shopify creation/update;
- order processing/reconciliation;
- refund/return orchestration;
- multi-owner allocation verification;
- settlement preparation;
- customer purchase → portfolio handoff skeleton.

### Wave C — Inventory / Recognition / Pricing
Build in parallel:
- intake/bulk import;
- raw/slab/sealed recognition orchestration;
- corpus enrichment;
- market ingestion/normalisation;
- pricing recalc;
- image-quality audit.

### Wave D — Customer / Seller / Consignment
Build in parallel:
- customer lifecycle;
- Seller Hub invitation/portfolio;
- consignment state workflows;
- consignor sale/settlement updates;
- customer-service escalation.

### Wave E — Growth Engine
Build before or at launch where dependencies allow:
- new-stock/price/trend event engine;
- AI listing copy;
- SEO maintenance;
- content/creative briefs;
- social scheduling;
- competitor intelligence / opportunity generation in shadow mode;
- founder daily briefing;
- analytics.

SEO/CRO autonomous experimentation should be built and simulated before launch, then activated only after there is enough real traffic to measure.

### Wave F — Cross-channel / Advanced Optimisation
Build adapters and tests early; activate when provider accounts/permissions are ready:
- eBay;
- Whatnot;
- Cardmarket;
- TCGplayer;
- cross-channel stock protection;
- channel reconciliation;
- advanced recommendation/optimisation loops.

## Backlog rule

The 396 existing `inventory.approved` outbox events are historical backlog.

Do **not** point an activated generic Event Gateway at them until:
- event routing is explicit;
- duplicate handling is proven;
- the intended consumer is defined;
- backlog disposition is chosen.

Options later:
- intentionally supersede historical events;
- replay only a controlled subset;
- route them through shadow mode;
- process them through a proven idempotent workflow.

They must not be accidentally consumed as the first production test.

## Definition of “well-oiled” at launch

A workflow is not launch-grade merely because it ran once.

For each launch-critical workflow we require:
- deterministic contract;
- version-controlled JSON;
- test fixtures;
- duplicate test;
- timeout/retry test;
- provider/API failure test;
- authorization test;
- read-back/reconciliation;
- observable result;
- Action Required on irrecoverable failure;
- replay procedure;
- measured latency/throughput where relevant;
- owner of the exception.

The founder should see **exceptions and decisions**, not routine plumbing.
