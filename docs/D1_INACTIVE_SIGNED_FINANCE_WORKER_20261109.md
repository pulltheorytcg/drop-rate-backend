# Inactive signed Cloudflare D1 candidate finance executor — 9 November 2026

Related: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What is being built and why

The repository already contains three **inactive, offline-tested** D1 financial candidate schemas `database/cloudflare_d1/candidate/0001_atomic_sale.sql`, `0002_atomic_card_refunds.sql`, and `0003_shipping_payment.sql`. Their source-verified sale/refund/shipping/fee planners are in FastAPI Python modules. A D1 Worker that executes a whole event with `db.batch()` on a separate candidate D1 database was missing.

`cloudflare/operational-candidate-finance/worker.mjs` adds a **staging-only**, fixed-event dispatch contract. Its one fixed POST path is `/internal/v1/candidate-financial-event`. It accepts only HMAC-authenticated, source-validated event details for `SALE`, `CARD_REFUND`, `SHIPPING_ALLOCATION`, `SHIPPING_REFUND` and `PAYMENT_FEE`. Every event compiles to a trusted, hardcoded `INSERT` template and bound parameters; client-provided SQL, owner role claims, table names, database IDs, arbitrary events, multi-statement strings and payouts are rejected. All sale statements (order, inbox, each physical sale line and outbox) are executed in exactly **one** D1 `batch()` call. Candidate database triggers validate active owner, immutable inventory ID, version compare-and-swap, correct commission and cost basis and write ledger/outbox in the same SQLite transaction. A duplicate webhook/refund cannot silently post a second financial adjustment; a failed batch is never acknowledged as success.

Cloudflare D1 explicitly documents that a Worker `D1Database.batch()` is transactional: failure aborts or rolls back the sequence. This transaction guarantee, real D1 trigger behaviour and latency must still be **proven in a disposable real Cloudflare D1 staging instance**.

## Connections and production separation

Future connection (not enabled here): authenticated/verified Shopify or eBay source → FastAPI deterministic business rules and exact source owner/inventory verification → signed internal event envelope → Cloudflare Worker bound **only** to separately created candidate D1 database → one atomic SQL batch → immutable pending ledger/outbox. The Worker does not authenticate customers by itself, infer ownership or fees, generate payouts, call Stripe, accept raw Shopify webhooks, mutate Supabase or switch live orders.

There is deliberately **NO** `wrangler.jsonc`, `wrangler.toml`, Worker deployment action, Cloudflare secret, production FastAPI route, D1 binding, credential or activation in this PR. A future deploy must use a **different database** from `ops_shadow_*`; candidate tables and the current immutable shadow cannot be conflated. The only positive Worker response is labelled `CANDIDATE_ATOMIC_EVENT_COMMITTED`, `authority=STAGING_ONLY` and `automatic_payout=false`.

The dedicated staging enable flag `DR_CANDIDATE_STAGE_ENABLED` must be exactly `true`; `DR_CANDIDATE_DB` must be a bound D1 database; the HMAC key `DR_FINANCE_HMAC_SECRET` must be a random 32-byte secret encoded as 64 lowercase hex characters. The secret is NOT provisioned or printed. The Worker uses HMAC-SHA256 of the exact `POST\n<fixed path>\n<epoch seconds>\n<raw JSON body>` envelope, rejects timestamps older/newer than 90s and payloads over 64KiB. HTTPS, a private Cloudflare Access/service-token route, rate limiting, secret rotation, real replay protections, FastAPI role/auth checks, source verification and human-reviewed staged cutover remain mandatory. A 90s HMAC window alone is NOT replay protection for mutation; database unique event keys and careful source event replays are required.

## Failure and recovery

- Invalid signature, shifted timestamp, oversized body, wrong method/path/content-type, untrusted SQL, owner/role injection, wrong cardinality/UUIDs/penny fields and malformed source hashes fail closed.
- The DB itself must reject stale inventory version, already sold physical copies, inactive/wrong owner, mismatched commission/cost, forged webhook ID, duplicate refund, incomplete shipping allocation, over-refund or inconsistent ledger.
- If any prepared D1 statement fails, `D1Database.batch()` must roll back all prior statements. Never split a sale into separate REST calls or retry a financial event without comparing its original immutable source/event SHA.
- An unavailable staging binding or disable flag produces 503 without sending SQL; a DB rejection produces a generic 409 with no sensitive source data in logs/responses.
- Outbox events stay `PENDING`: no settlement, transfer or payout execution.

## Testing and next release gates

`node --test tests/cloudflare_candidate_finance_worker.test.mjs` runs synthetic test payloads and a fail-closed fake D1 against the Worker `fetch` entry point. It validates HMAC, route/size, duplicate physical lines, source type/owner/amount/UUID boundaries, fixed parameterized SQL, one batch for mixed-owner sale, refund/fee/shipping operation families, error redaction and refusing incomplete/failed batch responses. `.github/workflows/d1-candidate-finance-worker.yml` runs Node 22 tests and syntax check offline, without Cloudflare credentials or deployment. The existing backend, n8n and dashboard suites are also merge gates.

Before any activation: (1) provenance-verified copying of original source owner/order/13 ledger rows plus full 150-relation classification; (2) **disposable real D1** schema+atomic commit and rollback under competing item transactions; (3) separate HMAC/service firewall and internal FastAPI route with no browser token; (4) identity and founder/consignor isolation; (5) Shopify/eBay idempotency including refunds, shipping, fees, cancellations, owner commission, restocks and chargebacks; (6) monitoring and approved freeze/replay/single-authority production switch; (7) rollback and complete zero-Supabase consumer proof. The source remains Supabase until all applicable gates pass.

**Release state: INACTIVE / STAGING-ONLY CODE. Supabase retirement NO-GO.**
