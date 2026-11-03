# Cloudflare D1 + R2 feasibility — catalogue read model (3 Nov 2026)

**Status: research / local synthetic SQLite proof; NOT a production cutover.**
The existing PostgreSQL master, Railway FastAPI service, R2 production
publications, Shopify integrations, physical inventory, owner allocations and
financial ledgers are unchanged. No live D1 database was provisioned, no paid
plan was activated and no production rows were deleted.

## What, why, connections, failures, verification

- **What:** evaluate a separate read-only D1 catalogue candidate, never an R2
  bucket masquerading as a transactional database.
- **Why:** 69,697 card references, quote evidence and artwork need to scale
  without consuming the current Free PostgreSQL 500 MB allowance. R2 is still
  appropriate for images, immutable snapshots and large source evidence.
- **Connections:** current source PostgreSQL -> versioned and integrity-checked
  projection -> optional D1 / Cloudflare Worker read endpoint -> Railway API;
  R2 for images and archives. PostgreSQL remains authoritative for founder
  inventory, ownership, orders, audit, settlements and the canonical source
  until a separately approved architecture migration.
- **Failures to test:** stale D1 generation, incomplete publication, language
  and variant identity collisions, changed index semantics, cost/row-read
  amplification, missed Shopify changes, authorization leaks, Cloudflare API
  errors and slow Railway-to-Worker round trips. Missing/invalid D1 generation
  must fall back to the *current* authorized path without a silent price guess.
- **Testing:** local SQLite schema/index/foreign-key tests; actual PostgreSQL
  live read-only counts and query plans; later a temporary **remote** D1 pilot
  with signed Worker APIs, production-like queries, network p50/p95 and full
  parity before any traffic routing or source-table retirement.

## Live read-only measurements

Project: Supabase `ozrxenrdladkooixutmm` (project name `pull-theory-dev`,
currently used by the Drop Rate services). On 3 Nov 2026:

| Observation | Result |
| --- | ---: |
| PostgreSQL database footprint | **419,966,099 bytes** |
| Existing safe bulk-import pause | **400,000,000 bytes** |
| Canonical reference card rows | **69,697** |
| Physical inventory records (must stay under controlled SQL ownership) | **617** |
| `reference_cards` relation | ~77 MB |
| `reference_market_prices` relation | ~59 MB |
| `reference_catalogue_prices` relation | ~45 MB |
| PostgreSQL backend Python modules directly referencing those source tables | **37** |

Reference-card counts are: Pokémon 36,927; One Piece 9,007;
Dragon Ball Super Masters 9,002; Dragon Ball Fusion World 7,595;
Naruto Bandai Legacy 4,487; Naruto Kayou 2,679.

Schema dependency checks against PostgreSQL system catalogues:

| Source | Incoming FKs | Custom triggers | Indexes | RLS enabled |
| --- | ---: | ---: | ---: | --- |
| `tcg.reference_cards` | 6 | 4 | 6 | Yes |
| `tcg.reference_market_prices` | 0 | 5 | 1 | Yes |
| `tcg.reference_catalogue_prices` | 0 | 5 | 1 | Yes |

The six card foreign keys come from recognition fingerprints, asking history,
asking prices, product details and both price tables. A read-only D1 mirror
**does not free these PostgreSQL bytes**; physically retiring the SQL source
would require replacing referential integrity, access control, write paths and
dependent queries, or retaining a minimal SQL identity table. No drop/truncate
is authorized by this feasibility note.

Production PostgreSQL `EXPLAIN` of a Pokémon English set page joining both
price tables used the `reference_cards_set_idx` and both price-table primary
key indexes. The port must retain index-backed set pagination and exact
four-part printing identities (`provider`, `system_code`, `language`,
`provider_id`). Names and set numbers alone are **not** canonical identities.

## Local SQLite / D1-style smoke test

`python tools/d1_catalogue_feasibility.py` creates **synthetic** rows matching
the six real game-level card counts; it does not copy private records or make
external network requests. It probes the following SQL shapes:

