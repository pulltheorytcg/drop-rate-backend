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

This is intentionally persistence-agnostic in the first slice. Canonical Postgres tables/API contracts come next, through a reviewed migration, before any n8n collection workflow can become active.
