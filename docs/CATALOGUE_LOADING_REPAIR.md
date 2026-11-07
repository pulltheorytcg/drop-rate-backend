# Catalogue loading and values — 9 October 2026

Live proxy logs showed catalogue requests at 122–452 ms and warm artwork at
99–114 ms. These are server durations, not measured phone end-to-end times.

The browser was sending the market refresh body as a JavaScript object instead
of JSON. Both hub request helpers forward bodies directly to `fetch`, so the
request could not pass the API's JSON validation. The catalogue now serializes
the body; coverage and source gates in the pricing engine are unchanged.

Known restricted One Piece images go straight through the existing authenticated
exact-reference route. Only nearby thumbnails are requested where Intersection
Observer is available. A bounded session cache retains at most 128 images / 16 MB
for up to an hour; navigating revokes old object URLs, and account teardown clears
all bytes. No tokens, ownership data or prices are persisted in browser storage.

The last 12 catalogue responses can render immediately for 60 seconds while the
same owner revalidates them. Inventory additions invalidate the cache; logout
destroys it. Failed revalidation explicitly identifies recently loaded results.
First visits still depend on network latency; this is not an instant-load claim.

Sets without a specific logo can display a labelled card preview from the exact
provider, system, set and language. The paginated query resolves a preview only
for the selected page. It cannot approve media or turn that artwork into product
packaging. Broken curated logos can fall back to the same preview.

Cards / Sealed products are now visible navigation controls. Choosing a product
type clears an incompatible card-checklist scope, while respecting game and
language. The existing database contains only three sealed product identities;
this UI repair does not claim a complete sealed-product catalogue.

Validation includes full backend and UI suites, regression cases for serialized
price requests, cached navigation revalidation, image reuse/account cleanup and
sealed navigation scope. Read-only live SQL returned 41 Japanese One Piece sets,
31 with exact-set card previews. Current-head CI and post-deploy browser evidence
are release gates. Rollback is application-only; no schema or inventory writes.
