# Current-listing estimates for missing catalogue references

## Scope

The founder requested current-market evidence as well as sold prices and a
backfill toward 89% of physical reference cards. The 28 October 2026 22:04 UTC
baseline is 43,362/67,065 (64.66%); the threshold is 59,688. Digital Pocket
references are excluded and sealed products are reported separately.

This adds a catalogue-only asking-price estimate. It does not turn an asking
price into a sale or change physical inventory, store prices or settlements.
Existing supported reference prices and labelled guides take precedence.

## Evidence contract

The official eBay Browse API supplies fixed-price UK listings. The matcher
requires the same game, card, set/printing, explicit language, raw Near Mint or
Mint condition, and a positively identified finish. Slabs, lots, proxies,
auctions, unknown shipping and unresolved parallel identities are excluded.
An unresolved catalogue finish can receive an estimate for a clearly labelled
listing-finish group; finish groups are never mixed or written into identity.

At least three distinct sellers must remain after duplicate and outlier
removal. One seller contributes one comparable. The point estimate is the
median; quartiles and dispersion are retained as evidence. Low sample counts
remain low confidence. A fresh request is necessary to renew the three-day
expiry.

Calculated postage uses the existing configured shop postcode as a delivery
benchmark. It is labelled as such and is not an exact customer shipping quote.
The postcode is not exposed by the catalogue API or public evidence reports.

The cache is separate from the established reference-value tables. Historical
asking evidence is append-only; a cache write requires an identical snapshot
inserted by the same actor in the same transaction and generates an audit
event. Identity is rechecked immediately before writing.

## Backfill controls

The operator command defaults to planning. Network collection and applying
valid estimates are explicit choices. No scheduler, startup hook or pre-deploy
provider request is added. Resume uses a durable cursor rather than replaying
completed references. Request reservations commit before HTTP, including failed
requests. No database transaction is held across provider I/O.

The worker checks the application's actual eBay quota and every applicable
window, leaves headroom for existing features, and additionally caps this
backfill at 500 Browse attempts per UTC day. It starts sequentially at no more
than one request per second and stops on provider/auth/rate-limit errors.
The existing 400,000,000-byte bulk-ingestion guard remains in force.

Before deployment: pass the focused matcher/API/UI tests, the normal repository
CI and the disposable PostgreSQL contract test; apply the additive migration;
then verify the live release. Run a small collection batch, inspect acceptance
and rejection evidence, apply only validated candidates, and read back both
the persisted estimates and the complete coverage denominator.

## Reporting and limitations

Existing coverage fields keep their original meaning. A separate combined
coverage target includes eligible asking estimates only where a stronger
supported reference value is missing. Digital records and overlaps do not
inflate the count. Sorting by existing market value is unchanged.

At baseline, Naruto accounts for 7,166 unknown-language records; Japanese
Fusion/One Piece account for another 5,154 missing records. English Fusion and
One Piece include thousands of indexed alternate prints. A successful API
request does not resolve these identities or guarantee an 89% result.

CardTrader whole-set price access is being evaluated using the existing
connection. Metadata availability alone is not pricing evidence. Its cheapest
25 offers per product are a limited asking sample, and shipping/currency,
language and printing still need explicit treatment before any import.

The 500/day ceiling is a pilot control, not a capacity plan for 89%. With a
three-day evidence lifetime and one reference per request, it supports roughly
1,500 current estimates sustainably even at a 100% acceptance rate. Existing
guide refreshes, permitted bulk sources and exact mapping improvements must
cover the larger gap. Raising the request rate alone cannot solve it.

Recovery review on 28 October retained the full 67,065 denominator and confirmed
43,362 supported values. It recovered the missing disposable-database fixture,
completed the resumable worker, and added rejection tests for negated condition,
language, finish and printing evidence. No live price gain is claimed until
the applied batch receipt and database readback are recorded.

Rollback: stop the operator command. Prior deployed application code ignores
the additive asking tables. Retain historical evidence and audit records; do
not delete them to undo display behavior. Revert the display/integration code
if needed, leaving established market values untouched.

## Initial live pilot, 28 October 2026

PR #774 deployed at commit `b55f4ba3df1190435392fece8bdaf0b2134f58de` and
readiness returned HTTP 200 with the database connected. The backend suite
passed 8,104 tests (18 skipped), and all eight PR workflows passed. Migration
`20261028224708_reference_asking_prices.sql` was applied with forced RLS and
no anonymous or authenticated-user direct table reads.

Collection-only run `654de0b2-af23-4b67-8ef1-3e6fd1b46d6e` reserved and
completed ten One Piece English Browse searches. It scanned 586 references:
575 were rejected as unresolved parallels, one query exceeded the provider
length limit, and the ten executed searches returned zero item summaries.
No estimates, inventory changes or store-price changes were written. The run
stopped at its requested limit and retained its durable cursor and report.

The database readback remains 43,362 supported values plus zero asking
estimates out of 67,065 physical reference identities (64.66%). The 89%
threshold remains 59,688; the remaining gap is 16,326. Shortening retrieval
queries is the next pilot correction; exact-match acceptance checks must
remain intact.

Follow-up run `934c25c8-c2a2-4348-8d7a-953ba7221922` after PR #775 used
ten shorter queries and retrieved 205 summaries. It still wrote zero estimates:
112 listings lacked explicit matching language, 41 were multiple-item or
nonphysical listings, 25 failed the exact-set check, and the remainder failed
other identity checks. This confirms retrieval improved while acceptance
remained conservative. Twenty Browse requests total were used by these two
pilots; no physical inventory or store prices were changed.

A third collection-only Pokémon English run,
`74b1fdf8-247c-4489-bc29-d87d1ecff26c`, used ten requests and retrieved
205 summaries with zero accepted estimates. It rejected 77 graded listings
and 77 listings with unknown/mismatching language, among other identity
failures. Thirty Browse requests were used across the three pilots.

The separate, audited Black Bolt numbering repair recovered 92 existing-source
guides. Verified combined coverage is now **43,454/67,065 (64.79%)**, with
zero asking estimates and **16,234** additional records needed for 89%.
See [the live correction receipt](SV11B_NUMBER_RECOVERY.md).
