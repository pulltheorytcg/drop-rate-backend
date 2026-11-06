# Architecture decision — migrate Drop Rate off Supabase to Cloudflare R2 + D1

**Recorded 6 November 2026. Approved direction from the founders; NOT an assertion that production was migrated.**

This decision **supersedes the proposed Supabase upgrade and the target-state recommendation** in `docs/CLOUDFLARE_D1_CATALOGUE_FEASIBILITY_20261103.md`. That earlier research and its read-only pilot are retained as historical evidence.

## 1. What we are building

A staged, testable migration from Supabase PostgreSQL and its dependent access/authentication paths to **Cloudflare R2 for immutable, large reference/evidence objects**, **Cloudflare D1 for indexed SQL and authoritative operational records**, with **Railway FastAPI as the deterministic business-rule API**. Shopify remains the unified checkout, n8n remains orchestration only.

This document is an architecture/cutover plan: it does **not** change production configuration, create D1 databases, change any owner, reprice any card, disable Supabase, switch authentication or spend money.

| Responsibility | Target | Rules |
|---|---|---|
| Canonical catalogue, source manifests, artwork, raw market observations and price-history archives | Private R2 objects, immutable content digests | Provider provenance, exact printing/variant/language/grade, allowed source terms; never let a blob replace ledger logic |
| Searchable catalogue/index and latest price materializations | D1 **read/index partitions**, bounded and separately versioned from source | Exact provider + system + language + source ID; only fully verified generation becomes visible |
| Physical inventory, canonical ownership, founder/consignor assignments, condition, cost, location and status | **Operational D1** with foreign keys and application RBAC | One unique inventory ID per physical copy; no ownership inferred from catalogue ID |
| Shopify order, individual order items, sale allocation, fees, commission, refund adjustments and settlement ledger | **One operational D1 transaction boundary** | Deterministic FastAPI calculations, unique event keys, ledger reconciliation; no cross-D1 financial atomicity |
| Auth/session/roles | Replacement identity integration + FastAPI verification | No Supabase Auth reliance after cutover; signed tokens, role checks, least privilege, no secrets in clients |
| Marketing automation | n8n to FastAPI APIs | Never calculate ownership or settlement amounts in n8n or AI |

**D1 is SQLite, not a PostgreSQL endpoint.** Existing PostgreSQL JSONB operations, SQL functions/triggers, locking and RLS policies cannot be ported by changing a connection string. D1 has no PostgreSQL RLS; every permission must be enforced by the API and audited. Do not expose a D1 write credential to Shopify or the browser. Use a private Cloudflare Worker binding/API or another reviewed server-side adapter, with signed and scoped calls from FastAPI.

## 2. Why / constraints

The full card-reference set is **272,079** including R2-first Magic (153,662), Yu-Gi-Oh! (45,215), Lorcana (3,505) and existing SQL reference games. Existing historical stored prices are **not the same as current verified Market Values**. The original PostgreSQL database was **430,460,051 bytes** on 6 Nov and the guarded batch threshold is 400 MB. We do **not** upgrade Supabase as the next step.

D1 Workers Free has **500 MB per individual database**, **5 GB total account storage**, **5 million rows read/day**, and **100,000 rows written/day**; Workers Paid offers **10 GB per database** and different usage allowances (verify plans on the date of any purchase). Design the R2 catalogue so a full daily reference reimport does not require 272k D1 row writes. Prefer immutable source downloads and **delta updates to D1**. Keep one operational D1 database so mixed-owner orders and settlements can commit atomically within it. Do not divide a single financial ledger over independent D1 databases.

Cloudflare sources:
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/d1/worker-api/d1-database/
- https://developers.cloudflare.com/d1/reference/migrations/

## 3. Connections and migration order

### Stage A — exact inventory and read model (no production writes diverted)

1. Inventory the existing Postgres schema, cross-table FK dependencies, index/query plans, RBAC/RLS, auth flows and the **37 Python modules** found by the earlier feasibility audit. Record an exhaustive compatibility map for each SQL function, trigger, `RETURNING`, `FOR UPDATE`, JSONB type, sequence and unique index.
2. Freeze stable keys for card references and physical items. R2 must carry source receipts, original printing/finish and immutable snapshot digest. D1 materialized catalogue rows only point to approved R2 generations.
3. Apply versioned D1 SQL migrations in a **fresh isolated test database** first. Populate read-only projections from verified R2 objects. Compare every sample and per-source count, exact ID, foil/nonfoil, language and price status with the PostgreSQL baseline. Track search p50/p95, row-read/write accounting and money-related schema isolation.
4. Wire a feature-flagged **read-only shadow** Cloudflare Worker/adapter, signed from Railway FastAPI. Never expose credentials to end users. Missing D1 generation, wrong digest, failed read or stale source must fail closed to the existing authorized read path (no model estimate or suggested retail masquerading as Market Value).

### Stage B — continuous catalogue Market Values

