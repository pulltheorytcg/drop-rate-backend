# Financial D1 cutover safety gate — 9 November 2026

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

**State: read-only acceptance gate; NOT a financial writer, Auth migration, source deletion or traffic cutover.**

## What / why / connections

This extends the already verified nine-table private operational D1 staging and source drift watch with an **independent financial semantic + typed-column test** before any founder/consignor ownership or payout authority can be moved. It reuses the existing source `source_capture` in a PostgreSQL REPEATABLE READ read-only transaction, exact original SHA/canonical link parity, and the existing private D1 account/name allowlist. The new protected GitHub Actions workflow calls `tools/d1_operational_financial_integrity.py`, never FastAPI publication, n8n direct queries, a D1 write API or Shopify payout APIs.

The original drift check proved that private D1's stored **JSON hashes** match PostgreSQL. That was not a complete proof that `ops_shadow_ledger.amount_minor`, `ops_shadow_order_items.owner_id` and `commission_minor` typed columns had not been corrupted separately. This new gate compares **all typed columns plus source JSON/hash** across the eight finance-relevant tables: owners, owner memberships, inventory items, orders, order items, refunds, ledger and Shopify webhook inbox. A change in any type, owner, minor-unit value, item or source key blocks; no private row IDs or balances are emitted.

## Production source observations — READ ONLY

At 9 Nov 2026 around 01:15 UTC, source inspection found **3 sale items, 3 refunds, 13 ledger entries, 14 Shopify webhook rows, 3 founders and 3 consignors, 0 payout requests**. The three existing sales were **founder-owned** and carried zero marketplace commission. All 3 refunds were for sold items returned to inspection; shipping refunds are represented by separate `SHIPPING_REFUND` ledger entries. Current production data therefore **cannot prove** commission handling for real consignor orders, zero-defect payout scheduling, cross-owner mixed order allocations, or concurrent refund scenarios. The offline synthetic tests cover these but are not production evidence.

An additional risk remains in the existing PostgreSQL refund route: a manually submitted `REFUND` can be allowed up to item sale + shipping total, while the commission-reversal trigger enforces an item-sale-only refund cap. The new gate **fails closed** when item `REFUND` totals exceed the item's net sale. This is an explicit cutover blocker requiring a reviewed split/refund policy, not permission to rewrite historical refunds or relax Postgres triggers.

## Deterministic acceptance

- Exact owner membership and inventory-to-sale-to-ledger/refund lineage.
- Each physical copy appears at most once in an order; every sale item has exactly one matching `SALE_REVENUE` ledger amount and correct immutable commission snapshot.
- Founder commission always zero; consignor basis points range 0–10,000; integer-GBP-minor-unit commission uses PostgreSQL `round(numeric)` semantics for positive halves (no floating arithmetic).
- Refund events have unique item/reference combinations, match signed `REFUND` ledger entries, and never exceed the card's net sale; shipping refunds are separate, never exceeding recorded shipping revenue.
- Commission reversal is proportional to cumulative item refunds and matches the original snapshotted rate; no double commission/reversal or negative reversal.
- Ledger source keys and Shopify webhook identities are unique; debit/credit signs and existing owner order lineage checked. Duplicate or mismatched source keys never considered idempotent.
- Typed D1 comparisons are performed over all finance-relevant fields, independent from original JSON hash parity, followed by a second source-hash parity check.

## Failure modes / rollback

Any mismatched value, untrusted source, stale D1 generation, duplicate ledger/webhook, unlinked physical item/owner, corrupt commission or shipping refund, or unavailable private credential fails the protected check and reports only a generic error. No secret, owner ID, refund reference or amount is logged. An error requires investigation; do not treat a green generic workflow as a public release receipt. To rollback this additive gate, disable its workflow; there is no data or route to revert. The source remains Supabase and the previous private D1 generations remain intact.

## Deliberately incomplete — do not cut over yet

The source currently has many more than nine operational relations. This gate does **not** cover payout requests, pending reservations, all Shopify/eBay/Stripe event lifecycles, fee reconciliation, monetary release status transitions, provider-side replays, complete immutable audit, an external OIDC provider, D1 transactional writer with reservation compare-and-swap, or performance/recovery of real concurrent financial writes. D1 cannot inherit PostgreSQL RLS. Add deterministic server-side owner authorisation and a single transactional D1 writer, compare against protected live fixtures, and require explicit restore/rollback before switching financial authority. The output always declares `full_financial_relation_coverage=false` and `supabase_retirement_authorized=false`.

## Test/readback plan

Offline Python 3.12 tests simulate a mixed founder+consignor order with shipping, partial refund and proportional commission reversal; validate missing/duplicate source keys, cross-owner refs, rounding, wrong refund amount/sign, tampered typed D1 values, and wrong Cloudflare account. CI runs these plus existing private D1 schema tests. A protected production job then verifies real same-snapshot original SHA+typed parity and uploads a counts-only audit receipt.

No new paid Cloudflare resources, Railway services, credential rotation, source mutation, payment movement, storefront UI or public URLs are part of this change.


## 9 November 2026 — confirmed D1 Free read-quota incident and scheduled recovery

Protected production [finance run #42548078246](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42548078246) confirmed `category=DAILY_ROW_READ_LIMIT` while reading the **first `ops_shadow_owners` table**, before financial value parity could be established. The read-only check **failed closed**. This is an exhausted account-wide Cloudflare D1 read allowance, not evidence of bad owner balances. Previous HTTP-400 failures remain unproven finance parity. No source or D1 financial writes, payment, Auth, service cutover or plan purchase occurred.

Merged PR #1023 (`7435248aae96c72ca34edf6a7952a1eee3fb30f0`) replaces deep-offset source catalogue scans with indexed card_key cursor queries and safely classifies Cloudflare D1 errors without disclosing provider details. Cloudflare confirms Free daily row limits reset at **midnight UTC**: https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/ .

The existing protected read-only finance workflow is now scheduled **once daily at 00:17 UTC**, after the reset and before the separate 03:17 UTC Yu-Gi-Oh import. This avoids simultaneous budget competition and does not retry a capped account throughout the day. GitHub Actions cron can be delayed or skipped; an expected run is not proof of a completed run (https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). The push trigger still covers changes to the verification script itself, but a workflow-only schedule commit does not immediately re-run the exhausted account. Offline PR tests and production environment protections are unchanged.

**Acceptance remains strict**: the scheduled workflow must emit `READ_ONLY_D1_FINANCE_TYPED_AND_SOURCE_PENNY_PARITY` and count-only original hash/typed-row/commission/refund receipt, or fail closed and preserve NO-GO. A passing result covers only eight financial source tables and the original nine-table private shadow, **not** full finance relations, payouts, OIDC replacement, no-split Shopify event replay or source retirement. Disable the schedule after full migration is formally approved or if routine reads threaten account budget.
