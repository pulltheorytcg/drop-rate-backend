# Drop Rate — Live Build Status

_Last updated: 23 September 2026_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification.

## Current progress

- **Full Drop Rate roadmap:** ~42%
- **Milestone 1 — Founder inventory control:** ~98%
- **Internal commerce / founder finance foundation:** ~80%
- **Milestone 2 — Shopify sale attribution:** intentionally deferred until Shopify store setup
- **Milestone 3 — Automated market valuation/pricing:** ~60%

## Current stage

**Core founder operations, internal finance, dashboard navigation and provider-neutral pricing/market-data infrastructure are live. Next work is final QA, import-review refinement and legitimate live provider adapters before Shopify.**

## Production-verified foundation

### Architecture / infrastructure
- GitHub private repository + CI
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI deterministic business layer
- Supabase authentication
- audit logging
- optimistic version protection
- browser security headers
- single-founder scope for current phase

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
Production navigation is now split into:

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
- no provider scraping assumed or enabled
- no live provider adapter enabled without legitimate access

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

## Milestone 1 checklist

| Requirement | Status |
|---|---|
| Login/authentication | ✅ Complete |
| Physical inventory model | ✅ Complete |
| Ownership | ✅ Complete |
| Manual add inventory | ✅ Complete |
| Import inventory files | ✅ Complete |
| Search/filter inventory | ✅ Complete |
| Acquisition cost | ✅ Complete |
| Purchase provenance | ✅ Complete |
| Card condition | ✅ Complete |
| Sealed/unsealed state | ✅ Complete |
| Grade/certificate | ✅ Complete |
| Language | ✅ Complete |
| Controlled physical locations | ✅ Complete |
| Stock audit/location counts | ✅ Complete |
| Final end-to-end regression QA | 🚧 Remaining |

## Founder dashboard modules

| Module | State |
|---|---|
| Dashboard overview | ✅ Structural view live; KPI/activity polish remains |
| Inventory | ✅ Live |
| Purchase Lots / cost basis | ✅ Live under Inventory |
| Storage Locations | ✅ Live under Inventory |
| Manual inventory intake | ✅ Live |
| Inventory imports | ✅ Live |
| Sales | ✅ Live foundation |
| Reports | ✅ Core finance metrics live |
| Balance | ✅ Live |
| Payout requests | ✅ Live |
| Settings / market pricing status | ✅ Live foundation |

## Supabase live capacity checkpoint

Checked after the market-ingestion deployment:

- organisation plan: **Free**
- PostgreSQL: **17.6**
- `tcg` tables: **22**
- foreign-key relationships: **35**
- database size: **~14 MB**
- direct database connection ceiling: **60**
- connections observed during check: **9**
- market observations: **0**
- pricing snapshots: **0**
- market ingestion runs: **0**

The schema itself is nowhere near a practical PostgreSQL table-count limit. The first expected storage pressure is append-only market evidence once automated provider ingestion begins.

The Supabase Schema Visualizer relationship between `tcg.owner_memberships.user_id` and `auth.users.id` is now enforced by a real foreign key. Visual node layout itself is Studio/browser UI state rather than database state.

Current Supabase advisor state:
- performance: only unused-index INFO notices expected on newly created / currently empty tables
- security: leaked-password protection remains disabled in Supabase Auth and should be enabled before production launch

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation continues |
| 2 | Database / authentication | ✅ Core complete |
| 3 | Founder account / inventory / ownership | ✅ Core complete; final regression QA remains |
| 4 | Inventory dashboard functionality | ✅ Core complete |
| 4.5 | Founder dashboard UX/navigation cleanup | ✅ Structural seller-portal navigation live; visual polish remains |
| 5 | Shopify integration | ⏸ Deferred until backend/pricing is clean and store exists |
| 6 | Orders / ownership allocation / settlements | 🚧 Core internal commerce/finance live; refinement remains |
| 7 | Market-data infrastructure | 🚧 Core + ingestion framework live; real provider adapters/access pending |
| 8 | Pricing engine | 🚧 Core deterministic engine live; automatic publication pending provider data + Shopify |
| 9 | AI card identification | ⬜ Not started |
| 10 | Consignment | ⬜ Not started |
| 11 | AI product listings | ⬜ Not started |
| 12 | AI customer service | ⬜ Not started |
| 13 | SEO | ⬜ Not started |
| 14 | AI marketing | ⬜ Not started |
| 15 | n8n orchestration | ⬜ Advanced workflows not started |
| 16 | Analytics / optimisation | ⬜ Not started |

## Resume here next session

1. Complete final Milestone 1 regression / failure QA.
2. Finish import candidate REVIEW-row resolution so unmatched imports can be manually corrected/matched.
3. Verify finance, refund, balance and payout workflows end to end with rollback-safe test scenarios.
4. Obtain/confirm legitimate provider access and implement live adapters one at a time.
5. Build source-mapping review tooling for live provider IDs.
6. Add scheduled market ingestion with purpose-built service authentication; n8n must only orchestrate backend APIs.
7. Add automatic repricing policy execution only after reliable live data exists.
8. Prepare Shopify integration after the backend/accounting/pricing loop is clean.

## Major deferred decisions / features

- Shopify storefront setup is not required yet.
- Canonical catalogue product → Shopify Product and physical inventory → Shopify Variant/SKU remains the intended mapping to validate during Shopify work.
- value-weighted Purchase Lot allocation waits for reliable market reference values.
- multi-founder ownership is deferred; current build remains single-founder.
- consignors/consignment come after the core founder sale loop.
- AI marketing, SEO automation and advanced n8n orchestration come after core inventory, commerce and pricing foundations.

## Completion rule

- **Coding only:** In Progress.
- **PR open / CI green:** In Progress.
- **Merged but not deployed:** In Progress.
- **Production deployment + health verification successful:** Completed.
