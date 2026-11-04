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

Production verification, 4 November: all three GitHub checks passed at
`3bc411ce`. Supabase applied the exact tested migration as `20261104123236`;
the migration-history manifest maps the CLI-generated source to that observed
version. Constraint read-back, owner/actor policies, forced RLS and append-only
grants were verified; the security-advisor findings were unchanged.

The founder retry then passed the former database failure but received HTTP 500
from an eBay seller request. One controlled retry returned HTTP 404, with the same
generic UI message. The channel link is `ERROR` with `PUBLISH:404`, with no locally verified offer or
listing ID. This is not a successful publication. The seller client now records
only an allowlisted API resource, HTTP method/status and bounded numeric eBay
error IDs. It never logs response messages, parameters, headers, tokens, request
bodies, query values or physical-copy IDs. Tests inject sensitive-looking data
in those fields and assert it cannot reach the logs or public exception.

PR #895 merged as `35a5dc28` after five GitHub checks. Railway deployment
`466c0b27-85ce-4c31-a900-339c681e5df3` reached SUCCESS at 12:49 UTC, with
10,005 tests passing in pre-deploy. The subsequent founder attempt isolated the
remaining failure to GET `/sell/inventory/v1/offer`: HTTP 404, error 25713.

The offer collection lookup now consumes only the explicit absent-offer result:
HTTP 404, exactly one error with ID 25713, domain `API_INVENTORY`, category
`REQUEST`, on the exact GET collection route. A private typed exception carries
that result to `get_offers`, which returns an empty list; the existing publisher
then creates the first offer. Other errors and individual-offer requests retain
their fail-closed behavior. The original unique-SKU recovery and live read-back
remain unchanged. Tests cover absent/existing offers, blank SKUs, auth/rate/server
failures, malformed/mixed errors and other endpoints (86 focused eBay tests pass).

Reference: [eBay's Inventory OpenAPI specification](https://developer.ebay.com/api-docs/master/sell/inventory/openapi/3/sell_inventory_v1_oas3.json)
documents the offer collection's 404 response; the exact 25713 response was
observed in the authorised live test. A successful listing is still a separate
post-deployment acceptance gate.

PR #898 deployed as `91e4348c` (Railway
`80984480-19f8-4ce8-ab08-e75e2af9158d`, SUCCESS at 12:58 UTC;
10,027 pre-deploy tests passed). The next attempt still logged the exact
GET-collection/404/25713 response. The initial classifier's domain/category and
single-error assumptions were too strict for the live response. The corrected
classifier requires the exact route and status and one to ten errors, each
containing numeric ID 25713. It ignores descriptive metadata but never ignores
an unknown/malformed additional error. The lookup still performs no mutation,
and subsequent offer creation remains subject to eBay's own validation.
91 focused eBay tests cover this boundary. Publication remains unverified until
the next post-deployment founder acceptance test.
