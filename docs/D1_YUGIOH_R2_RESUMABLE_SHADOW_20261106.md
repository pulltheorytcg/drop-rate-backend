# Drop Rate Yu-Gi-Oh! R2 -> D1 shadow: bounded/resumable production-source import

**6 November 2026. This is a safe private reference-data migration; no customer-facing cutover or market-price publication.**

## What and why

The R2 catalogue registry on 6 November 2026 contains **45,418** English `ygoprodeck/YUGIOH` card references (22,007,112 raw bytes, ~91 R2 parts). Lorcana's 3,505 references previously passed byte-for-byte D1 parity on a separate isolated database.

Cloudflare D1 Workers Free provides only **100,000 rows written per day account-wide**, and maintaining table indexes can add multiple metered writes per inserted row (Cloudflare documentation: https://developers.cloudflare.com/d1/platform/pricing/ and https://developers.cloudflare.com/d1/platform/limits/). Therefore a single 45k write batch is not safe to assume. R2 remains the authoritative immutable source; D1 only shadows indexed canonical reference data.

## Connections / boundary

- Railway FastAPI `/api/v1/internal/d1-shadow/yugioh/manifest` and `.../part/{ordinal}` reveal **only** the exact current approved `ygoprodeck/YUGIOH/English` content-addressed R2 part after checking a short-lived, **RS256-signed GitHub OIDC** JWT. The OIDC must identify exact repository owner/repo IDs, branch `main`, workflow `.github/workflows/d1-yugioh-r2-shadow.yml`, and `push` or `schedule` event. No user-supplied source identifiers, R2 object keys, database IDs or other auth bypass.
- The existing maintenance-admin actor and read-only transaction preserve forced Postgres RLS. No Supabase writes. R2 S3 credentials remain only on Railway; GitHub's D1-scoped token remains only on GitHub.
- `tools/d1_yugioh_shadow.py` validates every original R2 manifest/part SHA256, rebuilds its entire canonical snapshot, then opens a single isolated private D1 database `drop-rate-d1-real-yugioh-shadow`. The source count must be **exactly 45,418**; changed releases need a reviewed new manifest generation.
- Resume reads **every staged D1 row back** and checks every field against its corresponding R2 record before any insertion. Old staged rows can never be silently corrected/overwritten.
- Adds **at most 8,000 new card-reference rows per UTC day**, recorded with a permanent daily budget receipt *before* the first insert. This leaves substantial conservative room for D1's multi-index write accounting and other account operations; it is not a guarantee of Cloudflare quota headroom if other services use D1 that day.
- The workflow launches for the trusted main-branch merge and then at `03:17 UTC` daily, with concurrency limited to one writer. The daily budget receipt makes restarts idempotent. Cloudflare's server-side limits are final authority; a quota or network failure leaves an inactive partial shadow for a future reviewed retry.
- Only when all **45,418** cards are staged does the importer verify the complete SHA256 D1 projection, atomically mark the private D1 shadow generation active, and **verify it again**. This does **not** switch live catalogue readers. Only the final fully proven status `REAL_R2_YUGIOH_TO_ISOLATED_D1_VERIFIED` gets a GitHub **success** commit status. Incremental batches report **pending**.

## Failure checks and tests

- Offline unit tests use fake signed feeds and SQLite D1 transport; prove missing and spoofed OIDC workflow/auth rejects, original Lorcana route remains isolated, invalid R2 part checksum never creates D1, changed manifest mid-import fails, corrupt staged row prevents resuming, daily duplicate run makes no inserts, multi-day continuation and final hash activation. Existing Lorcana shadow can be independently reverified without duplicate creation.
- GitHub Actions PR job has no migration credentials. Only protected `main` jobs hold D1 API token and GitHub-issued OIDC claims. On failure, no price/Shopify/owner/settlement data changes and production reads remain on the current system.
- The full R2 YGO source is only card-reference *metadata*: it has **no approved market valuations**, slab grades, raw art quality guarantees, eBay sold proofs or Cardmarket finish-specific evidence.
- Account budget guard refuses D1 creation when the database count nears the Workers Free quota of 10. Existing source DB may be re-used **only** if its generation metadata and complete staged prefix agree with the R2 source; never modify an unknown existing database.

## Verification and subsequent scale

Monitor GitHub commit status `drop-rate-d1-real-yugioh-parity`, private Actions report `d1-yugioh-real-shadow-report.json`, and exact source parity. Do not consider a workflow green alone proof of full source migration. Before scaling to MTGJSON's **153,662 reference** Magic partition, assess its 93,973,955-byte source, up to 308 parts, 500 MB D1 Free per-database capacity and daily index-write costs. Stage Magic in deliberately bounded batches with the same immutable checks; don't combine multiple games' daily imports if they may exhaust the shared free-tier budget.

**Financial cutover separately gated:** Supabase Auth, ownership, transactions, fees, settlements, refunds, audit, and Shopify integration stay untouched until tested on D1 with atomicity, RBAC and rollback.
