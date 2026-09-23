# Drop Rate — Live Build Status

_Last updated: 23 September 2026_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification.

## Current progress

- **Full Drop Rate roadmap:** ~46%
- **Milestone 1 — Founder inventory control:** ~99% technically complete; final regression QA + data cleanup remain
- **Internal commerce / founder finance foundation:** ~82%
- **Milestone 2 — Shopify sale attribution:** not started against live Shopify yet; internal deterministic finance foundation exists
- **Milestone 3 — Automated market valuation/pricing:** ~70% technically complete; live provider validation remains the current gate

## Current stage

**Close-out / regression chapter for the core backend.**

The founder inventory, import, purchase-lot, storage, audit, internal finance, market-data and pricing foundations are live. Current work is deliberately focused on:

1. finishing live eBay/Parse diagnostics;
2. verifying every completed core workflow for regressions and failure handling;
3. correcting any defects found before starting Shopify integration;
4. deferring inventory cost cleanup to the next working session.

## Production-verified foundation

### Architecture / infrastructure
- private GitHub repository + PR workflow
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI deterministic business layer
- Supabase authentication
- audit logging
- optimistic version protection
- browser security headers
- single-founder scope for current phase
- provider adapters kept separate from deterministic pricing logic
- n8n intentionally not used as database or core business-logic layer

### Inventory
- canonical catalogue separated from physical inventory
- unique physical Inventory IDs
- search / filters / pagination
- Action Required workflow
- acquisition cost/date with unknown cost preserved as NULL
- Purchase Lots, fees, shipping and landed-cost allocation
- raw-card TCGplayer condition scale
- sealed/unsealed inventory state
- grading company / grade / certificate
- language
- registered Storage Locations + stock audit
- manual single-item intake with idempotency
- unified CSV import framework
- Collectr / eBay Purchases / HoloDex / Generic CSV presets
- conservative catalogue matching with REVIEW state for ambiguous rows
- raw import provenance and SHA-256 duplicate-file protection
- approval workflow
- manual import REVIEW-row resolution now live:
  - search canonical catalogue
  - explicitly select the correct match
  - skip invalid/unwanted source rows
  - preserve unrelated physical-data validation issues
  - batch version protection prevents stale review actions
- persisted import JSONB is decoded safely before final inventory commit

### Internal commerce / founder finance
- internal orders and physical order items
- acquisition-cost snapshot at sale time
- SOLD inventory state
- append-only owner financial ledger
- revenue / COGS / gross profit / net profit
- payment/platform fees
- shipping income / shipping cost
- refund/return foundation
- deterministic penny-perfect allocation
- pending / available / reserved / paid-out balances
- payout request + cancellation workflow
- no automatic money movement
- manual/off-platform sale support before Shopify

### Founder seller portal
Production navigation is split into:

- **Dashboard**
- **Inventory**
- **Sales**
- **Reports**
- **Balance**
- **Settings**

Existing working inventory/finance components were reorganised rather than rewritten. URL hashes such as `#inventory` and `#balance` are supported.

### Market-data infrastructure
- provider-neutral source mappings
- supported source slots: eBay, Collectr, TCGplayer, Cardmarket
- VERIFIED mapping gate before automatic ingestion
- immutable historical market observations
- observation deduplication by `(source, source_record_key)`
- source / condition / grade / language / seal-state normalization fields
- GBP-normalized values + FX provenance fields
- provider-neutral adapter protocol + registry
- immutable market-ingestion run history
- per-run fetched / inserted / duplicate / failed-mapping counts
- market provider health/status API
- dashboard Settings visibility for mapping count, observation count and latest run status
- permitted Parse API integration configured for live provider access
- eBay UK Parse adapter implemented with separate sold / active pathways
- UK pricing guardrail requires UK/EU anchor evidence before trusted displayed Market Value
- TCGplayer / Collectr remain supporting evidence rather than sole UK Market Value anchors
- no raw provider response is allowed to silently overwrite deterministic pricing state

### Live eBay / Parse diagnostic status
Current production state after PRs #23–#26:

- Parse authentication is working with the current `pmx_...` API key
- five-card smoke matrix stays within current request-rate constraints by using sold evidence only
- all five smoke requests now complete through the Drop Rate endpoint with HTTP 200
- prior idle-in-transaction timeout on the graded Charizard case is fixed
- provider calls no longer wait while a PostgreSQL transaction remains open
- smoke-run timestamps now use the database clock and diagnostic rows persist correctly
- eBay title matching now tolerates punctuation and seller word-order variation while keeping identity tokens exact
- latest smoke run still returned **0 accepted observations for all five cases**
- no observations, pricing snapshots or Store Prices were written by smoke testing
- PR #26 adds safe Parse response diagnostics showing returned keys, list counts and sample titles without logging credentials, request headers or raw response bodies
- **Next gate:** run the five-card smoke matrix once with PR #26 live, inspect Railway diagnostics, then fix the precise response-shape/query/filter issue rather than loosening matching blindly

