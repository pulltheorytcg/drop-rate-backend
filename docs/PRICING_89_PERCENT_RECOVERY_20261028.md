# Physical-card pricing coverage: 89% goal — 28 October 2026

## Goal and measured starting point

The founder's current target is **89%** of the full physical-card reference
catalogue with supported dated prices or explicitly labelled source guides.
It replaces the earlier 95% reporting goal. It does not change which records
or evidence qualify: digital Pocket references remain explicitly excluded;
unmatched, stale and unsupported prices still do not count. This is distinct
from comic/manga asking-price context and physical-copy valuation.

The production coverage receipt completed at **10:07:18 UK time on 28 October**
contains **43,269 / 67,065 priced physical references (64.52%)**. The receipt was
read at 10:13:16. Reaching 89% requires **59,688**, another **16,419** supported
prices. The 61-reference increase since yesterday's checkpoint belongs to the
existing background jobs, not this code change. See the
[baseline evidence](evidence/pricing-89-baseline-20261028.json).

## Repairs

- The One Piece and Dragon Ball free-source readers previously treated every
  positive detailed cache entry as current. They now use the same seven-day
  freshness window as coverage, allowing an expired value to be checked
  against the existing independent guide source.
- The Japanese Pokémon importer revisits its own positive guide after one day,
  while preserving another adapter's positive guide. A cache selection alone
  never advances an evidence date; a successful, complete and unambiguous new
  provider response is required before a write.
- Japanese Cardmarket-only releases can use negative source set IDs. The
  parser accepts that documented format while retaining literal source IDs,
  exact set codes, complete pagination and collector fractions. Duplicate
  releases and parallel printings remain unresolved.
- Fixed reason labels and bounded source-shape counts expose why an exactly
  matched Japanese reference has no usable quote. No alternative price field
  is accepted merely to increase coverage.
- The existing coverage report now calculates the founder's 89% threshold
  using integer arithmetic. A rounded display of 89.00% cannot pass below the
  required number of priced references. Updating the goal adds no prices.

## Provider dates and bounded verification

PokéWallet says its `updated_at` is the last time a price **changed**, not the
last time it was checked. An unchanged guide may legitimately have an old
provider timestamp. Preserve that source metadata and keep it distinct from
the time of a successful fresh API observation. Failed requests, missing
quotes and incomplete responses do not renew cached evidence. Sources:
[provider explanation](https://pokewallet.io/blog/tcg-price-api-12-card-games-one-key),
[timestamp handling](https://pokewallet.io/blog/build-one-piece-card-price-tracker-berrywallet-api-tutorial),
[API contract](https://pokewallet.io/api-docs).

The opt-in `pokewallet_jp_source_probe.py --execute` performs at most three
free read-only calls: `/sets`, then the first search page for up to two
negative-ID Japanese sets. It preserves the existing quota reserve, never
calls paid endpoints, and emits no credentials or source price amounts.
Incomplete searches produce page-shape counts only. Probe results establish
source shape, not unique catalogue matches or a coverage increase.

## Release gates and remaining constraints

Use normal PR CI, the native PostgreSQL persistence checks, the unchanged
Railway predeploy command and terminal deployment success. Verify the next
normal hourly receipts and distinct coverage separately from write attempts.
The release record must identify the actual source-probe and live results.

No provider allowance is reset. Hourly request allocations, weekly bulk
cadence, the 400 MB capacity guard, source-permission holds and physical
inventory/Store Price rules remain in place. No broad price backfill is
claimed from parser or reporting changes alone.

At this baseline, 7,166 Naruto references still have no eligible source.
If those remain unpriced, 89% requires all but **211** of the other 59,899
references to be priced. Existing free-feed repairs alone have not established
that this is achievable. Additional exact source and printing evidence remains
necessary across the unresolved cohorts.
