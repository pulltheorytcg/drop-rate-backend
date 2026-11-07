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

PR #899 deployed as `2869fbad` (Railway
`78e32516-b94a-4345-a006-9dd8e102845e`, SUCCESS at 13:11 UTC;
10,032 pre-deploy tests passed). The founder retry progressed beyond the
absent-offer lookup and received POST offer / HTTP 400 / error 25002, a generic
listing-validation error. No local LIVE state or publication ID was recorded.

Diagnostics now distinguish collection, detail and publish/withdraw operations
without logging identifiers. A bounded classifier emits only predefined labels
for known listing fields and validation concepts, derived from error messages
and parameters. Raw provider prose, parameter values, addresses, email addresses,
tokens and IDs are still never logged. These labels are diagnostic clues, not
authoritative field corrections; actual inventory facts and eBay requirements
must determine any repair. Tests verify static-only output and malformed bodies.

PR #901 deployed as `9669da90` (Railway
`9ba02a1c-90ae-4547-9654-427a455074df`). The next controlled test isolated the
error to `publish`, with only `length` and `card_name` hints. The canonical name
is 66 characters; eBay's standard item-specific value limit is 65. The payload
now removes the exact repeated card-number segment from an overlength Card Name
when the catalogue's separator/suffix pattern permits it. Longer remaining names
are bounded at a word boundary, while complete canonical identity remains in the
description and database and the separate Card Number is unchanged. Valid-length
names, owner, quantity, photos, price and graded descriptors are unchanged.
Regression tests cover the actual 66-character case, the 65-character boundary,
Unicode, longer names and identifier-prefix collisions. Live retest remains pending.


PR #905 deployed as `2c330a01ff42f1bd5abf206830fb7db8ab0fa1be`, Railway
`da770f7b-8bf3-429c-b5fc-ed0e4d192543` SUCCESS, with 10,045 pre-deploy tests
passing and 28 optional skips. The next founder attempt at 13:33 UTC passed
Card Name validation but failed publish with HTTP 400/error 25002. Static hints
were `missing`, `account`, `verification`, and `format`. The last label was a
classifier false positive from `information`; the format matcher now uses word
boundaries. The remaining account requirement must be inspected in eBay itself;
these hints do not identify a particular missing bank, identity or contact field.

The link remains ERROR / PUBLISH:400, without a verified offer/listing ID or
publication timestamp. The physical copy remains owned by the same founder,
priced at GBP 35. Seller Hub opens at a separate sign-in page, while the founder
app session remains active. No further publish retry should run until the seller
account action is resolved. Recover the existing offer by SKU when resuming.

For POST offer publication only, HTTP 400/error 25002 with account, verification
and required/missing hints now returns a static actionable Seller Hub message.
No raw provider prose is exposed. Regression cases cover the actionable response,
other endpoints/codes, a different item validation error and retryable server
failures, including injected private-looking fields that must never be logged
or returned. No account status, credentials, inventory or publication gates are
changed by this message improvement. A live listing is still an outstanding
acceptance gate; successful code tests do not establish eBay publication or sales.
