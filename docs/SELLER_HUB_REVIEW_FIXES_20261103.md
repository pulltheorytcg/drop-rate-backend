# Seller Hub phone-review fixes — 3 November 2026

## Scope and observed failures

This change addresses the user's review of the premium Seller Hub: the
Deadpool / Batman #1 listing journey, the Collection list layout, and the
arrangement of filters and sorting.

The supplied phone recording shows both comic photographs selected and both
permission checkboxes checked before a `Load failed` message at approximately
01:21. The detail panel then redraws and loses both selected files. Runtime logs
confirm a successful `comic-photo/upload-target` request at 16:34:10 UTC, followed
by an item reread and no `comic-photo/complete` request. The later listing-review
request succeeds at 16:34:25 UTC. This distinguishes the failed photo transfer
from an attempted Shopify product publication.

The old browser flow fetched Shopify's external staged-upload URL, while the
deployed Content Security Policy permits connections only to the application
and its configured Supabase origin. The browser therefore could not complete
that transfer. The existing generic mutation recovery then rebuilt the form,
discarding the local file inputs and unsaved preparation fields.

The recording also shows the Collection list clipped horizontally at around
03:10. Collection tables inherited a generic mobile table-to-card treatment
while retaining a desktop minimum width. Filter fields and sorting were split
across inconsistent rows above the items.

## Changes

### Comic photographs and listing review

- An authenticated, owner-scoped, same-origin endpoint accepts the raw JPG,
  PNG or WebP file. The server obtains and uses a Shopify staged target. The
  browser does not connect to an external upload origin, and the CSP stays
  restricted.
- Uploads have byte, decoded-image, timeout and destination limits. The caller
  cannot supply a transfer URL or multipart policy. A request UUID and content
  hash support exact retries, with owner, physical-copy and identity checks.
- The open item dialog retains both local file selections, permission choices,
  and unsaved preparation fields through errors and item rereads. Each side has
  a filename, preview, clear error and retry action. Files remain in memory only
  and are discarded on close, logout, account change, item change or identity
  change.
- A lost response is reconciled against the item read. A received photo is
  shown as pending review instead of encouraging another upload. Submitting one
  side preserves the other unsent side.
- Unsaved photographs and preparation edits cannot silently accompany a
  listing-review request. The form returns to Preparation and identifies the
  required save or upload.
- Review distinguishes the seller's remaining steps from Drop Rate's identity,
  intake, photo and shipping checks. Shopify reports `In review` for a saved
  inspection request. Success wording describes a saved listing request.
- Platform approval/readiness now uses comic/book condition or grade for comics
  and manga, and the figure condition contract for figures. These categories
  are no longer erroneously required to have sealed-product state.

Shopify's staged-upload and file-creation sequence is documented in its
[Admin API reference](https://shopify.dev/docs/api/admin-graphql/latest/mutations/stageduploadscreate)
and [media guide](https://shopify.dev/docs/apps/build/product-merchandising/products-and-collections/manage-media).

### Collection list and controls

- Collection-specific styles replace the conflicting mobile table rules.
  Phone rows have contained artwork, a two-line title, concise identity and
  status, and aligned market value and selling price. Desktop retains a
  four-column table.
- One toolbar contains search, `Filter & sort`, the selected grid/list control
  and refresh. The current product count and order remain visible.
- A native modal groups sorting, item filters and selling/availability filters.
  It becomes a bottom sheet on phones, with an independently scrolling body and
  reachable dismissal and confirmation controls. Its short entrance transition
  uses the existing motion controller and respects both motion preferences.
- Active filters have removable chips. Clearing filters preserves the chosen
  sort and grid/list layout. Server-side filtering, sorting, pagination and
  account guards remain authoritative.
- Changed assets receive the `review-20261103` cache version.

## Validation

The new regressions use synthetic items, photographs and accounts. They do not
submit customer photographs, approve live stock or publish a product.

- All 26 Node UI suites pass, including 70 inventory scenarios and six
  new Collection interaction groups.
- The existing inventory browser suite passes Chromium at 320, 390, 430 and
  1440 pixels, including guided listing, exact-copy actions, artwork, quantity
  confirmation and refresh recovery.
- `comic-listing-recovery.py` passes Chromium at 390 and 1440 pixels. It covers
  the recorded two-photo failure, identical retry bytes and UUID, retained
  preparation, current versions, lost-response reconciliation, save guards,
  account/item/identity isolation and actual authenticated raw-file requests
  under `connect-src 'self'`.
- The dedicated Collection browser suite checks the phone/desktop row layout,
  filter sheet, selected-view state, visible values, keyboard focus, viewport
  overflow and target sizes.
- Eighty-three focused backend checks and 20 PostgreSQL readiness cases pass.
  The existing shared-reference display, recommendation and account/journey
  browser suites also pass in Chromium (24, 24 and 29 cases respectively).
- Backend upload/readiness tests and the full exact-head CI results are recorded
  with the pull request. Chromium and WebKit CI are required before merge.

Synthetic visual review: [mobile list](ui/seller-hub-review-20261103/mobile-list.png),
[desktop list](ui/seller-hub-review-20261103/desktop-list.png),
[mobile filters](ui/seller-hub-review-20261103/mobile-filters.png), and
[recoverable photo upload](ui/seller-hub-review-20261103/mobile-photo-retry.png).

## Production boundary

Read-only diagnosis found that the reported comic still required genuine
identity/intake, physical-photo and shipping review. This change does not invent
those facts or approve the copy. The successful software release is not evidence
that this customer item has been published. Only the normal reviewed publication
path may establish that outcome.

Deployment uses the existing main-branch Railway pipeline after the exact pull
request head passes CI. Verify the deployed commit, readiness endpoint and
changed asset hashes before reporting the release as live.
