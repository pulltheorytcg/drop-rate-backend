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
   repair completed at 16:57:03 with a verified backup. Its separate publication
   was verified at 17:55:12 after database repair; the one-time flag is cleared.
   DR94 approved-media publication was verified at 18:02:25. Independent metadata
   confirms all five DR90–94 definitions are active/published and match reviewed
   source, with no supported Google Drive OAuth credential. All six one-time
   boot mutation flags are cleared. The normal DR94 media command returned
   HTTP 200 at 19:00:04.503 UTC; image counts and durable receipt fanout remain
   separate verification requirements.
3. Add an owner-free, exact-set reference-input cache with current Supabase
   identity, pricing eligibility, ownership and media checks. Live after native
   PostgreSQL 17 CI and actual R2/query parity: first 20 sets / 1,966 references
   verified; eligible delivery enabled on successful deployment at 14:38:45 UTC.
   The current deployment's 17:05–17:26 warming logs give a fresh, deduplicated
   checkpoint of 100 sets / 14,297 references / 855,888 compressed bytes. Do not
   add the first checkpoint again. This is partial reference-input cache
   coverage, not whole-catalogue delivery or reclaimed database space.
4. Verify actual scheduled controls before approved media. DR93's signed
   storage-health command returned HTTP 200 at 16:00:23 UTC. DR92's heartbeat
   returned 500 at 16:00:34 and its DR90 failure receipt returned 503. The exact
   DR92 pause was verified at 16:55:16 with a backup. The reviewed automation
   database repair is now installed as `20261027173335`; subsequent readback
   verifies the exact control functions and unchanged table privileges/RLS.
   DR92 has resumed: its durable heartbeat advanced from execution 41/count 1
   at 17:45:34 to execution 43/count 3 at 17:55:34. R2 health returned HTTP 200
   at 18:00:23 and heartbeat returned 200 at 18:00:34. Receipt fanout still
   needs an observed real execution. DR94 approved-media publication was
   verified at 18:02:25 after those health checks. Its normal scheduled command
   returned HTTP 200 at 19:00:04.503 UTC, followed by storage-health 200 at
   19:00:24.483 and heartbeat 200 at 19:00:34.195. The media response verifies
   command completion only. The mirror registry still contains 401 verified
   entries, latest verification 26 October at 23:18 UTC; no new mirrors are
   claimed. The exact production eligibility query at 19:30:30 UTC found zero
   approved assets awaiting mirrors. DR93/94 success paths validate responses
   but do not call DR91, so durable receipt fanout remains unverified. See the
   [runtime readback](evidence/runtime-continuation-readback-20261027.json).
5. Weekly private Drive copy: release #759 is merged and deployed behind
   disabled backend/workflow gates. Its real pinned n8n smoke passed at
   15:01:41 UTC: three automatic runs, one restart, three synthetic archives,
   seven objects, independent byte readback, saved continuation, receipt replay
   and cleanup. DR91 is now published, but real Google OAuth, durable production
   receipt acceptance and a bounded actual create/download/readback remain
   activation requirements. Both Drive enable flags remain false. No live Drive
   copy has been claimed.
6. Founder import recovery: release #760 is merged and deployed; all four CI
   workflows passed, including PostgreSQL 17, authenticated owner intake and
   responsive layouts. The earlier connector failure is resolved. A fresh
   19:22:07 UTC read again confirmed absence before the exact reviewed migration
   was installed as `20261027192257_founder_import_preview_rebuild`. Readback
   at 19:23:15 verifies unchanged roles, table/column privileges, RLS, schema
   permissions, policies and audit trigger; the separate 19:23:30 function read
   verifies the exact reviewed body and restricted execution. Advisor findings
   are unchanged. The rebuild flag is true. Targeted API deployment
   `20131280-07c8-474e-8932-2a0df29baf71` reached SUCCESS at 19:26:37.659 UTC,
   after 7,256 tests passed, 18 skipped and one warning; the new runtime logged
   readiness HTTP 200 at 19:26:32.903 UTC.
   No existing import is replayed. Live founder UI acceptance still needs an
   authenticated originating session and the original source file. See the
   [activation evidence](evidence/import-preview-rebuild-activation-20261027.json).

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
| Import recovery | Exact reviewed migration installed and verified; flag true; targeted deployment SUCCESS and runtime readiness 200; authenticated founder UI acceptance pending | Verify the founder journey with the exact original file; preserve source identity and avoid duplicate copies |
| Seller fulfilment | Carrier label, dispatch confirmation and tracking sync disabled | Verified actual label/reprint, parcel allocation, cost, dispatch and tracking journey |
| Seller payouts | Prepared balances/approvals; complete live bank-payout journey unverified | Funding, recipient readiness, transfer/bank payout, reversals/refunds and settlement reconciliation |
| Storefront | Current published-site acceptance needs a new dated pass | Mobile/desktop search, filters, stock, checkout delivery and refund/replay evidence |
| Operations | Control migration installed and heartbeat live verified; all five DR90–94 definitions active/published and exact; normal DR94 command HTTP 200 observed at 19:00; 401 verified mirrors; real receipt fanout and Drive unverified | Verify durable receipt acceptance, then authorize Google in n8n and prove the bounded private Drive copy |

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
Both feature gates were false at the initial release checkpoint. API deployment
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

