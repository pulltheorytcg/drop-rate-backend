# Asking acquisition funnel diagnostics

The existing official Browse worker now records count-only stages independently
from estimate persistence and Market Value eligibility. It does not change
queries, detail limits, matching, seller minimums, confidence, expiry, quotas,
capacity protection, source permissions or UI. No additional provider calls.

A search attempt is counted with its durable reservation, including failures.
Successful nonempty searches and discovered summary rows are separate. Selected
detail IDs can exceed calls actually made when the existing budget ends. Full
details counts bound, ID-matching responses; reused cached details are evaluated
again but are not new network retrievals. Exact acceptance includes existing
identity AND raw condition checks. Price/shipping validity, duplicate item/seller
removal, finish grouping, outliers and reference-level sufficiency follow that.

First-failure candidate rejections and dedup/sample rejections have separate maps.
They are not all independent rejection attributes. Reference outcomes separately
report insufficient comparables, stale evidence, dispersion and generated estimates.
Missing language proof is counted separately from explicit conflicting language;
neither is inferred from a UK seller. A generated estimate is not a committed
record. Persistence count commits in the same transaction as history/cache.

Current Market Value display eligibility remains zero for this excluded Browse
path; valuation permission remains NOT_VERIFIED. These diagnostics do not grant
rights or activate production valuation. Inspection must distinguish the current
policy blocker from an acquisition/matching failure.

Resuming an old receipt starts new counters with prior_requests_not_instrumented.
Old counts are never reconstructed as zero. receipt_funnel provides a read-only
legacy view and uses null for missing historic detail/identity/display evidence.

Validation: 361 affected tests pass, including a synthetic three-reference worker
sample: three searches, two nonempty, six details, six exact identity/condition
matches, three valid comparables, one generated estimate, zero writes/display.
Other cases cover wrong language/number/set/finish/grade/condition, missing
shipping, duplicate sellers, stale input, preserved resume counters and atomic
persistence rollback. Native PostgreSQL contract CI remains required.

This is instrumentation, not restored live price coverage. Real live receipt
counts and private release evidence are retained outside the public repository.
