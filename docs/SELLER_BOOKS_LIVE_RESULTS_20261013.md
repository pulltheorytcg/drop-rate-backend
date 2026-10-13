# Seller Hub comics and manga — live receipt, 13 October 2026

The owner Seller Hub now supports manual entry of Marvel, DC and other comics, graded comics, and manga. Open **Inventory → + Comic / manga**, or **Scan → Add a comic or manga**. Refresh an already-open Seller Hub tab to load the new form.

The form records series, issue or book/volume number, publisher, edition, format, language, and optional year, printing, cover, artist and ISBN/barcode. A raw copy has a book condition; a graded copy records its grading company, numerical grade and required certificate number. CGC, CBCS, PGX and a custom grading-company option are available. Cost, selling price and copy notes are optional.

Each addition is an unconfirmed `PERSONAL_COLLECTION` / `DRAFT` copy belonging to the authenticated owner. Seller-submitted catalogue identities require review. The existing confirmation and selling-review rules still apply. Duplicate graded certificates are rejected without disclosing another owner's stock. A retry after an uncertain save reuses the same request and cannot create an additional copy.

This release provides manual book entry, not automatic cover recognition, certificate authentication or comic/manga market pricing. A seller can enter a selling price; no unsupported book market value is generated.

## Production verification

- [PR #633](https://github.com/pulltheorytcg/drop-rate-backend/pull/633), merged code `dc3f8951ac4913af53aa1a0ad93c23f6bb5bea13`.
- Railway deployment `153c2c40-94f4-41ef-9c0a-87d50428f907`: **SUCCESS**.
- `/owner` and all four book/inventory/portal assets returned HTTP 200 and matched the committed files byte for byte.
- `/health/ready` returned `ready` with the database `connected`.
- An unauthenticated POST to `/api/v1/owner/books/intake` returned HTTP 401.
- Additive migration `seller_comics_manga` is applied in Supabase under version `20261013224334`. The canonical CLI-generated file is `database/migrations/20261013222139_seller_comics_manga.sql`; migration staging maps it to the applied version so it is not replayed.
- Existing stock before and after deployment: **614 items / 327 valued**. Ownership, Store Price and status fingerprint remained `692a601c4d0629871826cc9a3a031708`.

The 614-item baseline was measured before this release; an earlier pricing receipt had 613. No production book or physical copy was inserted for testing, and this release did not alter stock ownership, selling prices, statuses or publication.

## Validation scope

All nine applicable CI workflows passed. The local backend suite passed **5,776 tests**, and existing dashboard tests passed. Restricted-role PostgreSQL and signed-HTTP tests covered raw Marvel, graded CBCS and manga entry; owner isolation; shared reference identity with separate owned copies; edition separation; concurrent/changed-payload retries; duplicate certificates; invalid physical states; and attempts to self-verify catalogue identities.

Real Chromium and WebKit checks at 390 and 1440 px covered graded-book and manga forms, uncertain-save retry, post-save refresh failure and account switching. Browser tests used fixture API responses; authenticated intake tests used the isolated PostgreSQL fixture. Production checks verified deployment, database migration, assets and access protection without creating real stock.

The accompanying card-pricing repair is recorded separately in [the pricing recovery receipt](PRICING_RECOVERY_LIVE_RESULTS_20261013.md).
