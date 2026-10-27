# Drop Rate completion work — 27 October 2026

The founder authorized tackling the current gaps one by one. Work starts with
R2 catalogue/source delivery and recurring archive verification. Existing free
pricing jobs continue while these bounded releases are implemented.

## Current implementation step

1. Copy the reviewed book source checkpoint to private R2 with fixed input
   hashes, preserved review status, actual remote byte verification and an
   immutable manifest. Complete: production `BYTES_VERIFIED` receipt at
   14:14:49 UTC, 14 files / 6,228,589 source bytes. See the linked source contract.
2. Inspect stored n8n workflow and Google Drive credential metadata read-only
   before changing schedules. Complete: read-only inspection at 14:02:40 UTC.
   DR92/93/94 lack the reviewed DR90 error links and remain unpublished. No
   supported Google Drive credential exists in the inspected n8n database.
3. Add an owner-free, exact-set reference-input cache with current Supabase
   identity, pricing eligibility, ownership and media checks. Implemented;
   native PostgreSQL 17 CI and production build/readback gates pending.
4. Finish proven scheduled approved-media runs and weekly R2-to-private-Drive
   transfer with independent byte verification. Not complete.

The existing R2 price-history archive is already recurring and restore-verified.
It must not be duplicated. Source snapshots are additional durable copies;
current catalogue records, prices and ownership remain authoritative in Postgres.
Broad image caching still requires the recorded source permissions.

## Remaining ordered work

| Work | Current gap | Acceptance |
| --- | --- | --- |
| Card values | Last exact checkpoint: 43,135/67,065 physical references, 64.32%, including labelled guides | Supported current values or clearly labelled guides; 17,224 more needed for 90%; no invented prices |
| Artwork | 6,782 physical reference URLs missing; existing URLs are not all load-verified | Correct image visibly loads across search, sets and collection; exact printing and source checks retained |
| Comics/manga | 785 comics + 805 manga; zero positive shared market snapshots at checkpoint | Reviewed editions/covers/printing evidence and supported market values; 909 staged records stay held until reviewed |
| Phone scanner | Old deletion/two-item queue bugs repaired; representative device acceptance outstanding | Exact result, useful artwork/value, reliable saving and measured phone latency |
| Import recovery | Existing preview cannot be rebuilt after wrong column/default settings | Correct settings and rebuild without bypassing file identity or duplicating physical copies |
| Seller fulfilment | Carrier label, dispatch confirmation and tracking sync disabled | Verified actual label/reprint, parcel allocation, cost, dispatch and tracking journey |
| Seller payouts | Prepared balances/approvals; complete live bank-payout journey unverified | Funding, recipient readiness, transfer/bank payout, reversals/refunds and settlement reconciliation |
| Storefront | Current published-site acceptance needs a new dated pass | Mobile/desktop search, filters, stock, checkout delivery and refund/replay evidence |
| Operations | Workflow execution/Drive-copy receipts missing; legacy status entries overlap | Durable scheduled success/failure evidence and one current progress record |

Exact catalogue counts are dated 12:03–12:04 UTC on 27 October. Later table
statistics and price refresh writes must not be relabelled as newer coverage.

## Deliberately deferred

Live auction scanning remains design/research only. Native app distribution,
additional marketplace connections, automatic buyer-portfolio onboarding,
hardware bridge and recurring marketing are later workstreams. This sequence
does not authorize fabricated source rights or unreviewed money movement.

## Release evidence

Record exact PR/head, test results, deployment and actual storage/runtime
readbacks here or in linked receipts. A passing build alone is not completion.
See [current catalogue checkpoint](CATALOGUE_RECOVERY_20261027.md) and
[source archive contract](R2_CATALOGUE_SOURCE_ARCHIVE_20261027.md).
