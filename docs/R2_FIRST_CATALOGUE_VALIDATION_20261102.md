# Drop Rate — R2-first delivery and recovery validation (2 November 2026)

## Decision

The existing R2-first catalogue/market publication is current and hash-verified; it is **not** permission to delete `tcg.reference_cards`, price caches, or other live PostgreSQL source data. In Drop Rate's architecture, PostgreSQL remains authoritative for canonical identity, ownership, current prices, inventory, audits and settlements. R2 carries immutable private shared-input publications, not editable store state.

## Read-only production checkpoint, 23:20 UTC

| Gate | Evidence | Result |
| --- | --- | --- |
| Source backup/typed restore | 69,697 rows/14 columns, private R2 readback and PostgreSQL temporary-table full restore verified earlier on 2 Nov (PR #874 audit receipt) | PASS |
| Catalogue publication freshness | Generation **122486** equals `published_generation`; 69,697 card refs, 1,472 sets, 3,893 sealed refs, 2,056 products/profiles; 161 parts, 29,757,332 raw bytes | PASS |
| Price-input publication freshness | Generation **64967** equals `published_generation`; 59,693 market records, 27,676 catalogue guides, 3,889 sealed quotes; 366 parts | PASS |
| Full private R2 loader | Production Railway `CATALOGUE_R2_LIVE_LOADED generation=122486` at 16:38 UTC, after its checksum, count, schema and duplicate-identity checks | PASS |
| Production service health | 8 services, zero recent deployment failures, zero pending Railway changes | PASS |
| Live customer speed | No authenticated `/api/v1/catalogue-browser/products` request latency samples in the inspected 24-hour window | **UNVERIFIED** |
| Safe database reclamation | PostgreSQL database measured 419,957,907 bytes (~420 MB); `reference_cards` alone 77,152,256 bytes and remains referenced by recognition, inventory, pricing and catalogue code | **NOT AUTHORIZED** |

## Failure found in code

The two background R2 readers returned SQL fallback correctly after an unreadable object, but on the next visitor request immediately attempted the same entire publication again. Repeated requests during an outage could thus create avoidable outbound reads, CPU work and log noise even though source rows were safe.

The reviewed patch records a failure's `(generation, manifest_digest)` and pauses repeated attempts for **60 seconds**. It never delays SQL fallback; any newly published generation retries without waiting. It retains the original checksums, schema bounds, immutable identity validation, authenticated SQL overlays and operator flag backout. No cleanup or deletion code is introduced.

## Acceptance plan (remaining)

1. GitHub CI must pass the new fault-injection tests and existing catalogue, price, RLS and deployment suites. Do not merge on a partial/failing check.
2. On a signed-in founder account, open Games, a Pokémon set, a One Piece set, Comics/Manga, a sealed set and an owned-only page; compare the visible exact printings, quantities and market values with the existing PostgreSQL-backed route. Exercise search, game+type filters and value asc/desc; do not approximate prices or substitute artwork.
3. Capture real `/api/v1/catalogue-browser/products` response timings: p50 and p95, browser page completion, slow-stage logs and any 5xx. The public health endpoint alone is insufficient.
4. Inject missing/corrupt R2 fixture objects only in automated tests, **not** production. Assert no R2 object is used, SQL fallback stays available, retries are bounded, and recovery works when the object returns or a new publication is committed.
5. Only after these checks, separately decide on any non-authoritative redundant cache reclamation. Never remove canonical cards, inventory, owner attribution, financial transactions, audit history or current pricing source tables merely because an R2 backup exists.

**Backout:** Existing independent `TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED=false` and `TCG_R2_MARKET_DELIVERY_ENABLED=false` switches restore ordinary SQL. Revert this patch to remove the retry limiter. Do not edit the 400 MB importer guard or delete any source objects.
