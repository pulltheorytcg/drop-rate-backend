# Drop Rate — Live Build Status

_Last updated: 24 September 2026_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification where applicable.

## Current progress

- **Full Drop Rate roadmap:** ~49%
- **Milestone 1 — Founder inventory control:** ~99% technically complete; remaining work is mainly operational inventory cleanup + one pre-launch auth setting
- **Internal commerce / founder finance foundation:** ~85%
- **Milestone 2 — Shopify sale attribution:** guarded Shopify product/webhook/order/refund foundation is live; the remaining milestone proof is one controlled real sale/refund with exact physical-item and finance-ledger verification
- **Milestone 3 — Automated market valuation/pricing:** ~80% technically complete; provider ingestion remains intentionally gated until source-by-source production approval/validation

## Current stage

**Controlled commerce verification: ACTIVE — hardening gates are now enforced before the first real Shopify sale test.**

The latest pass exposed an important process improvement: we were testing individual features well, but not performing a sufficiently explicit system-level regression/review after every cluster of changes. From this point forward, every material feature is subject to a repeatable quality gate covering code tests, failure-path review, database invariants, migration reproducibility, production deployment/health and live-data verification.

The current backend is intentionally fail-closed: identity confirmation is required before pricing/listing, Shopify bulk publishing is disabled, market-data persistence is disabled, and no automatic money movement is enabled.

The next working session remains operational inventory work, but Shopify engineering will not advance past controlled testing until the quality gates below have passed for the full sale path.

## Production-verified foundation

### Architecture / infrastructure
- private GitHub repository + branch / PR / CI workflow
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI deterministic business layer
- Supabase authentication
- audit logging
- optimistic version protection
- browser security headers
- single-founder scope for current phase
- provider adapters separated from deterministic pricing logic
- n8n intentionally not used as database or core business-logic layer
- `database/migrations/**` is the canonical version-controlled migration directory
- legacy `migrations/**` is frozen historical material; new migrations must not be added there
- Supabase-native migration history is the authoritative applied-migration ledger

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
- manual single-item intake
- manual intake idempotency now validates payload identity: same key + same payload replays; same key + different payload returns conflict
- unified CSV import framework
- Collectr / eBay Purchases / HoloDex / Generic CSV presets
- conservative catalogue matching with REVIEW state for ambiguous rows
- raw import provenance and SHA-256 duplicate-file protection
- manual import REVIEW-row resolution
- approval/readiness workflow
- persisted JSON/JSONB is decoded consistently at the asyncpg connection boundary
- PostgreSQL now enforces physical-state invariants regardless of write path
- SOLD/historical mutation failures are returned as safe conflict responses rather than generic server errors

### Purchase lots / storage
- deterministic total landed cost = purchase price + fees + shipping
- equal/manual allocation support
- penny-perfect allocation
- registered `storage_location_id` is now the canonical approval/readiness location gate; the legacy text `location` field is synchronized from the registered location
- unnecessary `DELETE` permission on purchase lots was removed from the application role
- missing application-role UPDATE grants for newer inventory fields were fixed, including storage, purchase-lot, seal-state and pricing-output fields

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
- duplicate/repeated actions protected by source/reference uniqueness and idempotent paths

### Founder seller portal
Production navigation is split into:

- **Dashboard**
- **Inventory**
- **Sales**
- **Reports**
- **Balance**
- **Settings**

Existing working inventory/finance components were reorganised rather than rewritten. URL hashes such as `#inventory` and `#balance` are supported.

## Market-data infrastructure

### Core market framework
- provider-neutral source mappings
- supported source slots: eBay, Cardmarket, TCGplayer, Collectr
- VERIFIED mapping gate before automatic ingestion
- immutable historical market observations
- observation deduplication by `(source, source_record_key)`
- source / condition / grade / language / seal-state normalization fields
- GBP-normalized values + FX provenance fields
- provider-neutral adapter registry
- immutable market-ingestion run history
- provider health/status API
- deterministic pricing engine remains separate from provider access
- no raw provider response can silently overwrite Store Price
- UK pricing guardrail requires UK/EU anchor evidence for trusted displayed Market Value
- TCGplayer / Collectr remain supporting evidence rather than sole UK Market Value anchors

