# Cloudflare complete-exit execution register — 6 November 2026

**Direction approved: replace Supabase with private Cloudflare R2 + D1.** This file is a *live-data inventory and release contract*, **not evidence that data has moved or that production has cut over**. See [architecture decision](CLOUDFLARE_R2_D1_MIGRATION_DECISION_20261106.md). Shopify continues as storefront/checkout; Railway FastAPI owns deterministic business rules; n8n only orchestrates.

## 1. What we are building / why / what it connects to

Build a **complete**, independently testable migration of the full Drop Rate application off Supabase PostgreSQL, Supabase Auth and Supabase Storage. R2 holds immutable versioned source/catalogue and evidence, private card/media bytes, historical prices, backups and long-term audit. D1 holds indexed current catalogue/materialised eligible Market Values and **one consistent operational database** for owners, inventory, orders, refund/settlement accounting and state transitions. An independent identity provider must replace Supabase Auth; Railway verifies signed sessions and enforces per-owner permissions. Cloudflare D1 does not implement PostgreSQL RLS.

The first tangible change is an exhaustive checked-in [table inventory](CLOUDFLARE_FULL_EXIT_TABLE_REGISTER_20261106.json) and `tools/cloudflare_full_exit_preflight.py`. Every table has an explicit destination. A new or removed relation **blocks** migration until reviewed, rather than disappearing from the scope. No raw data, card photos, private balances or auth credentials are committed to GitHub.

### Verified production source — read-only, 6 November 2026

- Supabase project `ozrxenrdladkooixutmm`, database **430,476,435 bytes** at 17:52:40 UTC, exceeding the existing **400,000,000-byte** bulk-ingestion pause. Leave the guard enabled; it is not storage reclamation permission.
- Database system-catalogue audit (17:55:48 UTC): `tcg` **107 tables / 387.45 MiB of table+index relations**, `tcg_private` **6**, `auth` **27**, `storage` **8**. `tcg` has **128 functions, 156 custom triggers, 272 RLS policies, 185 foreign keys and 396 indexes**. PostgreSQL `reltuples` is *estimated*; these values are not authoritative row-count parity receipts.
- Large relations: `audit_events` ~101.68 MiB, `reference_cards` ~73.58 MiB, `reference_market_prices` ~55.89 MiB, `reference_catalogue_prices` ~47.73 MiB, `reference_image_mirrors` ~29.06 MiB. Their sizes include indexes; R2 shadows do **not** reclaim PostgreSQL space.
- Trusted GitHub status receipts at 17:49 UTC: Lorcana **3,505/3,505** verified D1; Yu-Gi-Oh! **8,000/45,418** D1 with today's staging receipt already spent; Sports/Heritage/Figures/Magic **0/155,488** D1 (gated); legacy five-relation dataset **0/79,186** D1 (gated). See [YGO run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42264804133), [follow-on run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42264804106), [legacy run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42264804179). 79,186 is five different relation types, **not 79,186 unique cards**.
- D1 read-only account capacity audit reported the **largest existing database at 9,146,368 bytes** and room by count for one additional database at 17:36 UTC. It did **not** measure remaining account-wide daily write quota. See [capacity run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42263074512). A green workflow run may still publish a **pending** D1 parity status.
- A verified R2 quote backup from 3 November includes 59,693 `reference_market_prices` and 27,676 `reference_catalogue_prices` source rows. It is a dated backup, not a current live price feed or a complete dataset retirement. Market Values, historical observations, image bytes and pricing source rights need independent proof.

## 2. Full table routing; current code coverage is not data parity

The [register](CLOUDFLARE_FULL_EXIT_TABLE_REGISTER_20261106.json) explicitly categorises all **148** named relations across app, private publications, Auth and Storage. Routes are design destinations, not evidence of exported/uploaded rows.

| Routes | Handling |
|---|---|
| Catalogue: reference cards/sets/sealed, product/profile records, comics/manga, sets, canonical printing IDs | Private immutable R2 source + exact-indexed D1 projections; preserve provider, game, language, printing, finish and stable IDs |
| Current price tables | Immutable R2 quote/provenance input + D1 **eligible** GBP-minor-unit Market Value projection; guide/unknown not promoted |
| Asking prices | **R2 asking-only / D1 non-market evidence**; never turn eBay Browse listing asking into sold Market Value |
| Historical observations, quote history and archives | Append-only R2 with indexed D1 provenance; never delete or rewrite |
| Artwork and media metadata | R2 private binary objects + D1 rights/access/exact-copy index; exact slab photo, no raw substitute |
| Owners, founder/consignor membership, physical stock, locations, lot costs | One operational D1 database with server-side isolation, immutable ownership lineage and private R2 backups |
| Orders, payouts, refunds, Shopify/eBay/Stripe callbacks | **Same** operational D1 transaction boundary with unique idempotency keys and ledger reconciliation |
| Audit, action queue, jobs, recognition, marketing state | D1 operational review state and immutable R2 evidence or audit records, preserving retention |
| `tcg_private` publication registry | Immutable R2 manifests and private D1 version pointers; no public write interface |
| `auth` (27 tables) | **Replacement identity integration**. Do **not** bulk copy passwords, refresh tokens, sessions, OAuth secrets or MFA materials into R2/D1 |
| `storage` (8 tables) | Enumerate actual private objects and rights; byte-level R2 copies with hashes, D1 object-identity metadata; no assumption that a URL is an image |