1. For each game, build adapter for sources with reviewed permission and exact provider IDs. The already merged Cardmarket source discovery (#919, #920) and MTGJSON ID bridge (#921) are *prerequisites, not live published prices*.
2. Normalize currency, time, condition, variant, finish, language and sold/guide/active-listing evidence independently. Cardmarket statistical guide values are **guide evidence**, not UK eBay sold transactions. Confirm source-use/display rights. No unverified eBay Browse asking quotes as final Market Values.
3. Record source and historical evidence as append-only, checksum-verified R2 snapshots. FastAPI deterministic rule calculates candidate market value; apply hard match/misprinting/recency/outlier/low-evidence gates. Do not invent UK sold evidence, grade premiums, minimum market values or substitute RRP.
4. Publish a **small D1 current-price projection** using an idempotent generation and pointer commit **only after** all associated R2 objects are written, read back and checksummed. Keep previous generations for rollback. D1 should store `Market Value` amount in GBP minor units only if eligible; separately track `GUIDE_ONLY`, `STALE`, `MISSING`, `REVIEW_REQUIRED`.
5. Coverage KPI is current eligible source-priced unique reference keys / 272,079, grouped by game and status. Never count historical price rows, duplicates, unlinked source products or stale guide rows as covered.

### Stage C — ownership and money (separate controlled cutover)

1. Export physical inventory, owner master, consignments, customer associations, orders, order items, provider webhook inbox, allocations, refunds, settlements, outstanding balances, role mapping, audit and transaction history as immutable encrypted/permissioned checkpoints; verify row counts and stable IDs before test import. Do not carry sensitive secrets or payment-card details.
2. Reimplement PostgreSQL policies/constraints in versioned D1 schema and FastAPI: founder isolation, immutable owner ID on sale lineage, unique inventory IDs, event idempotency, refund reversals, audit old/new values, double-entry or equivalent auditable net-proceeds balances.
3. Use D1 transactional `batch()` or an equivalent reviewed transaction boundary for order + allocation + balance ledger writes; use uniqueness/compare-and-swap for competing callbacks. Do **not** use R2 or multiple independent D1 databases as a shared financial transaction. Outbox for cross-system Shopify/Worker/R2 effects; replay exactly once at business-key level.
4. Replace Supabase Auth with a separately selected, tested identity solution. Stage verified users and account mapping; force safe session reauthentication where needed. Browser token permissions must never rely on mutable user metadata.
5. Shadow reconciliation over real multi-founder and consignor orders, refunds and disputes until **zero difference** for owner identity, gross, fees, commission and net GBP minor units. Simulate duplicates, out-of-order Shopify events, lost network acknowledgements, partial R2 uploads and concurrency.
6. Define a reversible production cutover: freeze new writes to old ledger or capture/replay a verified event buffer; check counts and balances; route a controlled first tranche; verify; maintain protected old data for rollback. No deletion until backup/restoration and sustained correctness are independently verified.

### Stage D — Supabase retirement

Only after both **data and authentication** no longer depend on Supabase, all Railway services use D1/R2 safely, webhook replay/reconciliation is proven, and an offline+R2 restore is tested, retire the Supabase project. Preserve records for the required legal/accounting retention schedule. Do not use `TRUNCATE`, disable RLS or drop audit/history tables as a storage shortcut.

## 4. Failure points requiring explicit tests

- **Wrong product:** El Thor One Piece normal reference previously matched premium/promo eBay sold titles. Strong name agreement is insufficient: exact edition/printing/finish proof required before a Market Value.
- **Financial race:** duplicate or concurrent Shopify events must not allocate a physical item twice or settle an owner twice.
- **Cross-system incomplete write:** R2 upload succeeds but D1 pointer fails, or vice versa; old published snapshot remains usable.
- **Auth/security:** customer/consignor/founder role cannot view or alter another owner's private balances. Test object and API-level authorization; D1 does not supply Postgres RLS.
- **Capacity:** D1 Free 100k/day writes and 500 MB per database, latency under real Railway-to-Worker traffic, source ingestion costs and rate limits.
- **Operational fallback:** stale/absent data must say “Market Value unavailable” internally and show no fabricated retail or guide price. No unintended Shopify sync.

## 5. Test and go/no-go matrix

**A. R2:** every snapshot has source consent record, checksum, immutable manifest, readback and restore test; 272,079 expected references checked for exact counting and key uniqueness.

**B. D1 read model:** actual D1 (not local SQLite only) migration, exact-key queries, pagination, price retrieval and stale/invalid publication fallback; full category counts; p50/p95 measured from Railway and billable rows documented.

**C. Pricing:** deterministic source classification, exact print matches, negative samples (promo/foil/slab/language), available guide vs verified sold distinction, FX/rounding, stale/outlier gates, rollback. Audited per-game coverage.

**D. Operational migration:** per-table counts and referential integrity; founder A cannot change founder B's owner ID; a Shopify multi-owner order settles exactly; 100 repeated webhooks result in one financial posting; refunds and reversals equal source; no missing audit events.

**E. Cutover:** signed access paths, secrets rotation, backup and restore demonstrations, feature flags, rollback drill, owner/consignor settlement parity and explicit founder sign-off.

**Implementation status as of this document:** Stage A D1 synthetic pilot previously tested; R2 catalogues and historical price backup exist. Stage A live database cutover, Stage B global price publication, Stage C operational cutover and Stage D retirement **not complete**. Merged Cardmarket pilots and source identity work do not represent published prices.

## Operational ownership of this decision

The founders have selected **R2 + D1 and migration away from Supabase**. The existing repository project instructions still describe PostgreSQL/Supabase as master; update those instructions after the cutover interfaces and transaction behaviour are approved to prevent new PostgreSQL-only implementation. Until the operational cutover, **the live PostgreSQL records remain authoritative**; this is a transition safeguard, not a proposal to keep Supabase permanently.
