# Live catalogue delivery from R2

## Production checkpoint — 30 October 2026

The complete catalogue published at **14:45:25 UTC**, after independent R2
readback, a comparison of **all 75,492 catalogue entry identities**, and eight
matching production query comparisons. PR #818 passed all ten GitHub workflows
and merged as `a4b377d7c38fedb26524991f06c8bddcae04ac8c`. Railway deployment
`e497007a-3af7-4314-b409-b8bc51cdca54` reached SUCCESS.

| Publication | Generation | Contents | Verified objects | Uncompressed bytes |
| --- | --- | --- | ---: | ---: |
| Catalogue | 121595 | 69,546 cards; 1,456 sets; 3,893 sealed references; 2,055 products; 2,055 profiles | 161 | 29,375,905 |
| Current market caches | 1 | 59,542 market records; 27,626 catalogue guides; 3,886 sealed quotes; 0 asking records | 366 | 103,799,009 |

The 91,054 price-cache records overlap identities and include source
availability/expiry states. They are **not** a count of independently priced
cards; copying them does not establish complete current market coverage.

Catalogue delivery, navigation, indexed browse and extended browse were enabled
after publication. The old exact-set background warmer was disabled; its
fallback reader remains available. The configuration rollout hit an
environment-dependent unit-test mock; the following test-only fix isolates the
ordinary-SQL route tests from inherited production delivery flags. Final rollout
verification is recorded below when complete.

## What Drop Rate reads

R2 supplies shared catalogue identity/display fields for games, sets, browse,
search, owned filters, sealed products and book entries. Bounded pages also use
exact matching rows from the separate R2 price snapshot. Existing SQL enforces
printing identity, expiry, ownership, inventory and book-validation rules.

**Full-catalogue value sorts retain their existing PostgreSQL query.** An earlier
attempt bound the whole entry population in one message, leaving the production
connection waiting for client input. The released route avoids that transfer.
Canonical and asking-price resolvers also retain their live SQL decisions.
These paths are intentional and are not reported as R2 delivery.

Importers and provider schedules continue to update source tables. A source
write invalidates its publication generation in the same transaction. The
maintenance worker publishes prices before catalogue validation and checks for
updates on its normal cycle. Missing, changed or invalid snapshots use current
PostgreSQL. A cold process loads and verifies immutable R2 objects in the
background while requests retain SQL fallback. This is a continuously refreshed
feed, not a claim that providers supply real-time prices for every product.

## Production comparisons

These are query computation timings, not browser page load times. Each case
returned matching results for the same authorised actor. The complete identity
multiset comparison precedes these page checks.

| Case | Existing SQL (ms) | Released computation (ms) | Delivery |
| --- | ---: | ---: | --- |
| Games | 573.39 | 1.26 | R2 |
| Sets | 537.69 | 16.55 | R2 |
| Browse | 16,909.79 | 135.88 | R2 + market generation 1 |
| Search | 5,695.01 | 418.82 | R2 + market generation 1 |
| Books | 382.12 | 59.33 | R2 + market generation 1 |
| Sealed | 256.35 | 40.03 | R2 + market generation 1 |
| Owned | 5,620.45 | 124.23 | R2 + market generation 1 |
| Value sort | 8,059.32 | 6,750.02 | POSTGRES_DYNAMIC_VALUE |

The read-only offline baseline has a bounded 30-second deadline. Application
request and R2 query limits remain unchanged; the value result reports no R2
timing. Any mismatch, upload failure, corruption or concurrent source change
prevents publication.

## Artwork migration

The API worker copies exact-reference artwork in resumable batches of 20, with
four downloads at once and a single-writer advisory lock. Each object is
downloaded and hashed before its current provider/printing/source-URL receipt is
recorded. Every database lease uses the existing maintenance administrator
through the normal authenticated connection wrapper. This fixes earlier raw
leases that saw no source rows under RLS.

Source policies cover existing Pokemon, Dragon Ball and One Piece sources plus
the Naruto archive and CardTrader Pokemon paths, including parentheses in
filenames. Signed R2 delivery uses verified receipts with original-source
fallback. Failed downloads back off; restarts resume from durable receipts.

At 14:41 UTC, **2,838 reference images were VERIFIED**, with 90 awaiting retry.
Copying continues automatically. **62,605** of the card records have source
imagery; **6,941 have no source image**. A storage copy cannot fill that separate
completeness gap. Sealed-image metadata is included in the catalogue, but this
checkpoint does not claim that every sealed image binary has been mirrored.

## Storage, access and validation

Both publications use closed projections, private immutable objects,
SHA-256/size/count/schema checks, independent readback and generation-checked
publication. Owner responses, physical-copy details, Store Prices, payment data,
secrets and approval decisions are excluded. Source tables and indexes remain;
this delivery release does not itself reclaim Supabase disk space. Physical
inventory is unchanged at **616 rows**.

Production migrations:

- `20261030002930_live_catalogue_r2_publication.sql`
- `20261030141054_r2_live_market_data.sql`
- `20261030141056_r2_remaining_reference_artwork_hosts.sql`
- `20261030142942_r2_cardtrader_image_filenames.sql`

Forced RLS, restricted publication permissions and all 16 price invalidation
triggers were read back. No-op price updates do not invalidate a publication;
rollback also rolls back invalidation. Security advisories were unchanged. One
stalled read-only validation connection was terminated after cancellation failed,
allowing the pending artwork migration to complete and clearing the lock queue.

All **8,473 local backend tests passed**, with 18 optional SQL tests skipped; the
initial deployment repeated the suite successfully. Native PostgreSQL CI passed
the realistic 70,000-card / 50,000-price fixture, two-owner parity, expiry and
identity rules, generation invalidation/rollback, permission checks, failed
upload/concurrent-update rejection and unchanged inventory. Restricted-role
artwork receipt tests cover additional hosts and stale-source rejection.

The local PGlite whole-catalogue fixture has a known locale-dependent game-label
difference; native PostgreSQL and actual production comparisons are the release
evidence. A signed-in browser check remains needed in this session: the available
browser is at the login page.

## Backout

Set `TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED=false` to restore ordinary catalogue
SQL after configuration rollout. Set `TCG_R2_MARKET_DELIVERY_ENABLED=false` to
restore PostgreSQL page-price inputs. Build flags can stop publication without
removing source data or verified objects. Keep image receipts and source
fallbacks. Archive and media workers have separate flags.
