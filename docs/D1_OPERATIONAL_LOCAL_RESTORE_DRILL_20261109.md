# Operational shadow: bounded local restore drill

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

This extends restoration verification for the existing operational D1 shadow.
It creates no new archive format, database, Worker, provider or live route.
It cannot connect to PostgreSQL, R2 or D1, and cannot issue refunds, payouts or
production writes. The only destination is disposable local SQLite memory.

## Input and execution

An operator must separately obtain an authorised, completed **standalone SQLite
snapshot** of the existing private operational shadow. This command does not
export or download it, materialise SQL dumps, rerun a protected workflow, or
grant permission for remote export/restore costs. A live database with a WAL or
journal sidecar is rejected. Keep private snapshots outside the repository and
public artifacts.

Obtain both pins from independently retained backup/source evidence: the exact
snapshot file SHA256 and expected current generation manifest SHA256. Merely
calculating pins from an unknown input does not establish source authenticity.

```sh
PYTHONPATH=backend:tools python tools/d1_operational_restore_drill.py \
  --snapshot /private/path/approved-operational-shadow.sqlite \
  --expected-file-sha256 <independently-recorded-file-sha256> \
  --expected-generation-sha256 <independently-recorded-generation-sha256>
```

Input is opened read-only/immutable; its checksum is verified before and after
the drill. SQLite backup reconstructs a separate in-memory database, then closes
it. The command refuses a nonempty restore destination through its Python API.
Limits: 64 MB input, 100,000 restored shadow/metadata rows, 32 generations.
The CLI prints aggregate results or an exception type, never private rows,
owner IDs, amounts, object keys, SQL parameters or the private source filename.

## Acceptance within the existing nine-table scope

- Exact tracked base schema and, if present, all four replay tables; preserve
  original constraints, indexes and immutable-ledger/owner-lineage triggers.
  Unexpected application objects and partial replay DDL fail closed.
- Logical count/full-row hashes for every shadow/metadata table match before
  and after restore. SQLite integrity and all foreign keys must pass.
- Every complete generation's original JSON bytes match their recorded SHA;
  typed D1 columns must reconstruct exactly using the existing source mapper.
  Nine exact table counts/digests match their original receipts.
- Legacy user mappings and catalogue-link scope remain exact. Hosted identity
  mappings are outside this old shadow drill. Sale/refund/ledger ownership and
  original-sale links are checked; owner/currency ledger sums reconcile without
  exposing balances.
- Replay journals are rebuilt using the existing inventory replay planner and
  checked against parent source rows, versions, plan digest, version root and
  capture high-water mark. Cycles, lost daily reservations and wrong heads fail.
- Quarantined interrupted staging remains quarantined and is preserved byte for
  byte. An incomplete journal/checkpoint is not certified as complete. Tests
  restore a stage interrupted before its journal, then use the existing replay
  to finish on the disposable copy without duplicating the daily reservation.

Synthetic tests exercise actual SQLite backup/restore, target corruption,
schema/trigger loss, bad JSON/hash/counts, missing references, wrong generation,
private-output redaction, replay corruption and interrupted recovery.

## Limits and remaining release gates

The nine application tables are owners, owner_memberships, inventory_items,
orders, order_items, financial_ledger_entries, refund_events,
shopify_webhook_events and media_assets. This is not all 150 source relations.
Nonempty reservation, payout-request, Shopify-line-link and audit tables are
explicitly rejected rather than silently included in a nine-table claim.

The original generation manifest includes media_object_mirrors source metadata
that the existing typed D1 shadow does not retain. The tool therefore does not
claim to recompute that whole-source manifest; independent file/generation pins
remain mandatory. It does not verify R2 artwork bytes, licensing, passwords,
hosted recovery, current source drift, remote D1 transactional behavior or a
production restore/rollback.

**No live snapshot drill or remote restoration is established by synthetic
tests. Gates A and H remain incomplete.** Required next receipts: authorised
private source snapshot, independent pins, actual local run against that
snapshot, separately approved disposable D1 restore/transaction acceptance,
broader source scope and production restoration/rollback drills.

Rollback of this code release: revert the tool, tests and documentation. No
schema, source record, deployment flag or live database change is required.
