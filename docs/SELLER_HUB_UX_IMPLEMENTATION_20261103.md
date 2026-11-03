# Seller Hub — premium interaction and UX implementation

**Status on 3 November 2026: implementation and local verification complete; native GitHub CI and live release pending. This release has not been deployed.**

The user authorised the reviewed UI/UX improvements, premium motion, GitHub publication, CI and Railway deployment after checks pass. The implementation preserves exact collectible identity, physical-copy ownership, truthful price evidence, deliberate sale submission, and existing review, payment and fulfilment protections.

## Delivered workflows

| Area | Completed implementation |
| --- | --- |
| Navigation and account | Primary destinations are Home, Collection, Scan, Search and Selling. Account and workspace tools sit in an accessible menu with keyboard navigation and focus handling. |
| Home and Selling | A compact collector home gives a clear Add item action and relevant work queues. Selling links directly to listings, orders and balances. Listing actions open the relevant filtered collection instead of a general collection detour. |
| Add item and save receipts | A shared entry offers the existing scan, catalogue and manual-entry paths. Successful saves provide View item/View collection and Add another. View item opens the actual saved copy; returning to Search restores useful context. |
| Collection and item details | Category, game, language and listing-state controls refine the owned collection. Sorting, exact identity labels, copy-level actions and grouped-copy behaviour are explicit. Item opening remains owner scoped. |
| Listing preparation | Contextual preparation shows the selected copy, required steps and next action. Progress can be resumed, while review and sale submission remain deliberate actions. |
| Search and recovery | Five categories separate Trading Card Games, Sports Cards, Comics, Manga and Figures. TCG queries search cards without requiring a game first. A single Filter & sort sheet offers relevant controls. Clearing refinements preserves the query; empty states offer category-specific recovery. Enter and IME composition behaviour are covered. |
| Saved references | Saved references belong to the authenticated account and remain distinct from owned inventory. Importing older device saves requires an explicit action. Failed sync and offline states are visible; late responses cannot transfer saves across accounts. |
| Account and onboarding | Profile forms adapt to mobile widths. Signup and verification recovery retain a clear next step without treating an unverified account as complete. Existing authentication and consent behaviour remains intact. |
| Financial and fulfilment views | Compact financial summaries and transaction layouts improve mobile scanning. Fulfilment guidance explains the current action and its effect while retaining the existing operational workflow. |
| Sports and Figures | Typed manual intake records explicit sports-card and figure identities. Verified catalogue references show their exact edition facts before copy intake. Seller-entered identities remain private and unreviewed until the existing review process permits wider discovery. |
| Premium motion | Short transitions, restrained elevation, responsive sheets and save feedback support the dark navy, storefront logo and Inter design. System reduced motion and the device-level motion preference preserve all functionality. |

Implementation lives in the existing application and API workflows, including `hub-experience`, `account-experience`, the catalogue browser, collection controls, guided listing and collectible intake modules. This is a functional redesign, with automated coverage of navigation, filtering, state preservation and mutations.

## Bounded official catalogue starter

The release includes a reviewed **six-reference metadata seed**, with full provenance and run instructions in [COLLECTIBLE_STARTER_CATALOGUE_20261103.md](COLLECTIBLE_STARTER_CATALOGUE_20261103.md).

| Category | Exact scope |
| --- | --- |
| Sports Cards | Four Topps Premier League 2025/26 **Base Players** references: Bukayo Saka/Arsenal #12, Cole Palmer/Chelsea #100, Mohamed Salah/Liverpool FC #174 and Erling Haaland/Manchester City #195. The references use the English UK checklist scope, release year 2025 and no asserted print run. |
| Figures | Two distinct Good Smile Company Nendoroid references: Hatsune Miku **3.0** (JAN 4571697188655) and **3.0 [Basic]** (JAN 4580828662797), with February 2026 release metadata. The special box, retailer bonuses and regional packaging variants are not represented by these entries. |

These are a small starter catalogue, not comprehensive coverage. Manual entry remains available. Figure manufacturer SKUs and exact retail release days remain unset; collector-copy language, condition, authenticity and completeness still require the normal intake and verification workflow.

The renderer writes canonical products and profiles with the existing `VERIFIED` status, `identity_source=OFFICIAL_CATALOGUE` and `verification_scope=OFFICIAL_REFERENCE_METADATA_ONLY`. It stores stable source IDs, official URLs, review dates and field-level evidence. **The seed writes no inventory, ownership, quantities, prices, media approvals or storefront listings.**