1. Exact four-column printing lookup with current detailed/catalogue quote
   fields (without making a pricing eligibility decision).
2. Bounded 25-row set pagination and deterministic sort.
3. Indexed normalized-name prefix search.
4. Composite foreign-key enforcement for local demonstration only.

Run result on the local executor: **69,697 synthetic cards**, ~31.8 MB in
SQLite (no full quote/evidence payloads), exact/filtered/search index plans
selected, seven tests passed via
`python -m unittest discover -s tests -p test_d1_catalogue_feasibility.py -v`.

Illustrative *local in-process SQLite only* timings (150 warmed operations):

| Query | Median | p95 |
| --- | ---: | ---: |
| Exact printing with two price joins | 0.003 ms | 0.004 ms |
| 25-card set page and price joins | 0.066 ms | 0.102 ms |
| Normalized-name prefix (20 results) | 0.017 ms | 0.018 ms |

These **must not** be presented as real Cloudflare D1 throughput, billable
rows-read, network latency, response time, or storage estimate for actual
market data. They prove only that a minimal, bounded SQLite query shape works
and uses indexes. The complete current PostgreSQL queries include JSONB
pricing eligibility, freshness and publication validation, owned inventory
aggregation, array aggregation, Postgres functions/triggers and security
policies; none are ported by this probe.

## Cloudflare pricing and quotas checked 3 November 2026

Cloudflare R2 Standard, **different from D1**:

- 10 GB-month storage free every month.
- Above free: $0.015 per GB-month. **100 GB additional** beyond the free 10 GB
  is approximately **$1.50/month** in storage (not necessarily £1.15 after
  currency conversion/tax). 100 GB **total** is approximately $1.35/month.
- 1 million Class A and 10 million Class B operations free per month;
  beyond that, Standard charges $4.50/million Class A and $0.36/million
  Class B operations. Egress from R2 is free.

Cloudflare D1:

- Workers Free: maximum **500 MB per D1 database**, 5 GB across the account;
  5 million rows read/day and 100,000 rows written/day included.
- Workers Paid (base plan **$5/month minimum**): up to **10 GB per D1
  database**, first **5 GB** of account-wide storage included then
  **$0.75/GB-month**, first 25 billion rows read and 50 million rows written
  per month included. Query/request traffic and usage above allowances can
  incur charges. This does not include Railway or Shopify charges.
- A full daily refresh of 70k card identities **plus** market price rows could
  exceed 100k D1 Free writes/day; only changed rows should be written, with
  explicit idempotency and throttling. We have **not measured** actual future
  write volume or D1 billable read counts.

Official source URLs (Cloudflare documentation, live at audit date):

- https://developers.cloudflare.com/r2/pricing/
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/d1/best-practices/import-export-data/

## Architectural decision before live pilot

**Recommendation:** Do not move ownership/consignments/settlement master
records to D1 during the storefront push. If the founders wish to keep a
small PostgreSQL footprint, pilot **public reference catalogue and cached
market-read projections** in D1 while retaining PostgreSQL master and R2
snapshots. That may improve read scaling, but **alone will not shrink SQL**.
The physical capacity objective needs a separately reviewed source-of-truth
transfer or evidence-blob offload, with the six FK contracts, security and
finance history preserved. The architecture rules must be updated before
promoting D1 from read model to authoritative source of canonical cards/prices.

Next gates:

1. Confirm available Cloudflare account binding/API and D1 plan **without
   changing billing**. Do not assume R2 quota is D1 quota.
2. Provision isolated test D1 only with explicit environment and cost scope;
   no production user data. Compare real request latency from Railway with
   native PostgreSQL and current R2 caches, and log D1 billable row counts.
3. Expand to all current price/source eligibility SQL, Japanese variant
   mapping, complete source/snapshot checksums and appropriate RBAC.
4. Run shadow read parity, corruption/retry/fallback and webhook checks; only
   then seek explicit architecture approval for source-record cutover.

The existing **69,697-row restorable R2 backup** and its manifest are retained.
This pilot does not overwrite or replace that archive.
