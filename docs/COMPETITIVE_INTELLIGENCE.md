# Competitive Intelligence & Experimentation

## Purpose

Drop Rate should understand what successful market leaders, direct competitors and smaller emerging TCG businesses are doing without relying on founders manually checking them.

The goal is **not to copy competitors**. The goal is to convert permitted public observations into evidence-backed hypotheses, combine them with Drop Rate's own customer/inventory/market signals, and feed only qualified opportunities into the existing Content Machine and governed CRO/SEO experiment engine.

This workstream is part of the Drop Rate intelligence layer:

`SENSE → NORMALISE → CORROBORATE → QUALIFY → HAND OFF → MEASURE → LEARN`

It remains OBSERVE-only until the Phase 3 launch-stability gate permits activation.

## Competitor groups

The watchlist should deliberately cover:

- **MARKET_LEADER** — large/successful businesses that show what has already scaled.
- **DIRECT** — businesses competing for the same cards/customers/UK demand.
- **EMERGING** — smaller/faster shops that may expose useful new formats or tactics early.

Discovery may suggest a business, but adding it to continuous automated monitoring requires founder approval and source-specific terms/rights review.

## What may be observed

Only legitimate public/permitted sources may be used. Potential observation classes include:

- catalogue/product launches;
- public price changes and promotions;
- stock-out / restock signals;
- bundles and loyalty/referral propositions;
- merchandising and navigation patterns;
- product-page/CRO patterns;
- public SEO/content topics;
- public social topics/formats and visible engagement;
- newsletters Drop Rate legitimately subscribes to;
- channel expansion;
- public customer reviews and recurring pain points.

A competitor asking price is **competitor evidence**, not market value. It must never be promoted directly into Drop Rate pricing truth.

## Source contract

Every automated source adapter must record/declare:

- source/provider;
- stable source key;
- collection method;
- source URL/identifier where applicable;
- terms review state/date;
- rate/concurrency policy;
- rights status;
- observed timestamp;
- evidence/facts;
- confidence;
- dedupe key.

Approved collection methods are deliberately bounded:

- official/public APIs;
- public feeds;
- public pages only where source terms permit the intended automated access;
- newsletters legitimately subscribed to;
- manual review.

No adapter may bypass authentication, anti-bot controls, paywalls, robots/access restrictions or provider limits.

## Rights / copying boundary

Competitor material is `REFERENCE_ONLY` by default.

Drop Rate may learn abstract patterns such as:

- topic;
- content format;
- timing;
- hook category;
- merchandising concept;
- offer structure;
- navigation pattern;
- customer pain point.

It must not automatically reproduce competitor:

- photography;
- video;
- scripts;
- descriptions;
- distinctive creative expression;
- watermarks;
- private/non-public data.

Generated output must be original Drop Rate material unless separate rights explicitly permit reuse.

## Corroboration rule

One competitor action is not a strategy signal.

A competitive opportunity becomes `QUALIFIED` only when:

1. at least one competitor observation exists;
2. at least two independent source keys exist;
3. at least one non-competitor origin corroborates it — e.g. Drop Rate analytics, market data, social trend data or an official release/news source;
4. the deterministic evidence score clears the configured threshold.

Otherwise it remains `WATCH`.

This prevents the system from following competitors in circles.

## Handoffs

Competitive Intelligence itself has **OBSERVE** authority.

Allowed outputs are proposals only:

- create an opportunity record;
- propose a CRO/SEO experiment;
- propose original content;
- propose merchandising;
- propose an acquisition review;
- propose SEO review.

It cannot directly:

- publish content;
- change prices;
- buy inventory;
- change ownership;
- alter settlements/finance;
- copy competitor material.

### Content Machine

Qualified content opportunities may later hand off an evidence bundle to the Content Machine foundation in PR #216. The factual evidence remains separate from the creative brief.

### CRO/SEO experiment engine

