# Drop Rate — Live Build Status

_Last updated: 23 September 2026_

This file is the persistent project tracker for the Drop Rate build.
A feature only moves to **Completed** when it has been merged to `main`, deployed to production and production health has been verified.
Percentages are weighted estimates, not simple phase counts, and should be updated as scope becomes clearer.

## Current progress

- **Full Drop Rate roadmap:** ~22%
- **Milestone 1 — Founder inventory control:** ~75%
- **Milestone 2 — Shopify sale attribution:** 0%
- **Milestone 3 — Automated market valuation/pricing:** 0%

## Current stage

**Phase 3–4: Inventory foundation + founder inventory dashboard**

### In progress now

**Storage Locations + Stock Auditing**

Goal:
- replace free-form physical locations with a controlled location registry
- support codes such as `BINDER-01/PAGE-04`, `BOX-03/SLOT-18`, `SHELF-A/BIN-02`
- link every physical inventory item to a registered location
- bulk-assign selected inventory to a location
- filter inventory by location
- show inventory counts by location and an Unlocated count
- preserve audit history and optimistic version protection

## Successfully completed and production-verified

### Architecture / infrastructure
- Private GitHub repository: `pulltheorytcg/drop-rate-backend`
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI backend
- Supabase authentication
- GitHub Actions backend checks
- deterministic business logic kept in FastAPI/PostgreSQL rather than n8n
- audit logging foundation
- optimistic version protection for inventory changes

### Inventory foundation
- single-founder model for the current phase
- 328 inventory records loaded
- canonical catalogue product separated from physical inventory item
- unique inventory records and inventory codes
- acquisition cost stored independently from market/store price
- unknown acquisition cost remains `NULL`, never silently converted to £0
- acquisition date
- condition
- grading company / grade / certificate number
- language
- free-form location field (being replaced by registered Storage Locations)
- store price
- identity confirmation
- inventory status
- notes
- search and pagination
- Action Required filters
- approval readiness calculation
- inventory approval workflow

### Card condition / sealed inventory state
- TCGplayer raw-card condition scale standardised:
  - Near Mint
  - Lightly Played
  - Moderately Played
  - Heavily Played
  - Damaged
- database guard rejects unsupported raw-card condition values
- sealed/non-card merchandise supports dedicated `SEALED` / `UNSEALED` state
- language remains separate from condition
- production deployment verified healthy

### Acquisition cost / Purchase Lots
- bulk binder/set cost allocation
- exact penny allocation validation
- equal split allocation
- manual allocation
- Purchase Lot records
- purchase price, fees, shipping and landed cost
- source/seller, purchase date, currency and notes
- inventory-to-Purchase-Lot provenance
- Purchase Lot detail view
- Purchase Lot metadata editing with version protection
- add more selected inventory to an existing lot
- detach inventory safely from a lot
- detached acquisition cost/date return to `NULL`
- approved inventory returns to Draft if its purchase-cost provenance is removed
- cross-lot conflicts blocked
- lot total cannot be reduced below already allocated cost
- currency cannot change after inventory has been allocated
- value-weighted allocation intentionally deferred until the pricing engine has reliable reference values
- Purchase Lot v2 deployed and production-verified

## Milestone 1 checklist

Milestone 1 definition:
> Founder can log in, add physical cards, assign ownership, record acquisition cost/condition/grade/location, search inventory and see exactly what they own.

| Requirement | Status |
|---|---|
| Authentication/login | ✅ Complete |
| Single-founder ownership model | ✅ Complete |
| Existing physical inventory stored | ✅ Complete |
| Search inventory | ✅ Complete |
| Acquisition cost | ✅ Complete |
| Binder/set purchase cost allocation | ✅ Complete |
| Condition | ✅ Complete |
| Grade/certificate | ✅ Complete |
| Language | ✅ Complete |
| Purchase provenance | ✅ Complete |
| Controlled physical locations | 🚧 In progress |
| Stock audit/location counts | 🚧 In progress |
| Add a brand-new physical inventory item manually | ⬜ Not built |
| Final Milestone 1 production QA | ⬜ Not started |

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation continues |
| 2 | Database / authentication | ✅ Core complete |
| 3 | Founder account / inventory / ownership | 🚧 Mostly complete |
| 4 | Inventory dashboard | 🚧 Mostly complete |
| 5 | Shopify integration | ⬜ Not started |
| 6 | Orders / ownership allocation / settlements | ⬜ Not started |
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

1. Finish Storage Locations + Stock Auditing.
2. Build manual single-item inventory intake so a new physical card/product can be added cleanly.
3. Run Milestone 1 end-to-end QA and close remaining inventory foundation gaps.
4. Start Milestone 2: Shopify integration.
5. Implement APPROVED inventory → Shopify product/variant synchronisation.
6. Implement verified, idempotent Shopify order/refund/cancellation webhooks.
7. Link Shopify order item → physical Inventory ID → deterministic sale attribution.
8. Only after the Shopify sale loop works, begin market-data infrastructure and pricing.

## Major deferred decisions / features

- **Card → Shopify Product / physical Inventory → Shopify Variant** is still a deliberate architectural decision to validate before Shopify sync implementation.
- value-weighted Purchase Lot allocation waits for reliable market reference values.
- multi-founder ownership is deferred; current build is single-founder.
- consignors/consignment are deferred until the core founder sale loop works.
- AI marketing, SEO automation and advanced n8n orchestration come after core inventory, Shopify and pricing foundations.

## Completion rule

For future status updates:

- **Coding only:** remains In Progress.
- **PR open / CI green:** remains In Progress.
- **Merged but not deployed:** remains In Progress.
- **Production deployment + health verification successful:** move to Completed and update percentages.
