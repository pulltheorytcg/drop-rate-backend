# Magic: verified source to quota-limited Cloudflare D1 shadow

**Implementation 6 November 2026. No live Shopify, pricing, founder ownership or financial migration.**

## What

A signed, source-scoped `tools/d1_magic_shadow.py` pipeline and `.github/workflows/d1-magic-r2-shadow.yml` continue Drop Rate's **full** R2/D1 catalogue build. It targets the exact previously verified MTGJSON partition:

- `mtgjson/MAGIC_THE_GATHERING/English`
- **153,662** original R2 printing/finish references (308 parts, 93,973,955 raw bytes)
- Immutable published manifest SHA256 `be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28`
- Source-only audit [#933](https://github.com/pulltheorytcg/drop-rate-backend/pull/933) passed full R2 SHA256 and exact-key reconstruction; this new writer migrates the indexed D1 shadow later.

Only the fixed trusted GitHub `main` workflow for Magic D1, signed with short-lived GitHub OIDC, may retrieve its original R2 manifest/parts from Railway FastAPI. The source-only Magic audit, Yu-Gi-Oh, Lorcana, untrusted branches and `workflow_dispatch` cannot impersonate this path. Existing PostgreSQL RLS and maintenance-admin role checks remain in force.

## Why now / exact rollout

Cloudflare D1 Free permits 10 databases, 500 MB **per database**, 5 GB total, 100,000 rows written and 5 million rows read **per UTC day**. Indexed writes count; Cloudflare can reject operations earlier because of other account usage. Source: https://developers.cloudflare.com/d1/platform/limits/ and https://developers.cloudflare.com/d1/platform/pricing/.

A full 153,662-card import on Free would be unsafe in one run. The Magic writer therefore:

1. Enumerates actual D1 databases and `PRAGMA page_count/page_size`, rejecting missing or invalid identities, >390 MB existing DB sizes or >=4 GB total.
2. Reads the original Yu-Gi-Oh `shadow_cards` **45,418** count, original source manifest, `shadow_generations` projection SHA and active pointer. **No Magic D1 DB is created and no R2 source is fetched until Yu-Gi-Oh's fully checked active partition is present.**
3. Waits one additional UTC day after any Yu-Gi-Oh staging receipt; prevents same-day 8,000 Yu-Gi-Oh + 5,000 Magic co-writes.
4. Reserves at least two D1 Free database slots for legacy and supplemental reference partitions. If slots or disk safety are unavailable, reports pending and does not create Magic D1.
5. Fetches/revalidates every original Magic part and full source sha via the Railway private endpoint, then sorts stable card identities for exact D1 row projection hashing. Rejects source generation changes, missing parts, wrong finishes/languages or invalid source keys.
6. Stages **no more than 5,000 new Magic references per UTC day** into a dedicated, isolated, indexed D1 shadow database. An immutable per-UTC-day receipt is inserted *before* any card rows. A duplicate main push or schedule cannot spend the same source budget twice.
7. Every resume reads back **all staged D1 rows** and compares each original ID/field to source. The source pointer stays inactive while partial.
8. Only at **153,662 rows** does the runner verify the entire D1 SHA256 projection, atomically activate the isolated private generation, and reverify it. It still does **not** route production search or change owner data.

The daily GitHub cron is `05:43 UTC`, after the existing 03:17 Yu-Gi-Oh writer and 04:05 read-only capacity audit. The trusted-main workflow publishes `drop-rate-d1-real-magic-parity` as **pending** for verified partial/blocked stages and **success** only for the fully matched D1 source. It produces a SHA/count artifact.

## Failure points and tests

- **Source identity error:** every part SHA, source content checksum, original printing/finish ID and manifest must agree. No name-based matching.
- **D1 allowance / storage:** fail closed when YGO incomplete, recent writes, low DB slots, storage limit or quota API error. Never bypass metrics or delete existing D1 DBs to free space.
- **Partial batch:** immutable day receipt means a crash can resume only on a later day, after exact prior row readback. No partial activation.
- **Tampering:** changed R2 source or staged row refuses continuation, rather than changing a price or overwriting an old row.
- **Auth:** GitHub workflow-specific OIDC, no credentials in clients, Postgres FORCE RLS preserved. Tests ensure a preflight-only OIDC cannot read Magic D1 endpoints.
- **Financial separation:** **zero Market Value, acquisition costs, physical owner assignments, Shopify, order and settlement writes**; original Supabase/Postgres remains authoritative for these live operational systems pending their own distinct migration.

## Independent gates still outstanding

- Yu-Gi-Oh full 45,418 D1 parity (first 8,000 confirmed as of 6 November).
- Real D1 capacity/usage audit and daily budget allowance.
- The legacy R2 source family (69,697 cards + 9,489 set/sealed/comic/profile rows) needs **its own distinct source-specific D1 projection**, not an assumption that every legacy relation is a card.
- The 1,826 sports/figures source rows need separate exact-source permission checks, identity proofs and bounded D1 import.
- Only after all target partitions have full parity and production search performance/rollback checks can a live catalogue read cutover occur. Real market-value pricing and the owner/auth/financial system migration follow separately.