[Automation runtime repair #762](https://github.com/pulltheorytcg/drop-rate-backend/pull/762)
merged as `fb19e7e8477779577736d90e745ddc171374627a`, exact tree
`aa8015eef401d9a34c731fa37c8c96d6f411773c`. API deployment
`a91487a5-7e2b-42d8-809b-0439fdb01562` reached SUCCESS at 17:05:20 UTC after
7,256 tests passed, 18 skipped and one warning; readiness returned 200. This
resolved the earlier BuildKit deployment failure. The API remains on that
release; the resumed production work installed the reviewed database repair
and recovered the stored automation state.

The automation migration is recorded as
`20261027173335_automation_control_runtime_repair`. Readback verifies reviewed
function body hashes, signatures, owners, settings and restricted grants;
table ACLs, RLS and required indexes are unchanged. Native PostgreSQL 17.6
checks additionally passed with captured production audit metadata overlaid
in disposable databases. Their data was synthetic; they are not evidence of
production receipt fanout or customer-data writes.

Successful n8n deployment `d20f969c-e663-4f84-b1ba-8546f908dfa2` emitted
`PUBLICATION_VERIFIED` for DR91 at 17:55:12 UTC with a verified SQLite backup.
The durable heartbeat read at 17:59:15 records execution 43/count 3, received
at 17:55:34.490942. The 18:00:23 storage-health and 18:00:34 heartbeat requests
both returned HTTP 200. DR94 then emitted `PUBLICATION_VERIFIED` at 18:02:25
with a verified SQLite backup on deployment
`73b85d89-b5a5-4931-bd16-eef34757c1cc` (SUCCESS at 18:02:42.855). Independent
metadata confirms all five DR90–94 definitions active/published and matching
source, while native Drive credentials remain absent. All six one-time boot
mutation flags were cleared with `skipDeploys:true`. No 19:00:03 scheduled
media outcome is claimed in advance.

At 17:57:21 UTC the import rebuild function and migration remained absent,
despite the now-working automation capability. That checkpoint's ledger
contained 136 migrations, including the automation repair and no import rebuild;
existing advisor warnings were unchanged. The import flag and both Drive flags
were false. See the historical
[dated recovery evidence](evidence/automation-import-recovery-20261027.json).

The resumed 19:22–19:23 UTC work resolved the migration blocker through the
governed connector. Migration `20261027192257_founder_import_preview_rebuild`
is installed and its reviewed function/security boundary is verified. Its source
blob `062994241c20b19f7321082738e05473a26075c3` is identical at PR #760's
tested head, its merge, deployed code `fb19e7e` and main `44b1a932`.
The rebuild flag is true. Deployment
`20131280-07c8-474e-8932-2a0df29baf71` reached SUCCESS at 19:26:37.659 UTC,
after its normal predeploy suite passed 7,256 tests, 18 skipped and one warning
in 23.99 seconds; runtime readiness returned HTTP 200 at 19:26:32.903 UTC.
No batch rebuild, historical import replay or live founder UI trial was performed.
The capability is deployed and enabled; founder acceptance remains open. Durable receipt
acceptance, native Google authorization and the bounded Drive pilot remain
separate unfinished work. See the
[activation evidence](evidence/import-preview-rebuild-activation-20261027.json).

