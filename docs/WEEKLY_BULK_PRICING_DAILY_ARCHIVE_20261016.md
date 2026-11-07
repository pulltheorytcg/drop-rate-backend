# Drop Rate archive + pricing cadence — 16 October 2026

## 1. What we're changing

The founder authorised:
- **Daily verified reference-market-history archival** at **04:00 Europe/London**, beginning Saturday **17 October 2026**; and
- **Weekly bulk source-pricing updates**, on **Mondays at 03:00 Europe/London**, first eligible **19 October 2026**.

The archive schedule was changed by ChatGPT's automation facility; it is **not** a Railway cron or Supabase pg_cron job. At the time of this release, the automation has **never completed an unattended verified archive**; a calendar schedule is not archival evidence. No new external archive storage or unapproved credential is added to Railway. The job must still prove full-field export, typed disposable restore, private Drop Rate Drive upload, downloaded package SHA-256 and the existing atomic full-content guard before removing any live history. If tooling is unavailable, archiving fails **without deleting records**.

## 2. Why / connections

Production Supabase Free is **405,499,027 / 500,000,000 bytes**, with **50,378 unarchived** price-history records following the 15 October source refresh. The 400 MB guard already defers bulk imports until verified archival lowers the actual database size.

- **Railway**: The existing `drop-rate-api-live` FastAPI service already runs `catalogue_maintenance.run_loop` every five minutes. No new service, cron, subscription or secrets.
- **GitHub**: `backend/app/catalogue_maintenance.py` adds the pure `weekly_price_slot` / `weekly_price_due` scheduling rules. The four heavy jobs `CATALOGUE_VALUES`, `CARDMARKET_VALUES`, `SEALED_REFERENCE_PRICES`, and `REFERENCE_PRICES` now run when the latest completed receipt was before the most recent **Monday 03:00 UK time**. An incomplete job may continue through paginated batches; a failed run retains its hourly retry/backoff. An initial fill with no prior receipt remains eligible rather than blocking new installations.
- **Supabase**: Existing immutable `tcg.reference_market_history`, `tcg.catalogue_job_runs` and source caches remain the authoritative audit trail. No schema changes or pg_cron installation; all maintenance still uses service-authenticated database calls.
- **Other daily operations**: Existing reference-catalogue identity/checklist intake retains its daily `due()` check; Shopify listing/price reconciliation, order/refund and founder/consignor allocations are unchanged. Per-card on-demand price checks may still use permitted sources; **weekly applies to full catalogue bulk repricing**, not each app interaction.

The regular UK schedule is Monday 03:00 pricing and daily 04:00 ChatGPT archive. Timing is derived in `Europe/London` via IANA timezone rules, including British Summer Time transitions. The scheduled archive should follow newly created Monday bulk history, not precede it.

## 3. Risks, controls and ongoing evidence

- **Unverified archival**: The daily automation is a requested, enabled task — **not proof** that storage is reclaimed. It may fail at export, restore, permissions or Drive readback. Never bypass the existing history digest guard or suppress the 400 MB pause to make weekly pricing appear to work.
- **Source freshness**: Present source prices and seven-day quote validity rules are unchanged. With weekly refreshes, exact references can approach seven days old before their next update; expired quotes remain visibly unavailable, not silently marked fresh. Missing exact edition and chase-card matches remain missing.
- **Interrupted source batch**: Preserve the existing `more_due_at_start` immediate continuation and provider-failure hourly retry. The weekly boundary doesn't strand a partial multi-batch import.
- **Other database writes**: Inventory, canonical updates, on-demand pricing and outbox may grow storage. The existing operations-monitor capacity warnings must stay enabled.
- **Provider limits**: Continue free, authorised existing data sources; no paid services and no scraping.
- **Clock transitions**: Monday 03:00 UK moves from 02:00 UTC in BST to 03:00 UTC in GMT. Avoid naive fixed UTC scheduling or a seven-calendar-day UTC offset.
- **Data protection**: No archive purge, schema modification, owner/Store Price change, Shopify repricing or settlement writes in this release.

## 4. Tests and release acceptance

`tests/test_weekly_bulk_pricing.py` validates Monday 03:00 Europe/London across October/March DST switches; weekly completion deferral, out-of-week code revision changes, retry/batch continuity, daily-source independence, once-per-week bulk worker eligibility and strict 400MB fail-closed preflight. Existing unit + real PostgreSQL CI and Railway predeploy suite remain gates. After deployment verify the exact merge commit on Railway, readiness, operations-monitor health and read-only inventory/price-history fingerprints.

**Final release claim must distinguish:**
1. Daily ChatGPT archive schedule = changed, *execution not proven*.
2. GitHub weekly backend scheduling = CI passed and merged.
3. Railway weekly schedule = only live after exact merge deployment SUCCESS.
4. Supabase current price data = unchanged; next market reference refresh remains blocked until a full verified archive clears the Free capacity guard.
