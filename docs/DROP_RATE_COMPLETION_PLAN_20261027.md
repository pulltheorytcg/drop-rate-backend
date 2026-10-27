# Drop Rate completion work — 27 October 2026

The founder authorized tackling the current gaps one by one. Work starts with
R2 catalogue/source delivery and recurring archive verification. Existing free
pricing jobs continue while these bounded releases are implemented.

## Current implementation step

1. Copy the reviewed book source checkpoint to private R2 with fixed input
   hashes, preserved review status, actual remote byte verification and an
   immutable manifest. Complete: production `BYTES_VERIFIED` receipt at
   14:14:49 UTC, 14 files / 6,228,589 source bytes. See the linked source contract.
2. Inspect and repair stored n8n definitions. Complete for DR90/91/92/93/94:
   exact four-ID upgrade at 15:09:36 UTC with a verified SQLite backup. The
   native runtime exposed and verified a raw HTTP response parser correction;
   DR92/93/94 now have their reviewed DR90 error links. DR90 was published at
   15:13:36 and both health schedules at 15:17:38. The separate DR91 source
   repair completed at 16:57:03 with a verified backup, retaining its inactive,
   unpublished state. All five stored definitions now match reviewed source.
   Fresh inspection still shows no supported Google Drive OAuth credential.
3. Add an owner-free, exact-set reference-input cache with current Supabase
   identity, pricing eligibility, ownership and media checks. Live after native
   PostgreSQL 17 CI and actual R2/query parity: first 20 sets / 1,966 references
   verified; eligible delivery enabled on successful deployment at 14:38:45 UTC.
   Warming continues gradually; this is not whole-catalogue cache coverage.
4. Verify actual scheduled controls before approved media. DR93's signed
   storage-health command returned HTTP 200 at 16:00:23 UTC. DR92's heartbeat
   returned 500 at 16:00:34 and its DR90 failure receipt returned 503. Those
   backend/database failures are being repaired. The exact DR92 pause was
   verified at 16:55:16 with a backup; DR90 and DR93 remain published, while
   DR91 and DR94 remain unpublished. All one-time operator flags are cleared.
   Publication alone is not proof of successful scheduled execution.
5. Weekly private Drive copy: release #759 is merged and deployed behind
   disabled backend/workflow gates. Its real pinned n8n smoke passed at
   15:01:41 UTC: three automatic runs, one restart, three synthetic archives,
   seven objects, independent byte readback, saved continuation, receipt replay
   and cleanup. Real Google OAuth, durable production receipt acceptance,
   DR91 publication and a bounded real copy remain activation requirements.
   No live Drive copy has been claimed.
6. Founder import recovery: release #760 is merged and deployed; all four CI
   workflows passed, including PostgreSQL 17, authenticated owner intake and
   responsive layouts. The rebuild gate remains false. Supabase's governed
   migration call returned `Invalid or expired requestState`; a later ledger
   read still had 135 entries and no founder preview rebuild migration. Its
   installation/activation therefore needs the connector request state fixed.

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
| Import recovery | Tested same-batch rebuild and founder controls deployed; database migration/activation blocked by connector request state | Apply the reviewed guarded migration, verify live readiness, then enable rebuild; preserve source identity and avoid duplicate copies |
| Seller fulfilment | Carrier label, dispatch confirmation and tracking sync disabled | Verified actual label/reprint, parcel allocation, cost, dispatch and tracking journey |
| Seller payouts | Prepared balances/approvals; complete live bank-payout journey unverified | Funding, recipient readiness, transfer/bank payout, reversals/refunds and settlement reconciliation |
| Storefront | Current published-site acceptance needs a new dated pass | Mobile/desktop search, filters, stock, checkout delivery and refund/replay evidence |
| Operations | R2 health succeeds; failed heartbeat paused; all five stored control definitions repaired; receipt/database repair prepared; media and Drive held | Install and verify durable heartbeat/receipt writes, resume heartbeat, then prove scheduled media and the separately authorized Drive copy |

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

Merged releases: [source archive #755](https://github.com/pulltheorytcg/drop-rate-backend/pull/755),
[runtime test compatibility #756](https://github.com/pulltheorytcg/drop-rate-backend/pull/756),
[R2 reference inputs #757](https://github.com/pulltheorytcg/drop-rate-backend/pull/757),
[guarded control plane #758](https://github.com/pulltheorytcg/drop-rate-backend/pull/758),
[disabled private Drive transfer #759](https://github.com/pulltheorytcg/drop-rate-backend/pull/759),
and [founder preview rebuild #760](https://github.com/pulltheorytcg/drop-rate-backend/pull/760).
The latter two feature gates are still false. API deployment
`ebea8e5c-07d8-452e-bd8c-8d7e47106b21` succeeded at 15:12:29 UTC on
`683979fb207016f4d1f562d082e5b0c32d2354d2`.

[Guarded heartbeat pause and receipt recovery #761](https://github.com/pulltheorytcg/drop-rate-backend/pull/761)
merged as `47b56af19ac8bb11677063c30c41a602538febfd`. Its pinned-runtime and
Drive smoke gates passed. Production n8n verified the DR92-only pause at
16:55:16 and the inactive DR91 source repair at 16:57:03. See the dedicated
[pause](N8N_HEARTBEAT_PAUSE_20261027.md) and
[receipt recovery](N8N_SUCCESS_RECEIPT_UPGRADE_20261027.md) receipts.
The first #761 API build failed in Railway's BuildKit service before tests;
the previous successful API remained live. No application regression is claimed
from that build-service failure.
