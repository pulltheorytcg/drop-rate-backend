# Comic and manga recognition and market values

## Requested outcome

Extend the existing Seller Hub book intake with camera/photo recognition and GBP
market values. Keep canonical printing identity, physical ownership and a seller's
asking price separate. Reuse the existing OpenAI transport, owner journal, eBay UK
sold feed, v4 calculation and scheduled refresh; no schema, paid service, worker
or Shopify theme publication is introduced.

## Scanner

`Scan → COMICS / MANGA` and `Add a comic or manga` open the same form. A mobile
camera capture or gallery upload accepts up to three photographs of one book:
cover, copyright/barcode page and, where relevant, grading label. Photos are
resized locally and sent to the existing configured vision model. The endpoint
validates image format, dimensions and byte limits. Images are not stored in the
recognition journal or attached as approved listing media.

The model supplies visible evidence only. Independently confident supported fields
prefill the form; unclear language, volume, printing, barcode or label fields remain
blank. ISBN/UPC checksums are validated. Manga BGS/CGC and comic CGC labels are
transcribed, not authenticated. Condition is always a human choice. The response
is `NEEDS_REVIEW` or `NO_MATCH`, with no money calculation or automatic stock save.
The existing explicit book intake creates a draft personal-collection copy.

Owner authorization and RLS guard both endpoints. A five-minute image/model receipt
deduplicates repeats, an owner-level database lock serializes admission, and at most
20 new book recognition receipts per owner per hour are admitted. Failed receipts
also count. Images may be retried in a subsequent five-minute slot. Changing user
or closing the form invalidates late responses. Revoked access during model work
prevents the result from being returned.

## Market values

The read-only `Check market value` endpoint resolves only an existing exact
canonical printing and physical condition/grade from stored shared evidence.
The existing scheduled sold refresh may price verified book identities once their
copy identity, printing, year, cover, publisher, language and condition/grade are
complete. User-entered/scanned identities still require the existing founder
review of both canonical book/profile records; recognition does not self-verify.

Five distinct exact UK GBP sold records within 90 days are required. Matching
requires explicit title evidence for series, issue/volume, publisher, year,
language and printing, plus recorded ISBN, edition, cover and artist. Generic
`Used` is not a book condition comparison. Raw condition and graded company/grade
are separate. Bundles, multiple volumes, contradictory covers/printings/labels,
facsimiles, digital products, and signed/restored/qualified copies are excluded.
Special-copy notes also block a standard-copy value. Current support follows the
existing English/Japanese market pipeline; other languages remain unavailable.

The calculation uses the existing v4 estimator and stores the full book identity
digest with immutable sold evidence and snapshots. A printing changed during the
provider request cannot receive its previous printing's price. Recalculation and
inventory/catalogue display reject a mismatched digest or unverified identity.
Shared values are independent of owner; catalogue browsing labels the raw-condition
reference. Market evidence never sets the seller's asking price, cost or listing.

## Verification and live limitations

- Focused Python tests exercise recognition evidence, checksum/field bounds,
  strict multi-image transport, wrong volumes/printings/covers/grades, duplicate
  or invalid sales, pricing v4, special-copy notes and shared identity digests.
- The collection CI fixture exercises the actual recognition table definition
  and owner policies using signed local JWTs and a restricted PostgreSQL role:
  concurrent receipts, cross-owner isolation, provider failure, revoked access,
  rate limits, absent-price lookup and no automatic inventory write.
- The market CI fixture persists synthetic book sales through the actual refresh
  and catalogue valuation code, then verifies two owners, concurrent printing
  changes, unchanged asking prices and immutable history.
- Chromium/WebKit fixtures at 390px/1440px exercise real photo decoding,
  explicit confirmation/save, source errors and late responses after field,
  account or dialog changes. These are fixture checks, not proof of real phone
  OCR accuracy or actual sold-price coverage. Full CI and deployment readback
  must pass before release is claimed.

Read-only production checks on 16 October found zero canonical comic/manga
records. The existing sold provider returned HTTP 429 and recorded a pause until
17 October 2026 at 17:00 UTC (18:00 BST). No new live book values can be claimed
from this release. Values remain unavailable until verified books and sufficient
permitted sold evidence exist and the existing provider can resume. No credit
purchase, forced refresh, archive deletion, financial update or artificial product
creation was performed.

Shopify's comics/manga collection and unpublished theme work remain as previously
recorded; this change does not add a book Shopify publishing adapter.