### Market hardening completed in this chapter
- Parse authentication verified with the current production key
- safe provider error messages do not expose credentials or raw response bodies
- smoke/provider diagnostics are authenticated and non-persistent
- provider calls no longer hold a PostgreSQL transaction open while waiting on external HTTP
- real ingestion was refactored to avoid the same idle-in-transaction failure class
- diagnostic run timestamps use the database clock
- diagnostic run logging persists correctly
- Parse snapshot pinning is optional; current canonical releases can be used deliberately
- eBay retrieval queries were broadened while post-retrieval identity acceptance remains strict
- title matching tolerates punctuation / seller word order without weakening hard card/variant/grade identity checks
- real production ingestion is **explicitly gated off by default**; presence of a Parse key alone cannot enable persistence
- provider probe counts the provider-specific result collection instead of the largest array in the response

### Final cross-provider live validation
Final production probe on 23 September 2026:

| Source / endpoint | Result | Interpretation |
|---|---:|---|
| eBay UK active | **72 listings** | ✅ live provider access working |
| eBay UK sold | **0 listings** | ⚠️ isolated upstream sold-search issue; Drop Rate receives an empty provider array before matching |
| TCGPlayer search | **10 cards** | ✅ live provider access working |
| Collectr search | **30 items** | ✅ live provider access working |
| Cardmarket search | earlier probe: **29 results** | ✅ provider previously validated; final run did not emit a response-shape line and should be rechecked before production ingestion |

Important conclusions:
- Drop Rate's provider plumbing is working; the system is not generally blocked on market APIs.
- eBay's active path works, while the Parse/eBay UK sold path currently returns an empty `items` array before Drop Rate filtering.
- Cardmarket is the strongest currently validated UK/EU pricing-anchor candidate, but production ingestion remains gated until source access/terms and live contract are approved.
- TCGPlayer and Collectr can provide supporting/global evidence after source-specific ingestion re-validation.
- eBay sold should be treated as an independent provider issue rather than blocking the rest of the platform.

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
- graded-card comparison now treats grading company + grade as the condition dimension rather than incorrectly requiring a raw marketplace condition too
- current pricing algorithm version after that correction: `drop-rate-market-v4`

## Current live inventory readiness

Production checkpoint on 24 September 2026:

- physical inventory items: **509**
- status: **508 DRAFT / 1 APPROVED**
- unknown acquisition cost: **0**
- missing condition: **10**
- missing storage location: **507** (Baltoy is in `ROOM-BOX`; approved Seel test candidate is in `ROOM-BOX/BINDER-01`)
- missing Store Price: **508**
- identity not yet confirmed: **508**
- missing owner: **0**
- missing catalogue reference: **0**
- duplicate Inventory IDs: **0**
- language: **1 English / 96 Japanese / 412 unknown/review required**
- portfolio acquisition cost basis: **£951.83 total (£1.87 per physical unit)**
- largest known cleanup group: **178 Phantasmal Flames items**

Acquisition cost is now populated for the current imported portfolio. Future unknown costs must still remain NULL until deliberately assigned.

### Language evidence correction — production verified

A production audit found that all **413** rows previously marked English had been changed from `NULL → English` in one unsupported bulk operation. None of those 413 source records contained explicit English evidence, while all **96 Japanese** rows contained explicit JP/Japanese evidence.

The unsupported English backfill was therefore rolled back fail-closed:
- inventory: **0 English / 413 unknown / 96 Japanese**
- affected catalogue identities: **373** changed from English to unknown
- audit trail: **413 inventory + 373 catalogue** English→NULL events under migration request `migration:20260924220735_revert_unsupported_english_language_backfill`
- current Collectr importer already sends missing language to REVIEW and does **not** infer English
- Shopify links/listings/reservations remained **0** throughout the correction

