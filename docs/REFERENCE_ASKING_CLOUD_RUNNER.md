# Manual cloud reference-pricing batches

## Active batch: 29 October 2026

The founder authorised live execution while using mobile with the laptop off.
A dedicated Railway worker now runs the existing tested operator independently
of a local CLI session. The storefront/API configuration is unchanged.

- Service: `reference-pricing-batch` (`6ddca000-0de6-4c73-9808-4f2e9fa755c8`).
- Project/environment: `9329767b-b092-495c-bf18-75cf69c28536` /
  `6f00816c-b630-4d0b-bcc1-26ac71fa712d` (production).
- Pinned source: `0b8a89d60d29117923ebe111872397bd5129f100` from
  `pulltheorytcg/drop-rate-backend`.
- Deployment: `c40c993b-1335-4582-83f3-ea6d46224834`, observed SUCCESS.
- Durable run: `ce1f435a-3a1c-4a94-889d-8fe887da7147`, started
  2026-10-29 00:16:32 UTC, apply mode, English, at most 1,000 Browse checks.
- At 00:17:42 UTC: RUNNING, 55 requests reserved, 54 collected, 1,277
  references scanned, 78 summaries, zero accepted/written estimates. This is
  an early execution receipt, not the final result.

The worker uses Railpack/Python 3.12, one Amsterdam replica, outbound IPv6,
`restartPolicyType=NEVER`, no cron, no public domain, no volume and no
pre-deploy command. Source is pinned so ordinary main pushes cannot rerun it.
It exits after the operator finishes; keep the stopped configuration available
for later explicitly requested runs.

## Command and credential scope

The startup command binds one stable run ID to the existing worker using
`functools.partial`; it does not change pricing or acceptance rules. The run
primary key prevents a second invocation with this ID from starting a new
collection. A restart without an explicit resume therefore fails before a
provider search rather than spending another batch.

```sh
python -c 'from functools import partial; from uuid import UUID; import backend.scripts.backfill_reference_asking as runner; runner.backfill_reference_asking = partial(runner.backfill_reference_asking, run_id=UUID("ce1f435a-3a1c-4a94-889d-8fe887da7147")); runner.main()' --from-settings --run --apply --max-queries 1000 --language English --output /tmp/asking-ce1f435a.json
```

Variables reference the existing `drop-rate-api-live` service inside Railway:
`TCG_DATABASE_URL`, `TCG_AUTH_ISSUER`, `TCG_AUTH_AUDIENCE`,
`TCG_SUPABASE_PUBLISHABLE_KEY`, `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID`,
`TCG_EBAY_CLIENT_ID`, `TCG_EBAY_CLIENT_SECRET`, `TCG_EBAY_MARKETPLACE_ID`,
`TCG_EBAY_ORIGIN_POSTCODE` and `TCG_ENVIRONMENT`.
Values were not exported or printed. The pool is limited to 1–2 connections;
`PYTHONUNBUFFERED=1` and `RAILPACK_PYTHON_VERSION=3.12` are local settings.
No Shopify, payout, marketing, seller-publishing or other provider credentials
were added to this worker.

## Monitor and recover

Read the durable receipt while the process runs:

```sql
select id, started_at, finished_at, status, requests,
       report->'stats' as stats, report->>'stop_reason' as stop_reason,
       report->'quota' as quota
from tcg.reference_asking_runs
where id='ce1f435a-3a1c-4a94-889d-8fe887da7147';
```

The database receipt is authoritative; `/tmp/asking-ce1f435a.json` is only a
local checkpoint and may disappear after a deployment. Reaching 1,000 checks
normally reports INCOMPLETE / REQUEST_LIMIT because the entire catalogue has
not been exhausted. Other stop reasons require inspection before resuming.
The 45-minute deadline, 2,000-request daily cap, provider quota headroom and
exact-match requirements remain enforced by the tested worker and database.

Before another launch, inspect both the receipt and deployment/process state.
Never blindly restart a potentially active worker. An authorised continuation
must keep scope/apply mode, use `--resume-run`, and request only the remaining
checks. A new completed-run continuation needs a fresh run ID; do not reuse an
immutable completed receipt. Preserve the global reservation ledger.

Before this batch, all 616 physical inventory rows had snapshot
`47a316ca0609fbbfedcd32f002c4c335` using the query below. Compare it after
completion; attribution requires review if another service changed inventory
concurrently.

```sql
select count(*) as inventory_rows,
       md5(string_agg(row_to_json(i)::text,',' order by i.id)) as inventory_snapshot
from tcg.inventory_items i;
```

Read actual persisted estimates/history and global coverage after completion.
Launch success and request counts do not imply price coverage gains.
