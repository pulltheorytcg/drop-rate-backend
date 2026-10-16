# Book artwork and market-price status

The user asked for artwork and market prices on the 14 starter editions. All 14
publisher covers have been retrieved and visually checked against their titles
and volume/issue numbers. The reviewed manifest records the exact catalogue UUID,
book identity digest, language, publisher page, image URL, check time and observed
image hash/dimensions. DC's same cover images use its 540px thumbnail parameter.
The Marvel cover was located through the publisher's indexed issue 112985 page.

Search cards and book details now use the existing authenticated thumbnail
transport. Book cover lookup resolves the exact stored catalogue identity and
requires matching language, release date, book fields and publisher provenance.
Changing a printing or cover, withdrawing the source, or marking the identity for
review removes that reference. Unapproved hosts, paths, credentials, ports and
redirects stay blocked. Existing concurrency, byte, image, cache and timeout bounds
apply. The database connection is released before fetching the public image.

These are labelled publisher reference covers. The seller's copy may differ.
Existing approved media takes priority; no media approval, rights claim, inventory
photo, Shopify publication or physical-copy identity is created. No images are
generated and no full-resolution images are added to the repository.

## Prices remain blocked

Production readback found 14 structured editions, zero verified printings and zero
physical book copies. The existing eBay/Trawl receipt remains HTTP 429, with its
next permitted check at **17 October 2026 17:00:42 UTC / 18:00:42 BST**. Recovery of
that provider alone will not price unknown printings. The existing exact book
pipeline still needs verified printing/cover identity, physical condition or
grade, and five eligible recent GBP sold comparisons.

PriceCharting was investigated, not integrated. Its public One Piece and Naruto
volume-one guides mix original Japanese publication years with English and other
printing sale titles. They cannot establish an exact English-edition value. Its
terms also require express permission to share price data through third-party
software. No subscription, provider permission, new integration or contact was
created. Publisher retail prices and asking listings are not sold-market values.

The catalogue now says **Market value pending**, identifies missing printing/cover
confirmation, and provides a direct eBay UK completed/sold search with edition
details. That link is for user comparison only: it does not fetch, import or
automatically accept any listing as evidence. Existing verified values retain
their original meaning. This release does **not** claim to deliver numeric book
market prices.

Sources checked 16 October 2026 UTC:
- [PriceCharting price-data acceptable use](https://www.pricecharting.com/page/terms-of-service)
- [One Piece volume-one guide](https://www.pricecharting.com/game/comic-books-one-piece/one-piece-vol-1-paperback-1997)
- [Naruto volume-one guide](https://www.pricecharting.com/game/comic-books-naruto/naruto-vol-1-paperback-2000)
- [Marvel issue 112985](https://www.marvel.com/comics/issue/112985/read)
- Per-edition VIZ/DC sources and cover receipts are in `backend/data/book_reference_covers_20261017.json`.

Validation covers exact edition/language matching, withdrawn and changed
identities, authenticated access, SSRF rejection, approved media priority,
price preservation, image rendering without an external browser URL, and
restricted-owner real-PostgreSQL catalogue readback. Both Seller Hub and Founder
load `catalogue-browser.js?v=21`.
