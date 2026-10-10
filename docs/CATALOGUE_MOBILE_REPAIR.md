# Catalogue mobile repair — 10 October 2026

## Reproduction and causes

Reviewed both supplied iPhone recordings (00:41:48 and 00:47:55 BST). The second searches for `Eb04-007` and `Eb04 007`; only the Japanese Zoro appears. The first scrolls through One Piece, Pokémon and Dragon Ball with slow artwork and missing prices.

Railway HTTP logs for 9 October 23:40–23:49 UTC provide the corresponding server evidence:

| Route | Successful requests | Median | 95th percentile | Other evidence |
|---|---:|---:|---:|---|
| Catalogue products | 34 | 297 ms | 855 ms | 7 cancelled requests |
| Reference image | 141 | 1,728 ms | 1,790 ms | 20 cancelled requests; groups of four cold downloads |
| Catalogue games | 1 | 4,436 ms | — | Existing immediate game tiles do not wait for this request |

The browser replaced the entire image grid on pagination and unchanged cache revalidation. The image proxy created a new HTTP client for every download, sent full-size PNGs and queued cache hits behind cold requests. Pokémon browse grids used `high.webp` despite the provider's smaller asset.

The official English One Piece importer contained only OP-16. Its parser also rejected promo numbers such as `P-084`. The community feed lacks OP-15/OP-17; production had only the two Japanese EB04-007 references. Broad search treated `EB04 007` as independent terms and could return OP14-007 because its set name contains EB04. Rarity was absent from name searches.

Values are a separate data-coverage problem. The completed Pokémon reference fill has 11,910 English and 9,440 Japanese priced references. The recorded Alolan Exeggutor `30th-002` detail response has no Cardmarket or TCGplayer prices or marketplace IDs. No One Piece/Dragon Ball reference rows had quotes. Physical stock remains a separate 251/510 valued copies; the recording shows a different, one-item seller account. These figures must not be confused.

## Changes

- Pagination appends rows and unchanged revalidation preserves rendered cards. Existing artwork stays attached while later pages load; account logout still destroys session caches and cancels work.
- Grid images use 384-pixel WebP thumbnails behind the same authenticated, exact-reference route. Detail/scanner images retain their originals. Thumbnails have a 32 MB / 1,024-entry cap, TTL and shared in-flight requests. Downloads reuse one bounded HTTP pool; simultaneous misses are limited to six, with at most 64 pending distinct jobs. Cache hits bypass that queue. Redirect, host, MIME, size and decode checks remain enforced.
- Pokémon browse images prefer the exact `low.webp` with the original as fallback. Images are decoded asynchronously; near-viewport prefetch extends to 640 pixels.
- Official One Piece discovery reads released booster dates from the paginated publisher product index and exact printing counts from its card lists. It complements the older community index from OP-15 onward. Future releases stay hidden until their release date. All discovered lists are checked before any is saved, including cross-release printing collisions. Existing OP-16 identity text is preserved. Import revision 2 triggers a pass on deployment.
- Complete Bandai collector-number queries require the exact normalized number. Ordinary text search remains literal and includes rarity, enabling `Zoro SP`.
- The daily reference-price pass adds first-party Cardmarket One Piece singles and packaging exports. Release names/codes establish an unambiguous expansion ID; the collector number must have one printing in each checklist and the names must agree. It never chooses a parallel by price, list position or guessed version suffix. Conflicting names sharing a number also block the match.
- New quotes are labelled Cardmarket references, with source IDs/time, original EUR, ECB GBP conversion and mixed-language/condition limitations. Writes and reads check the current reference identity; stale work cannot attach an old guide to a changed card. These quotes do not update physical inventory, sold observations, seller asking prices or publication eligibility. Reference job revision 3 runs after imports and daily thereafter.
- UI distinguishes an actual price check, a temporary failure and unavailable evidence. It no longer displays permanent source gaps as an endless pending operation.

## Verification before release

The live publisher responses parse 520 separate printings: OP-15/EB04 196, OP-16 155, OP-17 169. OP-17 contains English `EB04-007_p2`, rarity `SP CARD`, with the black/red Zoro art shown in the recording. There are no cross-set printing-ID collisions in these responses.

The 9 October Cardmarket exports give 316 unambiguous matches for that scope. Zoro SP maps to product **904150**, expansion **6492**. Product 904797 belongs to the separate Asia-region expansion 6723 and is excluded. This is a source dry run, not a claim that production has been refreshed yet.

Local original-to-grid byte checks:

| Image | Original PNG | Grid WebP | Reduction |
|---|---:|---:|---:|
| EB04-007_p2 | 328,550 | 93,602 | 71.5% |
| OP17-002 | 243,874 | 43,526 | 82.2% |
| OP17-003 | 280,218 | 52,886 | 81.1% |

Both Zoro and Atmos thumbnails were visually inspected. Local warm-pool upstream downloads for the latter two took 200/196 ms; the first cold request took 8,028 ms. Cached thumbnail lookup was below 0.01 ms. These are isolated source measurements, not deployed end-to-end iPhone timings; the first visit still depends on the upstream host and connection.

Regression coverage includes 2,048 generated combinations of collector numbers, releases, regional products, parallel and conflicting-name collisions. This found and fixed a conflict that ordinary fixtures missed. Additional tests cover shared-request cancellation, queue/cache bounds, unsafe redirects, smaller-image fallback, stable pagination nodes, unchanged revalidation, session cleanup, reference identity races, exact-number searches and real PostgreSQL persistence under the API role. Full backend/UI suites passed locally; current-head CI and production read-back remain release gates.

## Remaining limits

This does not establish universal market coverage. Dragon Ball/Naruto and older One Piece references still need verified provider mappings. Ambiguous One Piece parallels and source products without a current quote remain unavailable. Pokémon's latest set cannot receive an invented price when its source has none. Physical inventory estimates and five-sale UK sold valuations retain their existing rules and provider-capacity limits.

No new service, paid provider plan, schema migration, Shopify theme publication or eBay listing is part of this repair. Brand Redesign remains the unpublished theme. No new signed-in iPhone acceptance is claimed before a real post-release check.

## Primary source URLs

- https://en.onepiece-cardgame.com/products/
- https://en.onepiece-cardgame.com/cardlist/?series=569115
- https://en.onepiece-cardgame.com/cardlist/?series=569116
- https://en.onepiece-cardgame.com/cardlist/?series=569117
- https://en.onepiece-cardgame.com/products/boosters/op17/
- https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_18.json
- https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_18.json
- https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_18.json
- https://api.tcgdex.net/v2/en/cards/30th-002
