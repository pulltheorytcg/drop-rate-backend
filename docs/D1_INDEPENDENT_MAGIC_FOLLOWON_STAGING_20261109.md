# Independent, quota-safe Magic/sports/figures D1 staging

9 November 2026 · migration tracker https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What / why

Magic MTGJSON and the sports/figures catalogues have their own signed, immutable R2 source manifests and separate private Cloudflare D1 data. They do not share a canonical identity or transaction with the separate Yu-Gi-Oh D1 generation. Requiring the entire 45,419-row new Yu-Gi-Oh generation to finish before staging Magic's 153,679 records is unnecessary and delays full Supabase exit.

After PR #1043, the **inactive** follow-on importer recognises Magic's current 153,679 R2 source and 155,505 total independent follow-on records. This change removes the requirement that Yu-Gi-Oh's *whole* D1 source be complete first. It keeps the **same-day write receipt gate** and makes Yu-Gi-Oh source-independent rather than pretending Yu-Gi-Oh is already complete. Yu-Gi-Oh still requires its own exact checksum and active partition before serving it.

## Connections and security

Protected GitHub approval (SHA+run ID) → signed R2 full manifest and part verification → approved sports/sports heritage/figures/Magic generation → isolated per-source D1 prefix checks and private active pointer, without any Shopify/listing, owner, authentication, market-pricing or settlement authority.

The unrelated D1 jobs (Yu-Gi-Oh, follow-on including Magic, original-game legacy) now have the SAME GitHub Actions **write-job-only** concurrency group: `drop-rate-d1-catalogue-private-single-writer`. Only one can hold that group at a time. Their prior workflow-level concurrency and exact maintainer SHA/run-ID approval still apply. A stage job also refuses if the observed Yu-Gi-Oh daily write receipt is for the current UTC day. A missing Yu-Gi-Oh DB no longer blocks other verified sources; a malformed or uninspectable existing Yu-Gi-Oh receipt still rejects before any other D1 write.

The original follow-on D1 source staging limit remains 8,000 **new records per UTC day** and original private database slot and file-size checks remain. No Paid-tier overage budget or indefinite write allowance is authorised by this PR.

## Failure and tests

Offline tests cover independently staging sports with YGO incomplete/missing/new-generation pending, fail-closed YGO same-day receipt and malformed receipt, independently diagnosing a bad YGO active pointer, full R2 source SHA checks, existing tampered prefix, duplicate id and SQL D1 failure. The three source-specific private GitHub workflow jobs share one global write lock. Full backend/Python PostgreSQL, n8n and dashboard suites plus dedicated YGO, follow-on and original legacy offline source tests must pass.

## Explicit limitation / rollback

This change creates NO Cloudflare D1 database, performs NO real D1 import, sets NO approval variables and switches NO application search/checkout path on its own. The GitHub protected write job stays inactive until a maintainer explicitly approves its exact commit and run. Future real D1 imports must prove source/consumer parity and monthly usage/cost. A verified same-day writer collision, missing source manifest, bad SHA or loss of generation continuity blocks the stage. Roll back only the staging guard and shared job-concurrency changes if necessary; leave the current Supabase/R2 source authoritative. All eight Supabase retirement gates remain unreleased.