### Pricing engine
- robust source-level weighted pricing rather than simple average
- sold vs active-listing weighting
- recency weighting / half-life logic
- comparability by condition / grading / language / seal state
- outlier handling
- volatility and confidence calculation
- source-count and evidence-quality weighting
- outputs:
  - Market Value
  - Recommended Retail
  - Quick-Sale Price
  - Target Acquisition Price
- immutable pricing snapshots
- pricing policy configuration
- high-value / low-confidence / volatile-price review guards
- batch and single-item recalculation API
- pricing history API
- latest pricing outputs visible in Settings
- **Store Price is never silently overwritten by pricing calculation**

## Current live inventory readiness

Production checkpoint on 23 September 2026:

- physical inventory items: **328**
- status: **328 DRAFT**
- unknown acquisition cost: **326**
- missing condition: **10**
- missing storage location: **328**
- missing Store Price: **328**
- identity not yet confirmed: **328**
- largest known cleanup group: **178 Phantasmal Flames items**, currently all with unknown acquisition cost

Inventory-cost allocation is deliberately deferred until the next working session. Unknown cost must remain NULL until deliberately assigned.

## Known data-quality items

- One Piece catalogue currently contains both `Carrying On His Will` and `Carrying on His Will`; normalize this carefully in the catalogue-quality pass rather than silently merging records without verifying identities/references.
- packaged One Piece smoke-test cases remain blocked until physical `seal_status` is confirmed.
- Supabase leaked-password protection remains disabled and must be enabled before launch.

## Milestone 1 checklist

| Requirement | Status |
|---|---|
| Login/authentication | ✅ Complete |
| Physical inventory model | ✅ Complete |
| Ownership | ✅ Complete |
| Manual add inventory | ✅ Complete |
| Import inventory files | ✅ Complete |
| Manual import REVIEW resolution | ✅ Complete |
| Search/filter inventory | ✅ Complete |
| Acquisition cost model | ✅ Complete |
| Purchase provenance | ✅ Complete |
| Card condition | ✅ Complete |
| Sealed/unsealed state | ✅ Complete |
| Grade/certificate | ✅ Complete |
| Language | ✅ Complete |
| Controlled physical locations | ✅ Complete |
| Stock audit/location counts | ✅ Complete |
| Approval/readiness workflow | ✅ Complete |
| Final end-to-end regression QA | 🚧 In progress |
| Production inventory data cleanup | 🚧 Operational task; code largely complete |

## Founder dashboard modules

| Module | State |
|---|---|
| Dashboard overview | ✅ Structural view live; KPI/activity polish remains |
| Inventory | ✅ Live |
| Purchase Lots / cost basis | ✅ Live under Inventory |
| Storage Locations | ✅ Live under Inventory |
| Manual inventory intake | ✅ Live |
| Inventory imports | ✅ Live, including manual review resolution |
| Sales | ✅ Live foundation |
| Reports | ✅ Core finance metrics live |
| Balance | ✅ Live |
| Payout requests | ✅ Live |
| Settings / market pricing status | ✅ Live foundation |
| Live market smoke tests | 🚧 Live diagnostic workflow working; eBay evidence acceptance still unresolved |

## Supabase live checkpoint

Current known state:

- project: `pull-theory-dev`
- region: `eu-west-2`
- PostgreSQL: **17.6**
- physical inventory: **328**
- market observations: **0**
- pricing snapshots: **0**
- live eBay smoke diagnostic runs are now persisting successfully

Earlier capacity checkpoint found 22 `tcg` tables, 35 foreign-key relationships and ~14 MB database size. The schema is comfortably within normal PostgreSQL capacity; append-only market evidence is the expected future storage-growth area.

The Supabase Schema Visualizer relationship between `tcg.owner_memberships.user_id` and `auth.users.id` is enforced by a real foreign key. Visual node layout itself is Studio/browser UI state rather than database state.

Current Supabase advisor/security note:
- performance: unused-index INFO notices are expected on newly created / currently empty tables
- security: leaked-password protection should be enabled before production launch

## Core regression / close-out checklist

The current chapter is not considered closed until these are verified against production behaviour and/or focused tests:

### Authentication / security
- authenticated routes reject unauthenticated requests
- owner-scoped queries do not leak another owner's records
- RLS / application owner checks remain consistent
- secrets never appear in logs, URLs or API responses
- stale/version-conflict requests fail safely