Qualified CRO/SEO/merchandising opportunities may later hand off a hypothesis to the governed experiment engine in PR #215. That engine still owns approval, traffic allocation, measurement, statistical decisions, rollout and rollback.

### Inventory acquisition intelligence

A qualified opportunity may say **investigate acquisition** when competitor stock, external market velocity, social/official signals and Drop Rate stock position align. It never purchases inventory automatically.

## Planned n8n workflow

Registry key: `competitive-intelligence` (sequence 43).

Initial production authority: `OBSERVE`.

Planned stages:

1. load founder-approved watchlist/source contracts;
2. collect through permitted adapters;
3. normalize observations through FastAPI;
4. dedupe;
5. combine with internal/market/social/official signals;
6. call deterministic opportunity qualification;
7. persist/hand off a proposal;
8. include important opportunities in founder briefing;
9. measure the eventual downstream experiment/content result;
10. retain positive and negative learning outcomes.

No workflow JSON is activated by this foundation. Activation remains gated on source permissions, backend persistence/API contracts, shadow-mode proof, duplicate/retry tests and the Phase 3 stability gate.

## Learning loop

The system should retain:

- what was observed;
- what hypothesis was proposed;
- whether humans approved/dismissed it;
- what experiment/content action was eventually run;
- measured business outcome;
- whether the opportunity was useful.

Learning may improve opportunity ranking, source weighting and future hypothesis generation. It may not silently relax source permissions, rights rules, finance/ownership rules or production activation gates.

## Current implementation

`backend/app/competitive_intelligence.py` provides deterministic primitives for:

- source preflight;
- evidence normalization/deduplication;
- multi-origin opportunity qualification;
- OBSERVE-only action preflight.

The persistence/API slice adds:

- `tcg.competitors` — founder-approved market leaders, direct competitors and emerging competitors;
- `tcg.competitor_sources` — source-specific collection method, rights state, terms review, cadence and activation state;
- `tcg.competitive_observations` — immutable, deduplicated observations with facts/evidence and confidence/relevance;
- `tcg.competitive_opportunities` — deterministic WATCH/QUALIFIED opportunity records;
- `tcg.competitive_opportunity_evidence` — immutable multi-origin evidence behind each opportunity;
- admin-only FastAPI endpoints under `/api/v1/competitive-intelligence`.

The database is backend-only: forced RLS, no browser role access, no delete path, immutable evidence rows and audit events for every canonical change.

### API contract

Current admin operations are intentionally bounded to:

- create/list competitors;
- create/list sources;
- activate/pause/block sources through version-checked status changes;
- record/list normalized observations from already-approved active sources;
- evaluate/store opportunities from stored competitor observations plus explicitly supplied internal/market/social/official corroboration;
- list opportunities.

There is **no external website/social fetcher in FastAPI** and no autonomous publisher in this API.

For competitor evidence, the caller supplies only the stored observation ID. Source identity, confidence, relevance, rights state and competitor identity are loaded from canonical Postgres evidence. This prevents a caller from inventing extra "independent" competitor sources to force qualification.

### Production activation sequence

1. merge CI-green persistence/API PR;
2. apply the exact version-controlled migration through Supabase;
3. verify tables, RLS, grants, immutable triggers and audit behavior;
4. verify Railway production deploy and `/health/ready`;
5. create only founder-approved watchlist/source records;
6. build source adapters/n8n collection in a later PR;
7. keep collection in shadow mode until the Phase 3 launch-stability and source-specific permission gates are satisfied.


## Replay and evidence hardening

Opportunity and observation idempotency is strict rather than approximate:

