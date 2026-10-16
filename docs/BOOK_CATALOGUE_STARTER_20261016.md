# Starter comic and manga catalogue

Follow-up: [publisher cover artwork and market-price status](BOOK_ARTWORK_AND_PRICE_STATUS_20261017.md)
adds authenticated reference thumbnails for all 14 editions. The original seed
and its physical-copy/price restrictions below remain unchanged.

The user asked to add real comics and manga after the scanner release. The
reviewed manifest contains 14 English-language edition references, with publisher
pages and the release dates those pages give. This is a small curated import,
not an ongoing provider integration or a bulk refresh.

| Category | Entries |
| --- | --- |
| Manga | One Piece volumes 1–3; Naruto volumes 1–3; Dragon Ball Z volume 1; Hunter x Hunter volume 1; Jujutsu Kaisen volume 1; Death Note volume 1 |
| Comics | Absolute Batman (2024) issues 1–2; Absolute Superman (2024) issue 1; Ultimate Spider-Man (2024) issue 1 |

Sources: VIZ's individual paperback product pages, DC's individual comic pages,
and Marvel's Ultimate Spider-Man issue 112985 page. Exact URLs, ten validated
ISBN-13s and source-check dates are in
`backend/data/book_catalogue_starter_20261016.json`. Publisher retail prices are
not market values and were not imported. No descriptions were copied.

The existing `ComicPrintingCreate` and manual identity hash determine the product
fields. The seed is atomic and append-only: equivalent or changed existing
identities abort the operation, while a repeat of the identical seed adds zero.
It inserts only `catalogue_products`, `catalogue_product_profiles` and
`comic_printing_details`. It does not create physical inventory, media approvals,
prices, Shopify products, automation, schema or services.

Records are `STRUCTURED`, not `VERIFIED`. These sources establish the edition but
not a particular copy's printing number, cover variant, condition or grade. Those
fields stay unknown. The scanner/intake review and exact sold-evidence gates stay
in force. No first-printing or market-value claim is made.

Catalogue selection now passes available book details to the existing intake
form. The seller confirms their copy and explicitly saves. The catalogue seed
uses the same identity algorithm, so unchanged details reuse the reference rather
than creating a duplicate. Changed printings remain separate identities.

Publisher cover URLs are provenance only, with rights still pending. Browse
details link to the official publisher page to view the cover; the existing
approved canonical-media rules remain unchanged. No photo is generated, copied
into approved media or misrepresented as the seller's physical item.

Validation includes ISBN/source/identity checks, real PostgreSQL replay and
restricted-owner reads in the collection fixture, explicit form prefill without
physical/price defaults in Chromium/WebKit, and the existing full backend/UI
checks. Production import and release readback follow these checks.

Before this import, production had 0 books, 614 physical inventory copies and
50,378 retained reference-history rows. The sold provider's existing HTTP 429
pause lasts until 17 October 2026, 18:00 BST; this seed does not override it.
