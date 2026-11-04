# eBay publication audit repair

An approved individual card can pass all nine preparation checks and still fail
with HTTP 422 before eBay publication. Both the started and verified-publication
writers use `EBAY_INVENTORY_LINK`; the original marketplace audit constraint only
accepts `LISTING`, `MEMBERSHIP` and `RESERVATION`.

The additive migration accepts the missing eBay entity type in one atomic ALTER.
It preserves all previous types, existing audit rows, owner/actor RLS and the
API role's append-only grants. It changes no inventory, price, media approval,
shipping policy, publication switch or financial record. A five-second lock
timeout fails the migration instead of waiting indefinitely.

Regression tests execute both actual publisher INSERT statements against the
original PostgreSQL schema: reproduce the old failure, apply the migration,
verify both writes and existing rows, reject unknown types/foreign owners/actors,
and deny update/delete. CI explicitly runs these tests with the pinned PGlite
PostgreSQL runtime, so optional local skips cannot constitute release evidence.

Release: pass backend/UI CI, apply this migration, verify the production
constraint and unchanged permissions, then retry exactly one approved item from
the signed-in founder UI. Check local state and the remote listing before any
retry. Existing `LIVE` links return idempotently; provider offers are recovered
by the unique physical-copy SKU rather than blindly creating another offer.

Rollback: retain this backward-compatible audit extension. Do not delete audit
history or restore the old constraint after eBay rows exist. If a separate
publishing defect appears, stop the single-item test and diagnose it; do not
bulk-list inventory or relax preparation checks.