## 3. Sequenced migrations with real acceptance gates

**A — Complete source snapshot and schema conversion.** For every application relation, take consistent read-only captures with table counts, exact column/type schema, PK/FK constraints, hash manifests and per-row typed restore verification. Secure PII/financial snapshots in a separately restricted R2 destination with privacy, retention, encryption and rights checks. Supabase Auth requires an independently selected supported identity export/reauthentication method, *not* raw token copies. Resolve 128 PostgreSQL functions, 156 custom triggers, 272 RLS policies and 185 FKs individually or via equivalent FastAPI/D1 logic. Failure: drift, incomplete or exposed private archive. Test: full enumeration, stable IDs, denied cross-owner reads, digest/restore parity; zero source deletes.

**B — Finish R2→D1 reference catalogue staging.** Preserve current approved six R2-first partitions and typed legacy source without duplicating import jobs. The Yu-Gi-Oh! importer has a bounded **8,000 new rows/day** receipt; follow-on work starts only after 45,418 full active YGO parity; legacy starts only after 155,488 follow-on rows. No retries to evade daily quota. Failure: exceeded account D1 writes, digest/key mismatch, source drift, wrong language/variant/finish, unverified active pointer. Test: source SHA256, original relation counts, exact-key, negative cases, pagination, cold-reload, real D1 p50/p95.

**C — Price engine and history.** Export current quote tables **and** independent historical observations, sold evidence, sealed and figure prices, per-source timestamps, currency/FX, condition, language, grade and evidence type to R2. Build compact D1 projection with explicit `ELIGIBLE_MARKET_VALUE`, `GUIDE_ONLY`, `ASKING_ONLY`, `STALE`, `REVIEW_REQUIRED`, `MISSING`. Only permitted, exact, current evidence is eligible; never treat original SQL priced-reference count as sold-market-value coverage. Do not change Shopify Store Price. Failure: cross-print, raw/slab, asking/sold, USD/GBP, stale provider or duplicate source. Test: 5 independently verified exact sold comparisons for graded values, seller/item uniqueness, provenance retention, no RRP/guide estimate displayed as final Market Value.

**D — Artwork and files.** Inventory physical uploaded photos, scans, slabs, comics/manga, sealed images, public reference art and permitted rights. Transfer bytes into private R2 with SHA256/size/MIME validation and readback; index metadata and access in D1. Retain original physical inventory IDs and exact media provenance. Do not invent missing copyrighted images or infer graded from raw. Failure: missing original binary, wrong print or condition, unauthorised download, wrong owner, broken Shopify Files link. Test: actual signed-in raw vs PSA/BGS/CGC counterpart, blob restore, URL/rights audit, original image counts by category, mobile and desktop.

**E — Operational D1 + external identity.** Build one D1 transaction boundary for owner, physical item, order, commission, fees, balances, adjustments and settlement ledger. Migrate users through reviewed identity provider and verified owner-role mapping; revoke/expire old sessions as designed. Replay representative real source reads against D1 shadow only. Failure: founder A mutates founder B, price overwritten by model, two owners allocated one item, duplicate checkout webhook, refund out of order. Tests: **100 duplicate webhook deliveries = one posting**, concurrent physical reservation, three-founder/consignor split order, refund reversal, old/new audit, ownership and net balance penny-level parity.

**F — Cutover and retirement.** Switch feature-flagged reads after verified all-game D1 catalogue parity, fast query performance and exact image/value behaviour. Freeze or reliably buffer source writes, apply and reconcile one operational D1 ledger, switch signed/authenticated backend requests, ensure Shopify orders/refunds still idempotent, and demonstrate rollback. Test restore from a fresh private R2/verified backup and signed-in mobile/Desktop purchase. Only then authorise Supabase retirement, preserving accounting retention. No `TRUNCATE`, RLS disable, source deletion or silent production routing changes.

## 4. Capacity and truthful release status

Current D1 Free workflow budgets make **a complete same-day reference migration impossible without an approved revised capacity/plan and safely engineered new scheduling**; YGO's 6 November budget is already used. This is a technical execution constraint, not a missing click. A paid plan, if chosen, requires separate explicit commercial approval, measured D1 file/index sizes, provider quota readbacks and revised tests. Do not increase budgets or skip source SHA/finance checks merely to produce green jobs.

**As of this register:** table destination mapping has been implemented; the complete operational/full-price/full-media/auth data migration and production cutover have **not** happened. Neither GitHub merge nor a Railway deploy proves actual D1 data parity or a functioning multi-owner settlement. Preserve PostgreSQL authority until a verified operation-by-operation switchover. Do not claim "Supabase replaced" before Stage F.

### How to run the preflight

Local/offline validation (no credentials or data export):

```sh
python tools/cloudflare_full_exit_preflight.py
python -m pytest -q tests/test_cloudflare_full_exit_preflight.py
```

Production read-only schema drift verification, **only in an already configured trusted Railway service with platform-maintenance credentials**:

```sh
PYTHONPATH=backend:tools python tools/cloudflare_full_exit_preflight.py --verify-live-pg
```

The command queries only `pg_class` / `pg_namespace` through an authenticated admin in a read-only transaction. It does not download application rows, change anything, push to R2 or write to D1. It must return `FULL_EXIT_SOURCE_INVENTORY_VALIDATED_NOT_MIGRATED` and `live_schema_match=true` to pass. After that, each export/cutover stage needs an independent verified implementation and release receipt.
