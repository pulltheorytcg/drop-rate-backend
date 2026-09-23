# Drop Rate — Live Build Status

_Last updated: 23 September 2026_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification.

## Current progress

- **Full Drop Rate roadmap:** ~34%
- **Milestone 1 — Founder inventory control:** ~98%
- **Internal commerce / founder finance foundation:** ~70%
- **Milestone 2 — Shopify sale attribution:** intentionally deferred until Shopify store setup
- **Milestone 3 — Automated market valuation/pricing:** 0%

## Current stage

**Founder operations platform: inventory foundation complete; functionality QA + commerce/finance refinement in progress**

## In progress now

1. Final Milestone 1 end-to-end QA
2. Import review / unmatched-row resolution refinement
3. Founder finance and commerce workflow verification
4. Refund / fee / shipping / settlement workflow refinement
5. Founder dashboard functional verification

## Successfully completed and production-verified

### Architecture / infrastructure
- GitHub private repository
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI backend
- Supabase authentication
- GitHub Actions CI
- audit logging foundation
- optimistic version protection
- deterministic business rules in FastAPI/PostgreSQL

### Inventory foundation
- canonical catalogue separated from physical inventory
- unique physical Inventory IDs
- single-founder ownership model for current phase
- inventory search, filters and pagination
- Action Required workflow
- acquisition cost and acquisition date
- unknown cost remains NULL, never silently £0
- store price
- identity confirmation
- notes/status
- TCGplayer raw-card condition scale
- SEALED / UNSEALED state for sealed products
- grading company / grade / certificate
- language
- approval readiness and approval workflow
- Purchase Lots with purchase price, fees, shipping and landed cost
- equal/manual binder allocation
- Purchase Lot management v2
- registered Storage Locations
- stock location filtering and Unlocated counts
- manual single-item inventory intake
- duplicate-safe idempotent manual intake
- unified CSV inventory import framework
- Collectr / eBay Purchases / HoloDex / Generic CSV presets
- conservative catalogue matching; ambiguous rows enter Review
- raw source row + SHA-256 file provenance

### Internal commerce / founder finance
- internal orders
- physical order items
- acquisition-cost snapshots at sale time
- SOLD inventory state
- append-only financial ledger
- sales revenue entries
- platform/payment fees
- shipping revenue and shipping cost
- refunds and adjustments foundation
- deterministic penny-perfect fee/shipping allocation
- manual/off-platform sale API for testing before Shopify
- founder finance summary
- sales revenue
- COGS
- gross/net profit
- pending balance
- available balance
- reserved payout balance
- paid-out balance
- recent sales
- payout request workflow
- payout cancellation workflow
- no automatic money movement
- Balance & Profit dashboard section
- Recent Sales dashboard section
- Payout Requests dashboard section

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
| Final end-to-end production QA | 🚧 In progress |

## Founder dashboard modules

| Module | Functional state | UX state |
|---|---|---|
| Dashboard overview | 🚧 Needs final KPI/activity composition | 🚧 Redesign planned |
| Inventory | ✅ Live | 🚧 Redesign planned |
| Purchase Lots / cost basis | ✅ Live | 🚧 Move under Inventory/Purchases |
| Storage Locations | ✅ Live | 🚧 Move under Inventory |
| Manual inventory intake | ✅ Live | 🚧 Move under Inventory |
| Inventory imports | ✅ Live | 🚧 Move under Inventory |
| Sales | ✅ Backend + recent sales UI | 🚧 Dedicated Sales tab planned |
| Reports | ✅ Core finance metrics available | 🚧 Dedicated Reports tab planned |
| Balance | ✅ Backend + payout UI | 🚧 Dedicated Balance tab planned |
| Payout requests | ✅ Live | 🚧 Move under Balance |
| Settings / integrations | ⬜ Future | ⬜ Future |

## Planned dashboard UX / information architecture phase

**Do this only after the current functional QA pass.** Do not redesign core workflows while their business logic is still being verified.

Target founder/seller portal navigation:

1. **Dashboard**
   - available/pending balance summary
   - revenue / net profit snapshot
   - stock count/value snapshot
   - Action Required queue
   - recent sales/activity
   - quick actions

2. **Inventory**
   - all stock
   - add inventory manually
   - import inventory
   - Purchase Lots / acquisitions
   - Storage Locations
   - stock audit
   - condition / grade / sealed-state review

3. **Sales**
   - orders
   - sold physical items
   - order details
   - refunds / returns
   - sale attribution

4. **Reports**
   - revenue
   - gross profit / net profit
   - COGS
   - platform/payment fees
   - shipping income and shipping cost
   - sell-through and inventory performance later
   - date-range reporting / exports later

5. **Balance**
   - pending balance
   - available balance
   - reserved balance
   - total paid out
   - payout request
   - payout history
   - settlement details

6. **Settings** (later)
   - account/profile
   - Shopify integration
   - import/integration settings
   - commission / business configuration where permitted

UX rules:
- do not put every business function on one scrolling page
- top-level navigation/tabs should change views without duplicating business logic
- mobile/responsive navigation required
- preserve browser security headers and auth/session handling
- Action Required should surface on Dashboard but deep-link to the relevant workflow
- financial figures must come only from the deterministic ledger
- no placeholder/fake metrics

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation continues |
| 2 | Database / authentication | ✅ Core complete |
| 3 | Founder account / inventory / ownership | ✅ Core complete; final QA in progress |
| 4 | Inventory dashboard functionality | ✅ Core complete; final QA in progress |
| 4.5 | Founder dashboard UX/navigation cleanup | ⬜ Planned after functionality QA |
| 5 | Shopify integration | ⏸ Deferred until store exists and backend is ready |
| 6 | Orders / ownership allocation / settlements | 🚧 Internal commerce foundation built; refining |
| 7 | Market-data infrastructure | ⬜ Not started |
| 8 | Pricing engine | ⬜ Not started |
| 9 | AI card identification | ⬜ Not started |
| 10 | Consignment | ⬜ Not started |
| 11 | AI product listings | ⬜ Not started |
| 12 | AI customer service | ⬜ Not started |
| 13 | SEO | ⬜ Not started |
| 14 | AI marketing | ⬜ Not started |
| 15 | n8n orchestration | ⬜ Advanced workflows not started |
| 16 | Analytics / optimisation | ⬜ Not started |

## Immediate next work

1. Complete final inventory foundation end-to-end QA.
2. Verify finance calculations, balances, payouts and sale state transitions end to end.
3. Finish import candidate review / row-resolution workflow.
4. Refine refunds, fees, shipping and settlement workflows.
5. Run failure/security tests across inventory + finance.
6. Build the founder dashboard top-navigation/tab redesign.
7. Only after the backend and dashboard are clean, prepare Shopify integration when the Shopify store exists.
8. Then move into market-data infrastructure and pricing.

## Major deferred decisions / features

- Shopify storefront/store setup is not required yet.
- Canonical Card/Product → Shopify Product and Physical Inventory → Shopify Variant remains the planned mapping to validate when Shopify work begins.
- value-weighted Purchase Lot allocation waits for reliable market reference values.
- multi-founder ownership is deferred; current build is single-founder.
- consignors/consignment come after the core founder sale loop.
- AI marketing, SEO automation and advanced n8n orchestration come after core inventory, commerce and pricing foundations.

## Completion rule

- **Coding only:** In Progress.
- **PR open / CI green:** In Progress.
- **Merged but not deployed:** In Progress.
- **Production deployment + health verification successful:** Completed.
