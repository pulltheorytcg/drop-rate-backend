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

## First isolated execution and safe diagnostic correction (20:52–20:56 UTC)

- The original script merged by PR #1066, SHA `e9a8a161557a67b30c5430adc924bef52f51ce68`. Temporary Railway service `tier1-charmander-sold-readonly-once-20261110` (`6e207142-b925-4d88-96a5-b4d61e161d3d`) used reviewed SHA, **one** fixed Charmander, strict 75s hard timeout, no restarts or domains, 1vCPU/1GB, IPv6 egress, reference variables only.
- Deployment `137b9925-0621-44fe-9fb2-d575c55e03b5` **CRASHED** almost immediately: `TIER1_SOLD_ONE_SHOT {"status":"FAILED_CLOSED_NO_RETRY","error_type":"RuntimeError","applied":false}`. **No provider sale receipt, zero accepted pricing changes**. The first version intentionally suppressed detailed errors, so this alone cannot prove what failed.
- A **separate code-free, no-DB, no-provider diagnostic** deployment `f9e26a1f-f03e-428a-aa62-e40bc135231f` was **SUCCESS**; it emitted presence booleans only, confirming all three `TCG_DATABASE_URL`, `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID`, and `TCG_TRAWL_API_KEY` references were nonempty. No secret was printed.
- Independent read-only Supabase SQL confirmed the exact physical inventory remains approved, published, identity confirmed, Market Value NULL, Store Price £1, and exact game/set/number/condition/language unchanged.
- Code safety correction: explicitly pass `readonly_snapshot=True` into the existing FastAPI database `user_connection` and assert `SHOW transaction_read_only` is `on`. This works even if a pooler does not reliably honour session default read-only options. Add strictly enumerated non-secret failure codes to distinguish operator preflight vs 429, no raw exception strings or provider response body.
- Only after new CI passes, create a new **reviewed** one-time attempt (do not enable retries or expand scope) and record whether the provider was reached. If a provider rate limit/429 occurs, stop; no repeated paid calls. Existing temporary service remains configured with a credential-presence diagnostic (safe/inert) until the corrected script and pinned service patch can be applied and its actual receipt logged. Delete after receipt.

## Second attempt and isolated settings blocker (22:11–22:14 UTC)

- PR #1067 merged SHA `c183e428071e8fbca9697b3cd46439d8918ed248`; all GitHub jobs passed. The isolated one-shot deployment `cd37f901-5048-4aa0-87db-e4c02268568f` failed closed in ~1s, `error_type=RuntimeError`, `safe_error_code=OTHER_FAIL_CLOSED`, `applied=false`; it supplied **no accepted sold evidence**.
- A provider-free read-only DB diagnostic (deployment `c0bf14b9-ace5-416b-a0f5-a35b2bf052fc`) independently verified `POOL_OK`, `READONLY_CHECK true`, `AUTH_OK`, `TARGET_CHECK matched=true`, all with `provider_called=false` and no writes. So missing credentials, connection, RLS or physical identity are not the blocker.
- Root cause in code: `_fetch_comp_result` calls global `get_settings()`, which requires `TCG_AUTH_ISSUER`, `TCG_AUTH_AUDIENCE` and `TCG_SUPABASE_PUBLISHABLE_KEY`—irrelevant to this isolated one-shot and correctly absent from its three-secret allowlist. Missing required values raise `RuntimeError` before making any provider request.
- Correction: allow an explicit **existing** `provider_key` parameter on `_fetch_comp_result`, defaulting to unchanged full-app settings for all existing FastAPI routes. The isolated pilot passes `TCG_TRAWL_API_KEY` from its own environment, without adding API authentication secrets. Regression tests patch `get_settings` to fail if called, assert one requested provider page and no Store Price writes. The maintenance-actor read-only transaction and 75s/no-restart bounds remain unchanged.
- Next: full CI on this separate PR, reviewed SHA update to the existing isolated service, one single controlled run, actual receipt, and service teardown. If provider returns 429, no repeated calls.

## Final production receipt — 10 November 2026, 22:20–22:21 UTC

**Result:** **BLOCKED BY PROVIDER RATE/CREDIT LIMIT.** No Market Value or Store Price changes.

1. After reviewed PR #1068 (SHA `895ff190cbb1ecd7c9e2acc2cafbbde2000e2509`) passed its GitHub backend, dashboard, PostgreSQL and pinned n8n checks, the final isolated, 75s-bounded, no-restart Railway one-shot deployed as `c576f0df-be77-40b0-867e-0d0a0ee18799` (service `6e207142-b925-4d88-96a5-b4d61e161d3d`). Only one fixed inventory code, one provider page and the same three existing secret references were permitted.
2. Actual sanitized log: `TIER1_SOLD_ONE_SHOT {"status":"FAILED_CLOSED_NO_RETRY","error_type":"HTTPException","safe_error_code":"PROVIDER_429_NO_RETRY","applied":false}`. The provider **returned HTTP 429** (rate or credit limit). **No further provider requests or automatic retries** were made. No eligible current sold comparables or monetary candidate were obtained.
3. Independent production Supabase readback for inventory `INV-3B801C9CE17B48DEA1EE0DD8AB38EA25`: still `APPROVED`, `identity_confirmed=true`, `version=21`, `market_value_minor=NULL`, `store_price_minor=100` (GBP £1), **0** new `market_observations` and **0** new `pricing_snapshots` since 22:19:30 UTC.
4. The temporary Railway service was **deleted** from production; independent `list_services` returned no matching service, the pending Railway patch was empty, and no volumes were detached. No domains or cron had been created.
5. The live FastAPI service `drop-rate-api-live`, Railway deployment `03abe695-4162-4b54-b1de-97c391e9b830`, SHA `895ff190cbb1ecd7c9e2acc2cafbbde2000e2509`, reported **SUCCESS**. At 22:21 UTC startup succeeded and `GET /health/ready` returned **200**. Capacity guard logged `database_plan=pro`, `database_limit_bytes=8000000000`, `database_bytes=428158099`, `refresh_allowed=false`, `reason=BULK_REFRESH_DEFERRED_OPERATOR_HOLD`. Both `CATALOGUE_BULK_REFRESH_DEFERRED` and `CATALOGUE_R2_REFERENCE_MEDIA_DEFERRED` remained blocked by operator hold.

**Next release gates:** check provider quota / reset and permitted sold-evidence supply independently before another explicitly bounded **one-item** attempt. Do not automatically retry 429, enable bulk refresh, promote historical September comps, use eBay Browse active listings as sales, use Cardmarket guide estimates, or modify Shopify Store Prices. This effort validates infrastructure and source integrity; it **does not repair** the existing ten owner-scoped artwork exceptions, whose exact-photo/rights review remains separate.