The first physical test candidate, Baltoy `INV-041416049F4249C6BB29A846E29DDC37`, remains **DRAFT**. Near Mint condition and physical location `ROOM-BOX` are retained, but identity confirmation was revoked after the imported `Ninja Spinner 046/083 + English` combination failed external identity validation. Its Store Price remains NULL and it has not been published to Shopify.

The controlled Shopify candidate is now Seel `INV-06F489A853594CDC80E418271933D044`:
- canonical identity: **Seel / Phantasmal Flames / 021/094 / Normal / English**
- physical condition: **Near Mint**
- registered storage: **ROOM-BOX/BINDER-01**
- acquisition cost: **£1.87**
- manual controlled-test Store Price: **£0.49**
- status: **APPROVED**
- identity confirmation: **physically verified**
- current inventory version: **6**
- this is the **only APPROVED inventory item**
- Shopify link still absent; no external product has been created yet

## Supabase live checkpoint

Current production data after the latest hardening + language pass:

- project: `pull-theory-dev`
- region: `eu-west-2`
- PostgreSQL: **17.6**
- physical inventory: **509**
- market observations: **0**
- pricing snapshots: **0**
- market ingestion/diagnostic runs: **25**
- audit events: **3,562**
- active Shopify inventory links: **0**
- marketplace listings: **0**
- active reservations: **0**
- identity confirmations: **0**
- RLS remains enabled across operational business tables; `tcg.schema_migrations` is the known exception and currently grants only `SELECT` to `tcg_api`
- provider diagnostics have **not** polluted market observations, pricing snapshots or inventory values

Supabase security advisor status:
- database/security configuration reviewed during this chapter
- leaked-password protection is still disabled and remains a **manual pre-launch Auth setting** to enable in Supabase
- `tcg.schema_migrations` currently has RLS disabled; current grants were checked and only `tcg_api` has `SELECT`. Do not enable RLS blindly without a migration-tooling policy.
- currently-unused-index notices are expected on newly created / low-row-count modules and are not being removed prematurely

## Regression / hardening work completed

The following areas were reviewed and defects found were corrected:

### Authentication / security
- authenticated dashboard/API routes verified in production
- owner/catalogue integrity checked in live inventory
- RLS coverage reviewed
- provider credentials kept out of logs and API responses
- historical/immutable mutation errors normalized safely
- application-role privileges reviewed and tightened

### Inventory / imports
- unknown acquisition cost remains NULL
- inventory-code uniqueness verified
- manual intake idempotency strengthened against key reuse with different payloads
- import REVIEW resolution completed
- JSONB decode path fixed for import commit and generalized at DB connection boundary
- physical-state database invariants added/verified
- live inventory contains zero physical-state invariant violations
- unsupported historical English-language backfill identified from audit history and rolled back to unknown without altering the 96 evidence-backed Japanese items
- Baltoy physical verification trail preserved as CONFIRMED then REVOKED after catalogue/language conflict discovery; physical condition and storage remain intact

### Purchase lots / storage
- approval/readiness now requires the canonical registered Storage Location, matching the Shopify test-sync gate
- application-role UPDATE permissions corrected for newer columns
- purchase-lot DELETE privilege removed

### Finance
- append-only / uniqueness protection reviewed
- SOLD-state protections reviewed
- refund/payout/ledger foundations retained
- database conflict failures no longer fall through as generic 500s where historical mutation is rejected

### Market / pricing
- provider transaction boundary fixed in smoke tests and real ingestion
- ingestion-run logging fixed
- flexible-but-strict eBay identity matching added
- provider-response diagnostics added
- production-ingestion safety gate added
- guarded Shopify single-item readiness now exposes exact blockers and uses the same eligibility function as the actual publish action
- registered storage location is enforced consistently by approval/readiness and Shopify sync
- graded comparable-condition bug fixed
- cross-provider live access validated as recorded above

