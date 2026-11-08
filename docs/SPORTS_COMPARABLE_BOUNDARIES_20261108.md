# Numbered sports comparable identity repair

Generic token matching could satisfy a target's `/10` variant with the `10`
from `PSA 10`. Different sets, autographs and memorabilia could also enter the
ordinary comparison pool. The shared manual/background sold matcher now applies
a sports-specific identity boundary before its existing price/grade checks.

Require the exact normalized canonical set phrase (which the existing sports
identity model builds from year, manufacturer and set) and the actual print-run
denominator. Reject missing/conflicting denominators and numbered copies against
unnumbered targets. Rookie, autograph/signature and patch/relic markers must agree
with the canonical identity. Existing name, card number, parallel, grade, condition,
language, recency and duplicate tests still apply. No rarity premium is inferred.

This is a bounded identity fix, not a complete sports valuation strategy. It does
not establish authenticity, autograph certification, physical serial-number
uniqueness, player-demand premiums or grading-population data. Ambiguous titles
and abbreviated/reordered set names may be excluded until a reviewed structured
adapter resolves them. The current canonical model still needs explicit richer
rookie/autograph/relic evidence before broader support can be claimed.

20 fixture failures reproduced before repair; 56 targeted tests pass afterward.
Tests include exact /10 positives, base, /99, missing serial, wrong year/set,
autograph, patch/relic and rookie exclusions through both pricing entry paths.
No production data, UI, source permissions, estimate type or SQL schema changed.
Review CI before release; use an authorized non-mutating preview for live
acceptance. Rollback is a code revert/redeploy, with no historical data deletion.
