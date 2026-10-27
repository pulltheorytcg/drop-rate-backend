# Community book cover references — 27 October 2026

## Purpose

Open Library edition imports deliberately contained factual metadata only. Most
comic and manga catalogue entries therefore had no artwork even where Open
Library could display an edition cover. This change adds a separate, attributed
community cover reference to those entries. It does not turn a community image
into a reviewed publisher cover or a photograph of a collector's copy.

The [official Covers API documentation](https://openlibrary.org/dev/docs/api/covers)
explicitly describes direct image embedding on public pages, OLID lookup, medium
thumbnails, courtesy source links and `?default=false` for a missing-cover 404.
It also prohibits crawling this API. The application makes no background cover
requests, bulk cover downloads or server-side image requests for this feature.

## Binding and exclusions

`backend/app/book_community_artwork.py` only emits a reference when both book and
profile remain `STRUCTURED`, the source is the trusted Open Library bulk import,
and the stored import receipt matches the exact provider mapping. It rebuilds
the import digest from current canonical book fields, product fields, language,
release date and official source snapshot. A changed identity, stale digest,
different source ID, incomplete mapping, reviewed metadata hold or revoked
source/rights record leaves the existing placeholder.

This proves which imported edition is being looked up. It does **not** prove
that Open Library attached the correct artwork to that edition. The UI therefore
labels the image **Cover reference · Open Library · Cover may vary**. The source
may change its attached image; this is an on-demand source reference, not a
hash-pinned or reviewed image asset.

The checked-in `book_community_cover_exclusions.json` suppresses known incorrect
source artwork independently of metadata review holds. Its initial exclusion is
`OL9465913M`: the returned image shows Korean volume 5 while the imported record
describes English *50 Rules for Teenagers*, volume 2, ISBN 9781413900941. No other
edition is substituted. Future visual reviews can append exact exclusions with
their reason and date; this file must not be used to label unreviewed images as
approved.

## Response and display

Eligible catalogue and saved-inventory items receive a `community_cover` object:

```json
{
  "kind": "OPEN_LIBRARY_EDITION_REFERENCE",
  "provider": "OPEN_LIBRARY",
  "edition_id": "OL8537239M",
  "language": "English",
  "image_url": "https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false",
  "detail_image_url": "https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false",
  "source_url": "https://openlibrary.org/books/OL8537239M",
  "scope": "COMMUNITY_EDITION",
  "status": "REFERENCE_ONLY"
}
```

The medium thumbnail is used in grids and detail views. It is the documented
size for detail pages and avoids requesting historical large/original images
that may redirect to archive-hosted files outside the image CSP. Only the exact
`https://covers.openlibrary.org` image origin is added to CSP.

Catalogue browsing, its detail panel, the selected-book intake preview, saved
collection views and the founder inventory grid render this separate field.
Existing approved copy media and reviewed publisher references keep priority.
The shared browser helper accepts only the exact typed provider, edition URL,
medium image URL and language binding. Images load lazily, use no referrer, and
are direct browser image loads without application credentials. A missing or
blocked image becomes a clean unavailable placeholder without title/ISBN search,
another-edition substitution, proxying or retry loops. Source links remain
outside selection buttons and do not launch intake.

`reference_image_url` and authenticated reference-image paths are not populated
from this object. The canonical media approval, R2 mirror, Shopify, recognition,
fingerprint and physical-copy confirmation paths do not consume these URLs.
Seller-entered or review-required books receive no new Open Library match.
Market values, printing status, ownership, quantities and approval are unchanged.

## Verification and rollout

The application helper was run read-only against the current 1,541 editions whose
identity source remains `OPEN_LIBRARY_CATALOGUE`. It accepted **1,540 reference
paths**: 767 manga, 547 other comics, 130 Marvel and 96 DC. The sole rejected row
was the known incorrect cover `OL9465913M`. There are 1,542 Open Library provider
mappings overall; one mapping points to an already reviewed publisher edition.
These counts describe eligible references, not image availability or accuracy.
See [the helper readback](evidence/book-community-cover-helper-readback-20261027.json).

The focused Python suite exercises unchanged receipts, identity/source/language
tampering, metadata holds, the known wrong cover, duplicate mappings, exact
read-only queries, publisher/media priority, inventory ownership boundaries and
exclusion from scanner candidates. The UI behavioral suite covers exact URLs,
lazy direct delivery, no authenticated proxy request, 404 handling, attribution,
source-link interaction, approved-media priority and intake fields staying
unconfirmed.

Local validation passed all 40 new Python checks. The focused existing/new
Python regression batch passed 168 tests, with seven optional PGlite checks
skipped because that isolated SQL runtime was not installed. The full existing
JavaScript DOM test command passed, including the new five behavioral groups.
The existing dispatch UI test emits jsdom's non-fatal `window.focus` notice;
its assertions and the command both succeed. This is local mocked validation,
not a claim of deployment or a production signed-in browser session.

The number of eligible references is not the number of available or correct
covers. Before recording rollout coverage, read the actual API response and
verify a bounded representative sample in the browser. Record source errors and
wrong-art exclusions separately. Do not crawl the API or claim all metadata rows
have usable artwork merely because a URL can be formed.

No schema migration, grants or production data update is required. Existing
application read access to provider mappings is used. Deployment and live result
checks are recorded separately from this implementation note.
