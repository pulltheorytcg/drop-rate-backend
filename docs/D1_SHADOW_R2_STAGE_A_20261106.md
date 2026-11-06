# Stage A implementation: Cloudflare R2 -> D1 shadow catalogue — 6 Nov 2026

## Why / scope

Drop Rate's target is Cloudflare R2 for 272,079+ card reference objects, artwork and historical source data, Cloudflare D1 for indexed current reads and eventually fully audited owner/financial records, with Railway FastAPI implementing deterministic pricing and ownership business rules. **Supabase PostgreSQL remains the live transactional master until explicitly cut over after parity and replay tests**. No upgrade, alteration, deletion or disabling of Supabase is part of this PR.

This PR implements **the first genuine portable D1 read-model generation contract**; it is not a completed migration or published 272k-price pipeline.

## Components and boundaries

- \`backend/app/d1_shadow_catalogue.py\`: accepts ONLY a checksum-verified, fully restored R2-first Snapshot; validates exact source tuple and sha256 stable key, all rows and paging (including future releases); canonicalizes an immutable D1 projection; generates bounded, parameterized D1 insert statements.
- Three distinct D1 tables: generation registry, immutable shadow card rows and the single **active generation pointer** per original provider/system/language partition. The active view excludes partial/unpublished imports. Indexes cover exact ID, set page and normalized name prefix. **No Market Value column exists in this stage**, so historical Cardmarket guides cannot accidentally appear as real sold-based Market Values.
- Activation is a **single atomic D1 SQL statement** only when staged row count equals signed R2 expected count. The active pointer can be reverted to a previous fully staged generation after a failure. Changes to a source manifest never overwrite the previous generation.
- \`tools/d1_shadow_remote_probe.py\`: remote Cloudflare test with exactly 18 synthetic Magic printings and two different source revisions. It creates at most ONE new D1 database with \`drop-rate-d1-synthetic-<run_id>-<attempt>\`, only after source token validation and a conservative account database count check; tests partial publication rejection, activation, exact readback, new generation isolation and rollback; retains the synthetic DB for review, makes no live R2/Shopify/Supabase queries or modifications.
- \`.github/workflows/d1-shadow-r2-stage-a.yml\`: pull requests run offline tests with **no Cloudflare credentials**. Only a trusted **main-branch push** passing offline checks attempts the isolated remote Cloudflare smoke test using the pre-existing D1-scoped GitHub secret \`CLOUDFARE_D1_PILOT_TOKEN\`. If the token expired or lacks permissions, the remote smoke fails safely and the report must say so. Never log or print token values.

## Failure points / known limits

1. The remote smoke source is a *synthetic R2-shaped, checksummed fixture*. The code can project any existing verified R2-first Snapshot, but **we have not read the actual 153,662 Magic R2 records into D1** or rerouted production search. Those require a private, signed Railway-to-Cloudflare ingestion path, D1 query performance checks and source partition parity first.
2. D1 Free quotas, live source and price rights, high-volume imports and durable Worker's authentication need separate validation. The smoke refuses to allocate a database if more than seven were listed; this does not fully inspect pagination for >100 databases. No billing plan is modified.
3. Current SQL/Postgres pricing freshness/grade/business rules are **not** portable to SQLite unchanged. Do not use the D1 shadow catalogue to serve monetary values or settlement balances.
4. D1 active pointer checks row **count** and the original R2 manifest digest, and the importer verifies exact sampled rows; a production-grade all-record readback / signed projection digest parity check is still required before routing traffic. Do not treat a successful smoke test as proof of full-scale cryptographic equivalence.
5. The exact 272,079 cards include multiple independent source partitions. Each partition is published atomically and separately; there is no invented single transaction across all partitions or between R2 and D1. On failure, the previous active source remains intact.
6. Owner inventory, financial ledger, Shopify webhooks and authentication are **unchanged**. Later migrations must reimplement Postgres RLS/RBAC, unique event IDs, audit history and multi-owner settlement invariants in the FastAPI/D1 boundary.

## Testing

- Offline: \`PYTHONPATH=backend:tools python -m pytest -q tests/test_d1_shadow_catalogue.py tests/test_d1_shadow_remote_probe.py\`
- Read-only source integrity: original R2 digest, all records, exact keys, future releases, invalid Cardmarket ID rejection, duplicate identity rejection, bound-parameter inserts.
- SQLite D1 emulation: incomplete generation invisible; completed generation activates; a partial next generation cannot replace it; atomic swap and rollback restore the previous exact data.
- GitHub-protected remote Cloudflare test: account scoped to \`e4d4b363540e991048d2e1812d5ef53e\`, 18 synthetic printings in isolated database, no pricing or financial data, independently reviewed response/log and metrics before scaling.

## Go/no-go for Stage B

Confirm real D1 API access and report including database UUID and exact live smoke results; then implement R2 private readback and *delta* D1 ingestion, a restricted Cloudflare Worker API, multi-source full-key parity, p50/p95 latency and billable reads/writes. Only after matching data and access rules should any production catalogue read switch to D1. Storefront price publication, ledger and Supabase retirement remain separately gated.
