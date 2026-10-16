# Comics and manga — first-class catalogue and storefront sections, 16 October 2026

## Existing foundation (verified, do not rebuild)

Drop Rate already shipped on 13 October: `database/migrations/20261013222139_seller_comics_manga.sql`, `backend/app/owner_books.py`, `backend/app/comic_identity.py`, and `owner-books.js`. Signed account-bound `POST /api/v1/owner/books/intake` creates owner-specific **DRAFT / PERSONAL_COLLECTION** entries, including Marvel Comics, DC Comics, Other Comics and Manga with issue/volume, printing, language, optional cost, raw or CGC/BGS manga/CGC comic grade and mandatory certificate for graded. Existing duplicate-cert protection, consent and manual review stay in force. Supabase currently has **zero COMIC canonical product records and zero physical book copies**; no fictitious stock or market prices may be inserted.

## What this release adds

- One unified Seller Hub Search/Discover includes **COMICS** and **MANGA** as visually separate first-class category tiles, even with zero stock (explicitly displays `0 products` rather than disappearing).
- Existing `tcg.catalogue_products` rows of type `COMIC` join their independently reviewed `tcg.catalogue_product_profiles`, allowing genuine seller-entered book products to be browsed by franchise/series, title/issue/volume and language; no TCG source records are retyped and no synthetic book records are inserted.
- Backend appends stable zero-count `COMICS` and `MANGA` entries to `/api/v1/catalogue-browser/games`. The safe browse filter expands COMICS into `MARVEL_COMICS`, `DC_COMICS`, `OTHER_COMICS` without merging the original source identities. Manga retains its `MANGA` system.
- The book-specific `product_type=COMIC` browse mode cannot call the CARD or SEALED intake endpoint; it opens the already-built book form with separate printing validation. Empty category messages truthfully say books are not yet listed and offer a direct manual intake action.
- Two real Shopify **smart collections**, IDs `gid://shopify/Collection/684163105115` Comics and `gid://shopify/Collection/684163137883` Manga, handles `/collections/comics` and `/collections/manga`. Each is currently empty. Exact tags `Drop Rate:Comics` and `Drop Rate:Manga`, respectively, are reserved for future **verified and independently approved** book publication; manual book intake alone does **not** auto-publish a Shopify listing.
- Versioned GitHub **unpublished Brand Redesign theme** template includes the two collection tiles plus collection-route navigation; no live Horizon theme publication, new marketing artwork, paid APIs or fake inventory.

## Security, failure points and tests

- Book categories must never inherit trading-card market prices, TCG card identity, copy status, sample art or another seller's inventory. No `tcg.reference_market_prices` observations exist for these newly surfaced book systems; show price unavailable, never £0 or invented.
- A book is never added through `/api/v1/catalogue-browser/intake` (card-only validator); the existing owner-scoped book intake performs all validation and requires explicit physical condition/printing confirmation and idempotency.
- The full physical item still has unique inventory ID, owner, grade, storage and independent Store Price; no auto approving customer-submitted books, no seller isolation bypass.
- Shopify collections remain empty until published stock has accurate exact tag; no automated product synchronization for COMIC is activated by this release.
- Tests include backend book family and SQL-owner scope, real PostgreSQL owner-books intake regression, JSDOM dynamic book category and no-cards intake, exact unpublished theme JSON/route validation, and full backend/UI/CI. Release only after exact merged GitHub SHA Railway SUCCESS + readiness and Supabase inventory fingerprint and live Shopify collection readback.
- The Shopify theme overlay must be uploaded/rechecked to the **correct unpublished theme**, not blindly deployed onto Horizon. If theme file upload is unavailable through connected app, report GitHub prepared (not remotely active); never claim visible theme preview before verifying.

## Next development milestone

Build a separately reviewed deterministic **COMIC Shopify listing adapter** with source photo licensing/approval and exact printing + genre-specific book tags, in the existing FastAPI and Shopify webhook infrastructure. Book market valuations require licensed condition-/printing-/grade-aware evidence sources and tests; no scraping or arbitrary £1 market valuations.