An identical replay makes no changes. Existing disagreement or an equivalent identity under another key causes the entire transaction to fail for review; seller-entered records are never merged or promoted automatically. Only after all references validate does the transaction set category coverage to `STARTER_METADATA`, availability to true and the actual official counts (four sports cards and two figures). Failed batches leave coverage metadata unchanged.

## Database and application release order

Apply the new schema migrations in timestamp order after native CI passes:

1. [`20261103143718_catalogue_saved_references.sql`](../database/migrations/20261103143718_catalogue_saved_references.sql) — account-owned saved references, explicit grants and forced row-level security.
2. [`20261103145218_seller_sports_figures_intake.sql`](../database/migrations/20261103145218_seller_sports_figures_intake.sql) — Sports/Figures systems, FIGURE support, typed profile checks, seller-attributed unreviewed intake and physical-state validation.
3. [`20261103150140_catalogue_review_visibility_r2.sql`](../database/migrations/20261103150140_catalogue_review_visibility_r2.sql) — reviewed-reference visibility and matching R2 invalidation behaviour.

The metadata seed must follow these prerequisites as part of the coordinated release of the matching backend, frontend and catalogue/R2 changes. Render its SQL using `backend/scripts/seed_collectible_catalogue.py`, review it, and apply it through the approved database release process. Its own transaction, identity-conflict checks and short lock/statement timeouts are retained. Complete deployment and read-only live smoke checks before describing this release as live.

## Verification completed

| Gate | Recorded result |
| --- | --- |
| Backend regression suite | **8,924 passed; 25 skipped.** Skips are recorded as skips, not passing coverage. |
| UI interaction suites | **25 suites passed**, covering the existing workflows and the new navigation, discovery, collection, account, listing and collectible-intake behaviours. |
| Responsive browser checks | **108 checks passed with no errors**, using the real HTML/assets and synthetic data at 320, 390, 768 and 1440px widths. |
| Saved-reference PostgreSQL checks | Actual disposable PGlite execution verifies forced RLS, owner isolation, permitted own-row operations, rejected cross-account/no-user operations and denied direct roles. |
| Collectible-intake PostgreSQL checks | Actual migration and trigger execution verifies category/type constraints, seller attribution, prevention of self-verification, physical-state rules, owner isolation and provider/taxonomy compatibility. |
| Catalogue-seed PostgreSQL checks | Actual schema and generated SQL execution verifies six records, distinct editions, truthful category counts, unchanged replay, drift refusal, atomic seller-conflict rollback and unchanged inventory, prices and media. |
| Focused seed validation | **20 Python checks passed**, including exact reference data, canonical typed fields, source origins, unknown values, dates, duplicate identities and rejected price/artwork input. |

PGlite checks run against disposable local PostgreSQL instances. They do not connect to production. Screenshots and browser mutations use isolated synthetic accounts and data; no customer orders or payouts were executed for visual verification.

### Review screenshots

The committed screenshots show representative synthetic states from the responsive review:

- [Mobile Home](ui/seller-hub-ux-20261103/mobile-home.png)
- [Mobile Add item](ui/seller-hub-ux-20261103/mobile-add.png)
- [Mobile guided listing](ui/seller-hub-ux-20261103/mobile-guided-listing.png)
- [Desktop Selling](ui/seller-hub-ux-20261103/desktop-selling.png)

## Explicit limits and remaining release gates

**Value sorting has a 10,000-matching-copy guard.** It ranks the complete filtered selection using the same persisted reference values displayed in the UI, before pagination. Missing values remain distinguishable from zero. If more than 10,000 copies match, the API returns a clear request to narrow the filters; it does not silently sort a partial sample. This path makes no provider pricing calls. Concurrent changes to the selected copies produce a refresh request rather than mismatched values.

**Real-device acceptance has not yet been performed.** Responsive desktop-browser emulation does not establish physical iOS/Android behaviour, camera permission/rotation handling, real email delivery, external OAuth handoffs or payment/fulfilment integration acceptance.

Pending release work:

- [ ] Publish the reviewed branch and complete native GitHub CI.
- [ ] Apply the ordered database migrations and reviewed metadata seed during the coordinated release.
- [ ] Deploy the matching application release to Railway.
- [ ] Complete read-only live health, authentication, navigation and catalogue smoke checks.
- [ ] Perform and record real-device acceptance separately.

Local implementation and verification are complete. Native CI, database release, deployment and live verification remain pending at this record's date.