- an observation dedupe key is a duplicate only when the complete immutable payload matches, including facts, evidence, confidence/relevance and source publication time;
- a reused opportunity key must match the same hypothesis, qualification threshold, resulting decision and normalized evidence contract;
- evidence from a source later marked `BLOCKED`, or a competitor later marked `REJECTED`, cannot qualify a new opportunity;
- the qualification threshold and original qualification state are persisted with the opportunity so replay/audit can reconstruct the decision contract even if the later lifecycle state becomes DISMISSED or HANDED_OFF;
- confidence, relevance and qualification thresholds are normalized to the database's five-decimal precision before evaluation/persistence/replay.

These checks do not rewrite historical evidence or activate any external collection.

## Signed shadow ingestion

The automation boundary is deliberately one-way and shadow-only.

`POST /api/v1/automation/competitive-intelligence/observations/shadow` accepts HMAC-signed batches from Drop Rate automation using the existing automation command secret. The endpoint does not use a founder/browser session and does not expose direct table credentials to n8n.

For every observation, Postgres independently re-checks that the source exists, the competitor remains APPROVED, the source remains ACTIVE, the source is automated rather than MANUAL_REVIEW, and provider/source terms are REVIEWED. Rights and source identity come from canonical Postgres state, never from n8n.

Accepted rows are immutable `SYSTEM` observations with no founder user ID. Identical replay returns the existing observation; changed-content reuse of a dedupe key fails closed. Replay comparison deliberately excludes mutable source URL/rights metadata, while new inserts still inherit the source contract current at insertion time.

The endpoint returns `mode=SHADOW` and `external_action_taken=false`. It has no external fetcher, Shopify/eBay client, price mutation, inventory mutation, financial write or publishing capability.

### Shadow-ingestion production verification

The signed shadow-ingestion backend is deployed and healthy. Supabase recorded the applied migration as `20261001024803_competitive_intelligence_shadow_ingestion`; repository history is aligned to that version without SQL re-execution. The function is server-only (`tcg_api` execute; no anon/browser-authenticated/service-role execute), production still contains zero Competitive Intelligence observations, and Railway verified the merged application with 2,207 passing tests plus a 200 readiness check.

Migration history: `20261001024803_competitive_intelligence_shadow_ingestion`.


### Automation provenance hardening

The signed shadow-ingestion boundary stores the exact workflow key, workflow version and originating execution ID on the first immutable SYSTEM observation. Audit events generated by these inserts identify the actor as `automation:competitive-intelligence`.

The original 11-argument database ingestion function remains as a compatibility wrapper during rolling deploys and delegates to the provenance-aware function. This prevents a migration/API deployment ordering window from breaking signed ingestion. Duplicate evidence remains keyed by immutable observation content; a retry from a different execution does not create a second observation.


## DR-43 source-controlled workflow

DR-43 is implemented as `automation/n8n/workflows/dr-43-competitive-intelligence-shadow-ingest.json` with stable ID `DR43CompetitiveIntelligenceShadowV1`.

It is intentionally `active:false` and has OBSERVE authority only. The workflow is a reusable **shadow sink**, not an external collector. Future approved collectors may pass normalized observation batches into DR-43 only after their individual source has passed founder approval and source-specific terms/rate-limit review.

DR-43:

1. validates a 1–50 observation batch, UUIDs, allowed observation types, dedupe keys, object/array shapes, scores and timezone-aware timestamps;
2. reconstructs a bounded canonical body rather than forwarding arbitrary input fields;
3. signs the exact raw body using the existing `DROP_RATE_AUTOMATION_COMMAND_SECRET`;
4. derives the shadow-ingestion URL from the already governed automation-control URL, avoiding another secret or hard-coded backend host;
5. submits only to the signed FastAPI shadow endpoint;
6. refuses success unless the API confirms `accepted=true`, `mode=SHADOW`, `external_action_taken=false`, matching counts and matching dedupe keys;
7. records durable success through DR-91, while workflow failures route through DR-90.

The existing additive n8n startup provisioner will import the stable workflow when its ID is absent, but only because the committed JSON is explicitly inactive. It never overwrites an existing persistent workflow and this change does not activate DR-43.