### Deployment / reproducibility
- Railway production service remains `drop-rate-api-live`
- latest production deployment for the language-correction release is **SUCCESS** on commit `6d44f74f6b9bc734d26d0c52bef0ef75e18dddaa`; `/health/ready` returned **200 OK**
- PR and post-merge GitHub CI are green for the latest hardening commits
- Railway production has a **pre-deploy compile + pytest gate**; the missing `pytest-asyncio` dependency was fixed after deployment logs exposed 43 silently skipped async tests
- Railway now installs pinned **Node 22.23.3 LTS** alongside Python through `RAILPACK_PACKAGES`, so frontend/static checks run in the production pre-deploy gate too
- current Railway regression result: **369 passed, 0 skipped**; `/health/ready` returned **200 OK** after deployment
- live database integrity checks: **0 duplicate Inventory Codes, 0 language mismatches, 0 confirmed-without-evidence, 0 active-reservation/state mismatches**
- migration history reconciled: `normalize_explicit_card_languages` is present as `20260924195341`, and the production language correction is recorded exactly as `20260924220735_revert_unsupported_english_language_backfill`
- `database/migrations/**` is now the only canonical location for new migration files
- Railway `Wait for CI` still reads **OFF** (`checkSuites=false`) after two attempted staged updates; treat this as an external Railway/GitHub-integration permission/configuration blocker until the setting can be re-authorised and verified
- the guarded Supabase migration workflow is merged (`workflow_dispatch`, dry-run by default, explicit apply mode). Its required GitHub secrets and first production dry-run still need to be verified before the next schema change
- no unintended staged Railway configuration remains

## Quality / regression gate

A feature is not considered complete merely because its unit tests pass. For material changes, the following gates are now mandatory:

1. **Design review:** what is changing, why it belongs, dependencies, failure modes and exact test plan are recorded before implementation.
2. **Automated regression:** targeted tests plus the full backend suite must pass.
3. **Security / integrity review:** RLS/permissions, ownership boundaries, idempotency, concurrency and immutable/audit behaviour are checked where relevant.
4. **Migration review:** every database change has a version-controlled migration in `database/migrations/**`; production migration history must match the repository.
5. **Production deployment:** Railway deployment succeeds and health/readiness is verified.
6. **Live invariants:** production queries verify counts, uniqueness, state transitions and cross-table relationships after deployment or data mutations.
7. **Failure testing:** deliberate bad inputs, duplicate events, stale versions, unavailable records and provider failures are tested before a feature is treated as safe.
8. **Release decision:** any unresolved critical integrity issue keeps the feature gated, even when CI is green.

Current production regression baseline: **369 passed, 0 skipped** in Railway pre-deploy; GitHub PR and main-branch CI are green. Live inventory integrity currently reports zero duplicate Inventory Codes, zero language/catalogue mismatches, zero identity confirmations without evidence, zero active reservation/state mismatches, zero active Shopify links and zero marketplace listings.

GitHub status checks can be required on protected branches, but the current connector does not expose this repository's branch-protection configuration. Verify that setting in GitHub before multi-contributor development. Railway's own `Wait for CI` setting is also currently off, so the pre-deploy test gate is intentionally retained as defence-in-depth.

## Shopify product completeness contract

A Shopify product is not considered publishable merely because a product/variant exists. The backend must treat **product completeness as a deterministic publication gate**. Products remain `DRAFT` until every required field below has an approved source, passes validation and is written successfully.

| Shopify field | Source / rule |
|---|---|
| Title | Deterministic backend template from canonical card identity + explicit language + card number + variant + condition/grade. Never AI-invented. |
| Description | Structured facts from Supabase; AI may polish wording, but validators must prevent invented set/rarity/condition/grade/language/price claims. |
| Media | Approved media pipeline only; provenance and source rights must be stored. See media strategy below. Missing required media blocks publication. |
| Category | Deterministic Shopify taxonomy mapping by product type/game. |
| Price | `store_price_minor` from Drop Rate only. Shopify never becomes pricing source of truth. |
| Inventory | Exact sellable physical quantity from Drop Rate. Single-item listing = 1; no overselling. |
| Shipping | Deterministic shipping profile/weight/dimensions from approved product-type configuration; no AI assumptions. |
| Variants | Unique/physical-item listings use one controlled variant unless a deliberate pooled-listing model says otherwise. Language/condition/grade must never be silently collapsed. |
| Product metafields | Exact Drop Rate identifiers and structured card facts. Inventory ID is mandatory for single-item listings. Ownership remains backend-private and is not customer-facing. |
| Search engine listing | Deterministic handle plus validated SEO title/meta description generated from real database facts. |
| Status | `DRAFT` until completeness gate passes; only then `ACTIVE`. |
| Publishing | Publish only to explicitly configured publication/channel after all gates pass. Bulk publishing stays separately controlled. |
| Sales | Shopify records checkout/order facts; Drop Rate resolves each sale back to exact physical Inventory ID and owner. |
| Product organisation | Deterministic product type, vendor, normalized collections and tags from game/set/variant/language/status rules. |
| Theme template | Explicit product template selected by product type/listing model; never Shopify default by accident. |

