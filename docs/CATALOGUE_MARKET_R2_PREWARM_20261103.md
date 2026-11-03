# Market R2 cold-start warm-up — 3 November 2026

## Problem and scope

The API already preloads the shared R2 catalogue and its browse index at
Railway startup. The separately versioned R2 market-price snapshot previously
began its verified download on the first catalogue request that needed prices.
This causes an avoidable first-visitor SQL fallback while the market cache is
cold. This change warms **only the shared market snapshot** at startup. It does
not import, recalculate or invent any quote or change price/source eligibility.

## Implementation

- `catalogue_r2_market.prewarm()` reads the current published manifest under
  the configured existing maintenance actor, through `user_connection` and a
  read-only RLS-scoped transaction.
- `read()` schedules the existing integrity-checked, bounded R2 downloader
  asynchronously and releases that database transaction promptly. API readiness
  does **not** wait for the download.
- The API lifespan schedules this best-effort warm-up only when an authorised
  maintenance actor exists and market delivery is enabled. It uses the same
  shutdown cancellation collection as the main R2 catalogue prewarm.
- The existing four globally bounded R2 read slots are shared by main catalogue
  and market downloads. Integrity checks, immutable generation matching,
  condition/language/expiry rules and SQL fallback are unchanged.

## Failure handling

Disabled/missing actor, temporarily unreachable database or R2, stale or
partial publication, invalid digest, and overlapping cold-start downloads all
leave the existing authorised PostgreSQL path available. Nothing in this patch
changes the 400 MB import guard or owner/settlement data.

## Verification and acceptance

- Test the RLS maintenance actor, request purpose and read-only snapshot.
- Hold the mocked R2 download open and prove `prewarm()` completes without
  waiting; verify the cache is eventually loaded after release.
- Test missing/disabled configuration and database failure are fail-open.
- Run live/market R2 generation, browse and concurrent download tests.
- Before release: green GitHub CI, then Railway successful deployment and
  readiness. After a cold restart: verify market and catalogue `LOADED`
  log entries appear before or independently of the first browse, with
  lower cold-request latency, no `LOAD_FAILED`/permission errors and no
  increase in 404s. This is a targeted cold-start optimization; it does not
  promise faster unrelated value-sort SQL or fill missing prices.

## Separate pricing blocker found in production

Read-only audit on 3 November found 38,178 eligible recently sourced or
language-guide-backed reference prices across 60,051 physical Pokémon,
One Piece and Dragon Ball references (**63.58%**). Reaching 89% on those
three supported games requires at least **15,268** more eligible references.
Naruto is excluded pending permitted source coverage. The bulk refresh was
deferred while database size was approximately 420 MB, above the established
400 MB operational pause. Preserve that pause until a fully verified,
restorable database capacity change is separately authorised. An asking
listing or an expired/provisional quote does not count as a verified price.
