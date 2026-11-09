# Drop Rate — inactive private operational D1 owner-inventory read bridge

Date: 9 November 2026 · Migration tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## 1. What this builds and why

A **read-only, undeployed Cloudflare Worker** that gives the future authenticated FastAPI backend one narrow way to fetch a founder/consignor's inventory from the existing verified private `ops_shadow_*` D1 database. The current PostgreSQL/Supabase path still authenticates/authorises production users. D1 has no PostgreSQL RLS; allowing a browser to query D1 by a user-provided `owner_id` would leak another owner's inventory, acquisition costs and finances. This prototype instead accepts a **legacy_user_id previously verified by the server** on an HMAC-authenticated internal request, then derives the *only allowed owner* from active private D1 memberships. It never accepts an owner ID, role or admin claim in the request.

Components:
- `cloudflare/operational-readonly/worker.mjs` — one fixed `POST /internal/v1/owner-inventory` handler, exactly two fixed parameter-bound SELECT queries.
- `tests/cloudflare_operational_readonly.test.mjs` — disposable Node.js test fake proving authorization, query scope, pagination, privacy and failure behaviour.
- `.github/workflows/d1-operational-readonly-worker.yml` — offline JS tests/compile only, **not** deployment, credential access or D1 calls.

## 2. Connections and security boundaries

Future, but *not active now*:

1. Current FastAPI `require_user` resolves and verifies the caller's session and legacy `user_id`. When the external OIDC replacement is ready, #1027's verified subject→legacy UUID mapping must supply that value; no email auto-linking or JWT role/founder claim trust.
2. The trusted FastAPI server sends **only** `{legacy_user_id, cursor, limit}`, with `cursor` either null or a canonical UUID and 1–50 results, over private HTTPS. It signs `POST\n/internal/v1/owner-inventory\n<UTC epoch seconds>\n<raw JSON body>` as HMAC-SHA256 using a random **32-byte** `DR_INTERNAL_HMAC_SECRET` provided as **64 lowercase hex characters** in Worker secrets and the backend's private sealed environment (NEVER in Shopify, frontend JavaScript, n8n data or this repository). Headers are `X-DR-Timestamp` (integer seconds) and `X-DR-Signature: sha256=<lowercase hex>`. Timestamp must be within 120 seconds; TLS, request rate limits and a private Worker route/firewall are additional deployment gates.
3. Worker selects only `env.OPS_DB`, a private, explicitly bound operational D1 database, and `env.DR_OPS_GENERATION_ID`, a pinned 32-hex-character source generation. No caller-supplied generation, direct SQL, D1 database selector, read/write token or runtime D1 credentials are accepted.
4. Membership SQL joins `ops_shadow_identity_map`, `ops_shadow_memberships` (active), `ops_shadow_owners` (active), `ops_shadow_generations` (`PARITY_VERIFIED`) and requires exactly **nine** source table receipts. It returns exactly **one** active owner ID or fails closed on zero/ambiguous membership. The second SELECT is strictly filtered by this server-derived owner, pinned generation and UUID cursor, ordered by ID with `LIMIT` ≤50; rows with unexpected owner, invalid UUID, version or currency are rejected. There is NO Founder HQ/business capability, even for a platform-admin-labelled membership.
5. Worker returns `Cache-Control: no-store, private` and **no permissive CORS header**, and never prints raw SQL errors, user IDs, secrets, financial amounts or source rows to logs.

## 3. Failure cases and testing

Offline Node tests cover valid signed founder and consignor owner-scoped reads; malicious `owner_id`/role injection; a valid signed actor unable to read another owner's stock; missing, inactive (SQL only), ambiguous or malformed memberships; invalid/old/future HMAC timestamps, missing/wrong signature, tampered JSON, unavailable config; malformed path/method/content type/body; invalid output order, cross-owner rows, source D1 errors; bounded pagination; fixed SELECT-only SQL and lack of browser CORS. The user input cannot become an SQL identifier. No external APIs or secrets are required for tests.

**Important limitation:** tests simulate D1 `prepare().bind().all()` with correct SQL restrictions, but do not verify a real Cloudflare runtime, network policy, TLS, deployed HMAC secret distribution, anti-replay beyond a 120-second *read-only* window, live data freshness, full Auth cutover or worker read latency. All of these remain production-release gates. A signed request is evidence of a trusted backend call, **not** evidence of an authenticated end user unless FastAPI has performed the full `require_user`/role checks first.

## 4. Cutover and rollback

Do **not** deploy, add public routes, bind the existing production D1 database, create credentials, move Shopify traffic, disable `TCG_DATABASE_URL` or change any current login/financial system on this commit. The nine-table D1 snapshot is not a complete operational migration and Cloudflare Free tier hit its daily D1 read quota on 9 Nov; an upgraded plan is pending the user's Cloudflare dashboard action and cost acceptance. This is a safe **offline interface proof**, not permission to make owner-facing reads live.

Before enabling this read bridge, the exact source generation, nine receipts, owner permissions and rows must pass repeatable-read source SHA + typed-column parity in the live Cloudflare D1 account; deploy privately to staging with separate credentials; test rate limits, key rotation, revoked membership, cross-founder attempts and rollback. Keep Supabase PostgreSQL authoritative for all writes until a separately signed D1 financial writer passes the full sales/refunds/shipping/payments audit, and all remaining Railway/n8n consumers are removed. Rollback of this patch is simply reverting its unused worker/test/docs; no live data changes.

**Current migration status: NO-GO for Supabase retirement.**
