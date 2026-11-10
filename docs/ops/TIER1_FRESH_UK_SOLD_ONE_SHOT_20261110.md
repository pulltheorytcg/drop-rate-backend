# 10 November 2026 — one-item fresh UK sold pilot (review and deploy gate)

**Status: CODE STAGED, NO EXECUTION, NO PRICING WRITES until CI and explicit Railway receipt.**

## What / why / connections
The user's objective is **Market Value only**: prior 505 physical Tier 1 items had 0 safe immediate INSERT / UPDATE candidates under the strict 14-day sold-evidence preview. Widening historic UK GBP observations to 90 days shows only **one** currently unpriced item with five like-for-like sales: `INV-3B801C9CE17B48DEA1EE0DD8AB38EA25`, the already-approved and Shopify-published English Near Mint **Charmander / Phantasmal Flames / 011/094 / Normal**. Five recorded Trawl sold items dated 20–30 Sep 2026 were last ingested 9 Oct, so the £1.43 *historical median* MUST NOT be published as a fresh current price.

The targeted script `backend/scripts/tier1_fresh_sold_preview.py` reads exactly this inventory item with the existing authorized maintenance actor, forces a database **read-only session**, verifies exact printing/language/condition, then uses the existing deterministic UK eBay sold normalization and Trawl adapter to query **ONE PAGE** with no retries. It never calls an apply path or writes SQL/R2/Shopify, and never updates the existing **£1 Store Price**. The output omits seller listing titles, URLs and record IDs. It marks a candidate for **separate manual review** only if five normalized UK sold comparables are returned and at least one sold within the last 14 days. Otherwise it remains BLOCKED.

Provider terms: [Trawl](https://trawl.dev/terms) permit data to be used in one's own products while prohibiting raw API resale and respecting credit/rate limits. Trawl is independent of eBay. The official [eBay Browse API](https://developer.ebay.com/api-docs/buy/api-browse.html) provides active offers; eBay's official sold sales API Marketplace Insights is limited-release and cannot be assumed available. None of this certifies Trawl records as real sales without item-level evidence.

## Failure points and protection
- Expired, changed or unconfirmed physical identity → abort before provider I/O
- Database connection or maintenance actor invalid → fail closed; **do not** bypass RLS
- Trawl 429 or provider timeout → report `FAILED_CLOSED_NO_RETRY`, no automatic retry, no paid upgrade
- Fewer than five exact UK sold records, missing provider proof, stale 14-day window → BLOCKED, no monetary candidate
- New source terms / rights issue → stop; no raw-data reuse assumption
- Production startup/Shopify provider effects → unchanged; operator bulk hold remains `DROP_RATE_CATALOGUE_BULK_HOLD=true`
- Existing owner Store Price £1 remains untouched in all cases, including if preview is READY

## Deployment/runbook requirements
1. Merge this file and BUILD_STATUS entry with tests **before** creating live Railway audit workload.
2. Use a temporary **isolated Railway one-shot**, no HTTP domains, no cron, restart NEVER, ≤1 vCPU / 1 GB RAM, 75-second **hard subprocess timeout**, **single** `--limit 1 --read-only` invocation. Source pinned to reviewed main SHA. Empty service creation alone cannot run app code; provision then stage complete source/command/variables before first application deploy.
3. Only three secret **references**, never actual values, from existing `drop-rate-api-live`: `TCG_DATABASE_URL`, `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID`, `TCG_TRAWL_API_KEY`. IPv6 egress may be required for Supabase. No R2 credentials. Do not deploy or restart the live app.
4. Review entire staged Railway patch, run once, capture receipt from exact deployment ID, check evidence counts/expiry, and delete this temporary service. Do not reactivate bulk jobs.
5. Verify SQL readback confirms the inventory Market Value remains NULL and Store Price remains £1; verify no price snapshots were inserted. Record the result in this runbook/BUILD_STATUS by PR.
6. A real price write requires a **separate** reviewed, evidence-supported deterministic FastAPI value-only command that must NOT modify store selling price and must preserve all original observation history. This pilot does not implement that command.

## Tests
`tests/test_tier1_fresh_sold_preview.py`: five+comps, current 14-day sale requirement, reject stale, missing normalized provider evidence, 4 comparable failures, no private IDs or listing URLs in receipt, fixed target identity. Full GitHub backend and dashboard CI; no provider tests in CI. Verify live service readback, no media/financial effects.
