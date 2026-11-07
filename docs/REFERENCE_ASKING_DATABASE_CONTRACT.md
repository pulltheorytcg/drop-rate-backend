# Asking-estimate database contract

The asking cache is separate from sold observations, inventory valuation,
store prices and settlements. A row records an explicitly labelled GBP raw
near-mint asking estimate including postage, with at least three listings
from at least three sellers. The application must still prove the exact
printing, language, finish and condition before writing it. Database shape
checks cannot prove a listing matched a card.

The deployment tool applied migration
`database/migrations/20261028224708_reference_asking_prices.sql` on 28 October
2026. Readback confirmed forced RLS on all three tables, denied direct client
access and retained backend access. Do not edit historical migrations or apply
this migration automatically on application startup.

## Write order

1. Create `tcg.reference_asking_runs` with the platform-admin actor. Defaults
   record UTC `budget_day`, `started_at`, zero `requests`, and `RUNNING` status.
2. Call `select tcg.reserve_reference_asking_request($1)` and **commit** before
   every external request, including attempts that subsequently fail. Network
   calls must run outside that transaction. An ambiguous crash after reserving
   a slot conservatively consumes it; reservations are never refunded.
3. After validating provider evidence, open a new database transaction. Insert
   `tcg.reference_asking_history` with a new `snapshot_id`, the `run_id`, actor,
   complete reference identity, estimate fields and bounded evidence.
4. Upsert `tcg.reference_asking_prices` from that history row in the same
   transaction. Every field must match. The database records a compact audit
   event containing the old and new snapshot IDs/prices; the immutable history
   carries full evidence. A rollback removes all three effects together.
5. Finalize the run with `COMPLETE`, `INCOMPLETE`, `FAILED` or `STOPPED` and a
   `finished_at`. Finalized runs cannot be reopened or rewritten.

The runner should also hold its existing global worker advisory lock, consult
provider Analytics quota, and enforce the 400 MB database capacity guard before
each evidence write. The database adds an independent aggregate hard limit of
500 UTC-day request slots across all asking runs and actors. The reservation
function acquires its transaction advisory lock before updating a run. The run
trigger also protects direct updates. A restarted process/new run shares the
same daily total. A run from a previous UTC day cannot reserve another request.

Only `tcg_api` with a platform-admin actor can create or update evidence and
runs. Authenticated backend readers can read the display cache/history. The
`anon`, `authenticated` and `service_role` database roles receive no table
privileges. RLS is enabled and forced on all three tables. All foreign keys use
the default NO ACTION behavior, so deleting a reference/run cannot cascade away
evidence. History has no application UPDATE/DELETE grants and rejects both
operations through an immutable-history trigger.

`reference_identity` contains exactly `name`, `set_id`, `card_number`,
`set_name`, `finish`, and `rarity`, and must equal the current card/set row.
Evidence must include source `EBAY_OFFICIAL_BROWSE`, shipping basis
`ITEM_PLUS_SHIPPING`, condition `Near Mint`, an approved finish, nonempty
confidence, and `physical_valuation_eligible: false`. Its encoded JSON is
limited to 32 KiB; operational run reports are limited to 16 KiB. Never include
API credentials, access tokens, cookies, raw headers or response bodies.

Shipping evidence must also state
`shipping_context: CONFIGURED_SHOP_POSTCODE_BENCHMARK`. Provider-calculated
shipping uses the existing `TCG_EBAY_ORIGIN_POSTCODE` setting as a shop-location
benchmark. It is not a customer's exact delivery quote. The context label is
required even when the selected shipping amount is zero; do not claim an
unqualified delivered price or copy the configured postcode into reports.

`observed_at` cannot be in the future. `checked_at` cannot precede it. Expiry
must follow `checked_at` and be at most three days after `observed_at`. A cache
update cannot move observation/check time backwards. Expired or changed-identity
rows must be filtered by the reader; retaining them does not make them current.

## Database verification

Use a disposable local PostgreSQL database named `asking_test` and a database
owner connection. The test refuses other database names, remote hosts, and an
existing `tcg` schema:

```sh
ASKING_TEST_DSN=postgresql://postgres:postgres@127.0.0.1:5432/asking_test \
  python tests/reference_asking_postgres.py
```

The integration test applies the proposal (or its assigned migration), checks
forced RLS and client ACLs, and exercises actual SQL for successful writes,
rollback, compact audit events, same-actor/snapshot integrity, cache-only write
rejection, stale/invalid basis rejection, immutable history, non-admin denial,
durable request counters, concurrent reservations and the 500/day aggregate
ceiling across restarted runs. It uses synthetic evidence and no provider API.

`.github/workflows/asking-price-contract.yml` runs this test against a disposable
PostgreSQL 16 service on relevant pull requests. It uses a public test password
and no production credentials. The existing backend, browser and n8n workflows
remain independent and must also pass before release.

Production schema validation is read-only after the separately managed
migration. Check table RLS/ACLs and the migration receipt; do not run these
disposable fixtures against production. This proposal itself performs no live
database writes or provider requests.
