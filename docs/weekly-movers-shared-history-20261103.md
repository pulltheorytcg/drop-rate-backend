# Collection weekly movers: shared history, 3 November 2026

## Cause and correction

Collection values already use `reference_portfolio()` and immutable
`tcg.catalogue_market_snapshots`. Both mover endpoints still used the older
per-inventory `tcg.pricing_snapshots` and required eBay-only current records.
The owner endpoint additionally treated calculation time as observation time.
Those disconnected series produced no valid comparison in either main account.

`inventory_market_movers.py` now reads the exact current shared snapshot selected
for each authorized active holding. Both `/api/v1/owner/insights` and
`/api/v1/inventory/intelligence` call the same helper. This is a read-only change:
no price calculation, provider request, backfill, stock mutation, schema change
or scheduling change occurs on page load.

## Comparison contract

- Scope remains the authenticated owner's current collection. DRAFT, INSPECTION,
  APPROVED and RESERVED copies count; SOLD and WITHDRAWN copies do not.
- Current evidence must still be eligible under the collection resolver and no
  more than seven days old. Catalogue-only comparisons and stale last-known
  amounts cannot supply a current holding value.
- For a seven-day view, baseline evidence must be six to eight days before the
  current evidence date. The closest observation to seven days wins. The earlier
  snapshot must also have been recorded in the earlier period; a recalculation
  today cannot create a historical point.
- Both snapshots must match canonical identity, physical basis, language,
  grading company/grade, seal state, algorithm, method, source, ruleset revision
  and any book printing digest. Sold evidence keeps its five-input and sale-age
  requirements.
- Guide estimates also match provider reference, quote source, finish, source
  field, product/variant, currency, FX provenance and exact printing metadata.
  Historical GBP amounts remain as originally recorded. Only the current guide
  is required to exist in today's cache; requiring an old price to equal the
  current cache would erase genuine changes.
- Identical owned physical profiles appear once with a quantity. Amount and
  percentage changes are per unit. Guide movements are explicitly labelled
  estimates; they are never promoted to exact sold-market valuations.
- Responses include actual baseline/current dates and distinguish an empty
  collection, missing current values, waiting for history, no change and real
  movers. Missing data is not a zero value or a zero-percent trend.

## Production read-only verification

The new query executed successfully against production on **3 November 2026 at
22:53:26 UTC**. The same Python collection resolver and mover helper were then
run against that bounded captured result. The first two rows are account-local; the final row is the combined remainder
of active inventory, not a separately verified account. A profile means one
exact physical valuation basis.

| Account scope | Active copies | Eligible current copies / profiles | Old comparable profiles | New comparable profiles | Changed / unchanged |
| --- | ---: | ---: | ---: | ---: | ---: |
| Founder collection | 509 | 328 / 297 | 0 | 95 | 52 / 43 |
| Seller review collection | 106 | 7 / 5 | 0 | 0 | 0 / 0 |
| Other active inventory (combined) | 2 | 0 / 0 | 0 | 0 | 0 / 0 |

All 95 comparable founder profiles were guide estimates. The 52 changes span
actual evidence gaps of 6.62–6.81 days; the earliest baseline was 25 October
17:48 UTC and latest current evidence was 1 November 13:11 UTC. The owner panel
shows up to six changes, and the founder panel ranks risers and fallers separately.

The seller review collection has six copies across four current sold-market
profiles, one copy with a current guide estimate, six copies needing details
and 93 without an eligible current value. Its four sold-market profiles each
have eight stored snapshots, but their actual
evidence dates are only 8/9 October and 1 November. There is no genuine point in
the required late-October weekly window. The new panel therefore reports its
coverage and waiting state truthfully; this deployment cannot create those
missing old observations. The added guide profile also has no qualifying weekly
comparison: its nearest old observation is 8 days, 2 minutes and 28 seconds
before the current evidence, just outside the documented six-to-eight-day
window. This is insufficient *matching weekly* history, not an assertion that
no historical record exists.

Current coverage increased during the handoff because the Cardmarket valuation
pass finished at 22:39:46 UTC with 244 shared snapshots and zero provider calls.
The founder has 202 currently valued profiles waiting for history and seven
stale copies. The remaining active inventory is a combined diagnostic bucket: zero currently
valued copies, one copy needing details and one unavailable value.

## Remaining provider limitation

The latest completed shared sold-market valuation pass was 2 November at 03:03
UTC: 133 valued products and 133 inserted snapshots, with 1,923 canonical products
missing exact evidence. Bulk catalogue valuation is scheduled for Monday 03:00
Europe/London. The permitted eBay provider loop checks hourly and backs off for
24 hours on HTTP 429.

Read-only ingestion receipts showed 13 provider failures in the previous 14 days,
all HTTP 429, with the latest retry time at 3 November 23:38 UTC. The most recent
133 successful five-sale updates were on 1 November. A future comparable week
for the four seller profiles is conditional on another successful, sufficiently
spaced provider observation and the scheduled catalogue pass. It is not promised
by the UI. No provider quota, credential, ingestion or automation settings were
changed for this UI correction.

A separate read-only capacity receipt at **22:54:58 UTC** measured
**430,197,907 bytes**. PostgreSQL is writable, but the existing **400 MB** bulk
refresh pause still applies. Consequently, the next scheduled Monday slot
(9 November) is not a readiness promise: provider recovery, sufficiently spaced
qualifying evidence and the capacity gate must all permit the later pass.

The existing R2 history cleanup archives `reference_market_history` guide-cache
history. It does not remove `catalogue_market_snapshots` or `market_observations`,
so it does not supply the absent eBay weekly baseline identified here.

## Continuation review after the chat handoff

The pending work was recovered intact and applied to the latest main branch,
including the separately released R2 catalogue changes. Collection photo
handoff, comic intake, optional costs, removal and duplicate-save protections
remain in the regression scope.

Review found and corrected a small monetary display edge: an actual one-penny
rise or fall on an expensive item can round to `0.00%`. Founder ranking now uses
the exact integer-pence difference for direction, and both panels display the
correct arrow with `<0.01%`. An unchanged price remains excluded.

The first local full Python run uncovered a missing SOCKS library in the local
test runner and two tests pinned to the previous script cache version. The
runner-only dependency was supplied without changing application dependencies;
all 65 affected runtime cases then passed, and the two cache assertions were
updated to verify the released script version. The final affected Python set
passed 77 tests. The complete GitHub run and Railway release remain separate
verification gates.

## Verification

`tests/test_inventory_market_movers.py` covers copy grouping, removed items,
truthful states, source/identity response guards, current freshness, historical
recording times, finite money arithmetic and batches of at most 100 snapshot IDs.

`tests/inventory_market_movers_postgres.py` executes the exact parameterized
production history SQL and actual shared-reference migrations in disposable
PostgreSQL/PGlite. It checks a genuine old guide quote absent from today's cache,
sold and guide movement, rising/falling/unchanged values, 18 physical/source/time
exclusions, current mapping and identity rejection, owner membership/RLS,
duplicate quantity, removed holdings and unchanged database state on reads.
The standard backend CI runs this fixture after installing its existing pinned
disposable PostgreSQL dependency.

The live-market persistence fixture now explicitly rejects per-copy legacy
history as a substitute for shared collection history. Existing collection
resolver, owner API, insight/media and founder ranking tests remain in the
regression set.
