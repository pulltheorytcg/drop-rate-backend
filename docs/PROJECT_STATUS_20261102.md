# Drop Rate project build, milestones and launch readiness

**Status date:** 2 November 2026, approximately 22:42 GMT. **Assessment basis:** GitHub main at [ed5c99e](https://github.com/pulltheorytcg/drop-rate-backend/commit/ed5c99eea1d8e7eab0e3a1af140e299b25c9a198), the existing [launch tracker #598](https://github.com/pulltheorytcg/drop-rate-backend/issues/598), [PR #868](https://github.com/pulltheorytcg/drop-rate-backend/pull/868), [PR #863](https://github.com/pulltheorytcg/drop-rate-backend/pull/863), [draft PR #874](https://github.com/pulltheorytcg/drop-rate-backend/pull/874), and read-only Railway production service/deployment inspection. This is a dated assessment, not an automatic production acceptance certificate.

> **Executive assessment:** The API, founder inventory foundations, catalogue, scanner, Shopify integration and seller-preparation interfaces are substantially implemented. Launch remains blocked by unverified real-world buyer/seller transactions, shipping and settlements, signed-in phone QA, source/asset gaps and backup/restore capacity. Technical completion is not the same as commercial readiness.

## Project completion estimate — explicitly judgment-based

| Scope | Estimate | Interpretation |
| --- | ---: | --- |
| **Launchable Shopify web MVP** | **65%** | Weighted assessment of the three original milestones plus acceptance/recovery gates; see calculation below. |
| **Full multi-owner, AI-automated platform vision** | **45%** | Rough scope-weighted planning estimate that also includes mature consignment operations, customer service, AI marketing, native mobile apps, advanced analytics and automation. Not based on commit/test count. |
| **Architecture and initial core product implementation** | **approximately 75–85%** | Architecture, APIs, RLS, inventory, catalogue, scanning and Shopify groundwork exist; this does not establish full end-to-end reliability. |
| **Live commercial acceptance** | **approximately 35–45%** | Engineering tests exist; physical-phone, paid-order, dispatch, refund and settlement proof remains incomplete. |

These percentages are **subjective planning estimates**, not measured source-code coverage, pricing coverage, automated CI coverage, or a guarantee. They will be reassessed after each verified production acceptance gate.

### The three agreed milestones

| Milestone | Estimated completion | Verified foundation | What is still required to close it |
| --- | ---: | --- | --- |
| **1 — Three founders can log in and manage separately owned physical inventory** | **90%** | Supabase Auth, unique physical inventory, ownership/RLS, cost/condition/grade/location, owner-scoped dashboard, audit and Action Required mechanisms are implemented; earlier production inventories contained hundreds of physical records. | Record a **real authenticated session from each of the three founder accounts**, adding/searching/updating distinct copies, confirming strict cross-owner isolation, cost and audit accuracy, and mobile usability. No inferred ownership. |
| **2 — Approved inventory syncs to Shopify, sells and attributes money to the correct owner** | **65%** | Published physical inventory links, guarded Shopify sync, verified webhook intake/idempotency, order/owner allocation and deterministic postage/ledger scaffolding exist. Seller comic preparation and founder photo review were merged in [#868](https://github.com/pulltheorytcg/drop-rate-backend/pull/868); they do not auto-approve or auto-publish. | One separately authorised real purchase on the intended Brand Redesign storefront, exact inventory→owner attribution, multi-owner case, fulfilment/label/packing-slip/tracking, refunds/replay, verified actual postage and one reconciled settlement report. Owner shipping permissions and handling ambiguous provider outcomes remain explicit gates. |
| **3 — Market evidence updates valuations and recommended pricing automatically** | **60%** | Modular source evidence, R2 catalogue/market projections, price histories, constrained GBP reference guides and daily/weekly guarded jobs exist. [#863](https://github.com/pulltheorytcg/drop-rate-backend/pull/863) correctly excludes model-only estimates from the verified 89% KPI. | Complete source-rights-aware refresh/reliability and provenance verification, reduce exactly identified missing evidence/artwork, prove price display on phone, and restore-proof R2 history/source backups. Last documented independently measured eligible reference-guide coverage was **43,454 / 67,066 = 64.79% (29 October)**, around **16,235** extra eligible values short of **89%**; this is **not** the project-completion percentage and must not be represented as a current 2 November live SQL count. |

**How the 65% MVP assessment was calculated:** 25% importance × milestone 1 at 90%, plus 35% × milestone 2 at 65%, plus 20% × milestone 3 at 60%, plus 20% × cross-cutting launch/recovery acceptance at 40% = **65.25%, rounded to 65%**. These weights prioritise the functioning sale and correct financial allocation above optional polish. No feature is declared complete solely from mocked tests.

### Wider 16-phase roadmap summary

| Original build phases | Readiness interpretation |
| --- | --- |
| **1–4: architecture, database/auth, three-founder inventory, dashboard** | Mostly implemented; founder-by-founder acceptance not closed. |
| **5–6: Shopify, order attribution and settlement** | Significant backend work deployed; real paid/fulfilment/refund/settlement acceptance is the main commercial critical path. |
| **7–8: market data and pricing** | Running but incomplete source coverage, source eligibility, book valuations and on-device performance. No fabricated prices. |
| **9–10: recognition and consignment** | Functional scan/collection and seller-preparation pieces; exact-print, slab/sealed, physical photos, ordinary-seller import correction and custody workflows need verification. |
| **11–14: AI listings, service, SEO, marketing** | Partial listing/SEO and campaign foundations; autonomous customer service, full AI creative automation and scale marketing are **not** launch-complete and remain deferred. |
| **15–16: n8n and analytics/optimisation** | n8n and monitoring exist; workflow provenance, fault handling, real performance measurements and finance/fulfilment operational evidence need completion. |

## Live technical state on 2 November

- **Main branch:** commit [ed5c99e (#873)](https://github.com/pulltheorytcg/drop-rate-backend/commit/ed5c99eea1d8e7eab0e3a1af140e299b25c9a198). This added a short-TTL coalesced catalogue pricing-coverage read. The main Railway FastAPI service was **SUCCESS/online**; n8n was **SUCCESS/online** in the read-only check.
- **Configured Railway services:** nine, including idle PSA prototypes and a temporary one-off backup worker. The Railway environment-status check reported **one critical service issue**: the temporary **drop-rate-reference-backup-once-20261102** deployment was **CRASHED**. The other eight reported no active issues (which does not mean eight running application replicas).
- **R2 backup blocker:** the backup worker on [draft #874](https://github.com/pulltheorytcg/drop-rate-backend/pull/874) failed with **Invalid private archive object identity** during verified readback on 2 November. The draft addresses an earlier locale-sorting mismatch. **Do not mark full source backup or restore as verified; do not delete/postpone safeguards on the original PostgreSQL source.** The main customer API remains separate and online.
- **Supabase capacity:** [draft #869](https://github.com/pulltheorytcg/drop-rate-backend/pull/869) records **419,220,627 bytes** on 2 November, below the 500 MB Free plan limit but **above the 400,000,000-byte import guard**. R2 holds approved large media/catalogue projections, while PostgreSQL remains the source of truth for physical stock, owners, evidence and finance. No table removal is authorised.
- **Catalogue:** approximately **69,697 reference-card identities** were confirmed in the latest source-backup read-only investigation. This is **not** 69,697 items owned by founders. Comics/manga have separate records; approved commercial physical photos and source-backed book prices are still distinct gaps.
- **Storefront/theme:** the founder reported on 1 November that **Drop Rate — Brand Redesign is the main Shopify theme behind a storefront password**. This audit did not independently verify Shopify Admin theme role, live inventory count or checkout; do not confuse active product links with a validated public buying journey.
- **Additional scope:** [draft #869](https://github.com/pulltheorytcg/drop-rate-backend/pull/869) prepares other collectible categories with production schema groundwork but no full imported/published catalogue. It is **not required for the initial Pokémon / One Piece / Dragon Ball / Naruto storefront launch**; do not move its experimental wider catalogue work onto the launch critical path.
- **Native apps:** App Store/Google Play badges remain **Coming Soon**; signed/approved public mobile app releases are **not** part of the proposed Shopify web-launch date.

## Launch gates, in priority order

1. **Protect database and recoverability:** resolve the temporary R2 backup failure; require complete exact-record source export, SHA-256, upload/readback, typed PostgreSQL restore proof and verified no-loss checks before any physical offload. Keep current capacity guard and automated history-archive evidence.
2. **Close owner/account acceptance:** verify login and physical stock isolation for all three founders, plus an ordinary seller's preview→correction→Draft commit→Collectr re-export path without duplicates, owner leaks or silent Shopify publication.
3. **Prove one complete separately authorised paid pilot:** real exact physical item → Shopify paid order → correct owner and net proceeds → actual approved carrier label → one packing slip → dispatch/tracking → refund/replay handling → reconciled settlement report. Multi-owner split shipment must either pass or be explicitly restricted at launch.
4. **Finish intended storefront acceptance:** real mobile and desktop browse/filter/search/PDP/cart/checkout, exact copy stock/decrement, shipping boundaries and customer account. Test original Brand Redesign theme, not only previous Horizon. Verify rollback to Horizon or other safe customer-visible gate.
5. **Measure the actual UX:** time a signed-in physical scan→confirmed identity→listing, and buyer homepage→purchase; record screens/taps, first-load/repeat-load latency, source art and price visibility. No claim of performance based solely on CI.
6. **Release proof:** required CI and native PostgreSQL/RLS isolation; source-controlled n8n workflows and failure alerts; no critical Action Required items or unresolved webhook-gap criticals; verified release SHA/deployment readback; approved go/no-go decision.

A green CI run, a live button or a generic completed checkout simulation does **not** close these gates. The detailed tracked checklist remains [#598](https://github.com/pulltheorytcg/drop-rate-backend/issues/598).

## Preliminary launch forecast (not a commitment)

**Planning target: Monday, 18 January 2027, for a limited password-free Shopify web storefront launch.** Reasonable conditional planning range: **11–29 January 2027**. The January date includes engineering, separate founder authorisation of a real paid pilot, practical phone/desktop verification, holiday/calendar buffer and a written rollback. It excludes native mobile-app store releases, full unattended consignor rollout, paid advertising and new collectible categories.

| Window | Planned evidence gate | If missed |
| --- | --- | --- |
| **3–13 November** | Safe R2 backup/restore receipt; capacity containment; owner/account acceptance plan. | Do not delete PostgreSQL source or accelerate bulk imports. |
| **9–27 November** | Controlled seller-import corrections, actual label/fulfilment path and exact ledger/owner tests. | Restrict multi-owner/seller operations; no unsupported shipment claims. |
| **23 November–11 December** | Signed-in real-device and Brand Redesign buyer QA, authorised paid pilot, refunds, owner accounting and documented rollback. | Keep storefront password gate / restrict sales. |
| **14–18 December** | Founder-only release candidate and final commercial readiness review, if preceding gates pass. | Carry open failures into January; no automatic public launch. |
| **11–29 January** | Conditional public Shopify storefront opening; **18 January** is the planning midpoint. | Delay rather than publish with an unresolved financial/security/fulfilment gate. |

**Confidence: low-to-moderate.** This date assumes dedicated delivery time, timely founders' authorisation of live commercial tests, viable carrier/API scopes, and no major blocker from free-source pricing eligibility or database recoverability. The 89% verified-value goal is a separate quality target: unsupported cards must remain honestly unpriced and cannot be made “complete” by internal models. If 89% is made a strict opening requirement without new permitted sources, **the date cannot presently be committed**.

## Change boundary and verification

This status update is **documentation only**. It changes no FastAPI rules, inventory, owners, prices, database migration, Railway deployment, Shopify publication, consent, financial ledger or credentials. GitHub review should confirm exactly the new dated report plus a pointer in BUILD_STATUS, check source links against live PR/deployment records, and keep the backup worker/other draft PRs untouched. Do not merge in a way that accidentally triggers a live deployment while recovery operations are in flight.

**Next status review:** after the R2 restore readback and the first separately approved real paid, physical fulfilment and owner-allocation test. Update measured milestone estimates only with fresh production evidence.