### Inventory
- manual add is idempotent
- unknown acquisition cost stays NULL, never coerced to £0
- edit flow preserves version protection
- Action Required filters are correct
- identity confirmation / approval transitions are valid
- storage assignment and stock-audit counts remain correct
- ownership cannot be silently changed through unrelated edits

### Purchase lots / cost allocation
- total cost = purchase price + fees + shipping
- equal / manual allocation remains penny-perfect
- assignment cannot double-allocate items incorrectly
- unknown values remain unknown until deliberate assignment
- full operational cost cleanup is deferred until next session

### Imports
- duplicate-file SHA protection works
- ambiguous/unmatched rows remain REVIEW
- manual catalogue resolution only clears identity-related issues
- invalid physical data remains Action Required
- skipped rows do not create inventory
- stale batch version fails safely
- commit creates the correct number of physical inventory items
- raw source provenance remains intact

### Internal sales / finance
- one physical inventory item cannot be sold twice
- sale snapshots acquisition cost correctly
- owner ledger remains append-only
- fees / shipping / COGS / profit are deterministic
- refund/return paths reverse the correct financial effects
- payout reserve / cancel / paid-out states reconcile exactly
- repeated/idempotent actions do not duplicate financial entries

### Market data / pricing
- live eBay diagnostic root cause resolved
- strict identity guard prevents wrong variants/grades/proxies from entering evidence
- smoke tests never persist observations
- real ingestion is immutable and deduplicated
- UK/EU anchor rule prevents unsupported UK Market Value
- low-confidence / insufficient-data cases enter Action Required rather than inventing a price
- Store Price is never silently changed by market recalculation

### Production / deployment
- Railway health/readiness remains green
- startup succeeds from clean deployment
- latest GitHub main commit matches production deployment
- Supabase migration history matches repository migrations
- no pending/staged Railway configuration changes are left unintentionally

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation continuously updated |
| 2 | Database / authentication | ✅ Core complete; pre-launch auth hardening remains |
| 3 | Founder account / inventory / ownership | 🚧 Core complete; final regression + operational cleanup remain |
| 4 | Inventory dashboard functionality | ✅ Core complete |
| 4.5 | Founder dashboard UX/navigation cleanup | ✅ Structural seller-portal navigation live; visual polish remains |
| 5 | Shopify integration | ⬜ Next major build after current close-out chapter |
| 6 | Orders / ownership allocation / settlements | 🚧 Internal deterministic foundation live; Shopify event integration + final QA remain |
| 7 | Market-data infrastructure | 🚧 Core framework + eBay live diagnostic path live; provider validation remains |
| 8 | Pricing engine | 🚧 Core deterministic engine live; trusted live evidence + automatic execution remain |
| 9 | AI card identification | ⬜ Not started |
| 10 | Consignment | ⬜ Not started |
| 11 | AI product listings | ⬜ Not started |
| 12 | AI customer service | ⬜ Not started |
| 13 | SEO | ⬜ Not started |
| 14 | AI marketing | ⬜ Not started |
| 15 | n8n orchestration | ⬜ Advanced workflows not started |
| 16 | Analytics / optimisation | ⬜ Not started |

## Immediate work order

### Today — close the current chapter
1. Run PR #26 live eBay diagnostics and identify the exact provider-result/matcher failure.
2. Fix and re-test until at least representative raw and graded eBay cases can produce correctly matched smoke evidence without persistence.
3. Work backwards through the core regression checklist above.
4. Fix defects found through small, isolated PRs with tests.
5. Re-run production health / Supabase integrity checks.
6. Update this document again with the final close-out state.

### Next session
1. Review physical inventory and confirm card identities.
2. Create/assign storage locations.
3. Allocate acquisition costs, starting with the 178-card Phantasmal Flames group / binder workflow.
4. Resolve the remaining 10 missing conditions.
5. Prepare approved inventory for the Shopify milestone.

### Next major engineering milestone
**Shopify integration:** approved inventory → Shopify product/SKU → Shopify order/refund/cancellation webhooks → deterministic inventory attribution and financial allocation, with webhook signature verification and idempotency.

## Major deferred decisions / features

- multi-founder ownership remains deferred; current build stays single-founder
- consignors/consignment come after the founder sale loop
- AI identification comes after core commerce/pricing reliability
- AI marketing, SEO automation and advanced n8n orchestration come after inventory, Shopify, settlement and market pricing foundations
- value-weighted Purchase Lot allocation waits for reliable market reference values
- no automatic money movement until settlement reporting is thoroughly verified

## Completion rule

- **Coding only:** In Progress.
- **PR open / CI green:** In Progress.
- **Merged but not deployed:** In Progress.
- **Production deployment + health verification successful:** Completed.