### Media strategy — avoid manually scanning the whole inventory

The system should support two media classes:

1. **Canonical/licensed reference media** for ordinary raw cards where a permitted provider supplies reusable card imagery. The source URL/provider/license/provenance must be recorded against the canonical CARD. One approved canonical image can serve multiple equivalent physical copies.
2. **Physical-item media** for high-value, graded, unusual-condition, signed, altered, sealed or otherwise item-specific inventory. These items should require actual front/back/item photography before publication.

The intended operational workflow is **batch capture, not manual scanning**:
- camera/phone capture station
- Inventory ID / QR or barcode associates each shot with the exact item
- automatic crop/deskew/background cleanup
- AI may help detect front/back, orientation and image quality
- human review only for low-confidence/image-quality exceptions
- approved files stored once and referenced by the backend
- Shopify receives only media that has passed provenance + quality checks

Do **not** assume card-image reuse from eBay, Collectr, TCGplayer, Cardmarket or other providers is permitted. Reuse only when provider terms/licensing explicitly allow it. If no permitted canonical media exists, the item remains DRAFT until approved physical media is captured.

### Product completeness release rule

Before activation/publication, the backend must verify at minimum:
- canonical identity confirmed
- language explicit
- condition/grade valid
- registered physical location
- acquisition cost known
- Store Price known
- exact SKU / Inventory ID
- media policy satisfied
- shipping profile resolved
- required metafields present
- title/description/SEO validators pass
- product type/vendor/collections/tags/template resolved
- Shopify quantity matches backend sellable quantity
- publication target configured
- no duplicate active Shopify link for the physical item

Any failed check leaves the product DRAFT and creates an Action Required reason rather than guessing.

## Known remaining items

These are **not blockers to the current backend foundation**, but remain explicit work:

1. **GitHub branch protection:** verify `main` requires pull requests + passing CI before the project expands to multiple contributors.
2. **Railway Wait for CI:** `checkSuites` remains false despite two attempted updates; re-authorise/check the Railway GitHub App permissions and verify the toggle persists.
3. **Supabase migration delivery:** guarded workflow is merged; configure/verify its two GitHub secrets and run a production dry-run before the next schema change.
4. **eBay UK sold via Parse:** provider returns an empty list; investigate separately or use an alternative official/permitted source path.
5. **Cardmarket production ingestion:** re-probe/contract validation plus source-access/terms approval before persistence.
6. **Collectr production adapter:** diagnostic search is live, but the production detail/graded-price contract must be re-validated before enabling ingestion.
7. **TCGPlayer production ingestion:** supporting evidence only; validate the exact live detail/pricing endpoints before enabling persistence.
8. **Supabase leaked-password protection:** enable manually before launch.
9. **One Piece catalogue naming:** verify and normalize `Carrying On His Will` vs `Carrying on His Will` carefully.
10. **Packaged One Piece inventory:** confirm physical `seal_status` before provider matching/pricing.
11. **Operational inventory cleanup:** 412 remaining language reviews, 508 unconfirmed identities, 507 remaining registered-storage assignments, the remaining 10 conditions and 508 Store Prices. Current acquisition costs are populated; future unknown costs must still remain NULL.

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
| Purchase provenance / cost lots | ✅ Complete |
| Card condition | ✅ Complete |
| Sealed/unsealed state | ✅ Complete |
| Grade/certificate | ✅ Complete |
| Language | ✅ Complete |
| Controlled physical locations | ✅ Complete |
| Stock audit/location counts | ✅ Complete |
| Approval/readiness workflow | ✅ Complete |
| Core regression / hardening pass | ✅ Complete |
| Production inventory data cleanup | 🚧 Operational task for next session |
| Leaked-password Auth setting | 🚧 Manual pre-launch action |

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation maintained continuously |
| 2 | Database / authentication | ✅ Core complete; one manual pre-launch Auth setting remains |
| 3 | Founder account / inventory / ownership | ✅ Technical foundation complete; operational data cleanup remains |
| 4 | Inventory dashboard functionality | ✅ Core complete |
| 4.5 | Founder dashboard UX/navigation | ✅ Structural seller portal live; visual polish can continue incrementally |
| 5 | Shopify integration | 🚧 Guarded product sync + verified webhooks + exact-item sale/refund pipeline live; product-completeness/media contract now defined; controlled real sale still required |
| 6 | Orders / allocation / settlements | 🚧 Deterministic Shopify attribution/ledger foundation live; real end-to-end verification and settlement reporting remain |
| 7 | Market-data infrastructure | 🚧 Framework + multi-provider live access validated; production persistence intentionally gated |
| 8 | Pricing engine | 🚧 Deterministic engine live; trusted live evidence + scheduled execution remain |
| 9 | AI card identification | ⬜ Not started |
| 10 | Consignment | ⬜ Not started |
| 11 | AI product listings | ⬜ Not started |
| 12 | AI customer service | ⬜ Not started |
| 13 | SEO | ⬜ Not started |
| 14 | AI marketing | ⬜ Not started |
| 15 | n8n orchestration | ⬜ Advanced workflows not started |
| 16 | Analytics / optimisation | ⬜ Not started |

## Immediate work order

### Next session — inventory operations + controlled verification
1. ✅ Seel 021/094 selected, physically verified, priced and moved to APPROVED.
2. Verify the live Shopify test-publish flag is ON and bulk publish flag is OFF through the authenticated app/runtime.
3. Publish only Seel `INV-06F489A853594CDC80E418271933D044` through the guarded single-item test path.
4. Execute one controlled checkout/order and verify webhook signature + duplicate delivery handling.
5. Verify exact Inventory ID → owner attribution, COGS snapshot and owner/finance ledger.
6. Execute cancellation/refund/return test and verify state restoration + audit trail.

### Next major engineering milestone — Shopify
Build the complete controlled sale loop:

`Approved inventory → Shopify product/SKU → Shopify checkout/order → webhook verification → physical Inventory ID → owner attribution → deterministic fees/proceeds → refund/cancellation handling → auditable settlement report`

Required controls:
- Shopify webhook signature verification
- webhook/event idempotency
- duplicate-order protection
- no ownership inference from Shopify alone
- backend/Supabase remains source of truth
- failure/exception queue for sync and order-allocation problems

### Market work after/alongside Shopify
- re-validate Cardmarket detail/pricing contract and source permission
- re-validate Collectr production adapter contract
- validate TCGPlayer detail/pricing support path
- keep eBay active as listing/liquidity context
- solve eBay sold independently rather than blocking the wider provider model
- only then enable persisted observations and automatic pricing runs source by source

## Major deferred decisions / features

- multi-founder ownership remains deferred; current build stays single-founder
- consignors/consignment come after the founder sale loop
- automated media intake/product-enrichment follows the controlled Shopify sale loop; AI identification comes after core commerce/pricing reliability
- AI marketing, SEO automation and advanced n8n orchestration come after inventory, Shopify, settlement and market pricing foundations
- value-weighted Purchase Lot allocation waits for reliable market reference values
- no automatic money movement until settlement reporting is thoroughly verified

## Completion rule

- **Coding only:** In Progress.
- **PR open / CI green:** In Progress.
- **Merged but not deployed:** In Progress where deployment is applicable.
- **Production deployment + health verification successful:** Completed.
- **External provider limitation:** recorded explicitly; does not silently count as platform failure.
