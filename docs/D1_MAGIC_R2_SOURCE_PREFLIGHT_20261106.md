# Magic (MTGJSON) R2-to-D1 migration — mandatory source preflight

**6 November 2026. Source-only verification, not a D1 migration or pricing publication.**

## What we're building and why

The protected GitHub Actions workflow `.github/workflows/d1-magic-r2-preflight.yml` validates the **153,662** original English `mtgjson/MAGIC_THE_GATHERING` reference records registered as an immutable Cloudflare R2 source. Original registered 6 November manifest digest is `be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28`, source raw bytes approximately 93,973,955. This is *not* the number of market-valued cards. Yu-Gi-Oh!'s first 8,000 of 45,418 references successfully staged in an isolated D1 shadow on 6 November; its remaining D1 batches run under an 8,000-new-card daily source-specific budget. We **do not** use Magic to compete with that D1 Free quota.

## Connections and scope

- The protected FastAPI export exposes only `/api/v1/internal/d1-shadow/magic/manifest` and `/magic/part/{ordinal}`, behind short-lived, signed GitHub-issued OIDC for **exact** repository identity, workflow ref, main branch, hosted runner and push event. Missing, changed or mis-scoped claims fail closed.
- Existing read-only `user_connection` with verified maintenance-admin access keeps PostgreSQL FORCE RLS. No private founder, consignor, settlement or customer data can be returned. R2 source digest is required to match the current published source registry and the fixed exact card scope.
- GitHub's main-branch preflight reads the manifest and all source parts, verifies SHA256 checksums, cumulative R2 content identity, stable card keys and the resulting source projection. It publishes a **source-preflight** success/failure GitHub status, plus an artifact of counts and digests.
- The preflight does **NOT** possess a Cloudflare D1 API token, create a database, write a row, change Shopify, set a price, change a physical owner, use n8n or switch any live traffic. In particular, a green Magic preflight is NOT a D1 migration.
- The current official Cloudflare D1 Free plan has 500MB maximum per database and 100,000 rows written/day total, with indexed writes counting toward the limit. Verify actual account usage and estimated on-disk size before a future Magic D1 staging phase. Cloudflare: https://developers.cloudflare.com/d1/platform/limits/ and https://developers.cloudflare.com/d1/platform/pricing/.

## Failure points / tests

- Any missing R2 part, altered raw object, unexpected scope, generation change, wrong count, source manifest mismatch, malformed printing/finish/language, unauthorized OIDC workflow, unexpected redirect, wrong R2 source or excessive source size blocks publication.
- The workflow runs offline source/RLS/old-game regression tests before signed live access. Unit tests prove no D1 token is present and no D1 write client is imported.
- Main-branch workflow may initially receive 404/503 while Railway deploys; only these *temporary* source-access responses are retried. It never retries a 401/403 or malformed data to bypass access policy.
- Only success when all **153,662** original reference identities pass full checksum and deterministic projection verification. The report contains `verified_d1_rows: 0` intentionally, even on success.

## Next cutover gate

After the first Magic source-only proof passes and the Yu-Gi-Oh! complete D1 parity is verified, design a distinct, fixed-source Magic D1 shadow with a **shared account-wide** write-budget gate, disk-size preflight, and full reference readback. Do not automatically enable simultaneous daily Magic and Yu-Gi-Oh! imports, because their D1 index updates would share the Free quota. Only then work on historical market data adapters and verified **Market Value** publication; no MSRP, guide estimate or invented sold data.

Owner allocations, payment ledgers, Supabase Auth replacement, Shopify integration and their full audit/rollback rehearsals remain separate production cutover milestones.
