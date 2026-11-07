# DR107 — Three-game artwork coverage and exact-print source review

7 November 2026. This release is an audited, source-bound image-candidate pilot. It does not mirror, approve or publish unreviewed artwork.

## Production gap

Verified with read-only SQL against the active Supabase R2-first registry:

| Source | Game | Stored | Released | Linked current-generation refs | Approved listing media |
|---|---|---:|---:|---:|---:|
| YGOPRODeck | Yu-Gi-Oh | 45,418 | 45,418 | 0 | 0 |
| Lorcast | Disney Lorcana | 3,505 | 3,505 | 0 | 0 |
| MTGJSON | Magic | 153,662 | 151,613 | 0 | 0 |
| Total | | 202,585 | 200,536 | 0 | 0 |

The counts concern these new R2-first source generations, not the pre-existing Pokémon, One Piece or other artwork.

## Source selection

* Yu-Gi-Oh: https://ygoprodeck.com/api-guide/ is primary. It provides passcode-level image candidates but card_images does not prove exact printing, rarity, edition or alternate image mapping. Re-hosting guidance is not itself a publisher image licence. PublicAPI.dev and the API Evangelist GitHub entry are directories, not new independent artwork sources.
* Lorcana: https://lorcast.com/docs/api and https://lorcast.com/docs/api/images are primary. Store the specific crd_ printing ID and image timestamp/variant. https://lorcana-api.com/Home.html is a backup evidence source, not automatic Disney/Ravensburger image licensing. The Lorcast API is beta and asks for cache, throttle and respect for Community Code.
* Magic: MTGJSON stays canonical for physical printing identity; https://scryfall.com/ is the primary source of exact Scryfall image candidates. Only join original MTGJSON card.uuid, identifiers.scryfallId, source set, collector number, rarity, finish and language to the exact Scryfall printing. Scryfall recommends bulk for high-volume work and fewer than ten live requests per second. The older https://docs.magicthegathering.io/ API announces deprecation in March 2027. FreeAPIHub is an API index rather than a new source.

## Implementation

* GET /api/v1/artwork/coverage is admin-only and read-only. Counts only current active R2 manifest links and rights-VERIFIED, APPROVED, ACTIVE, unrevoked, Shopify READY canonical image records. Missing image candidates never count as approved artwork.
* GET /api/v1/artwork/sample/{YUGIOH|DISNEY_LORCANA|MAGIC_THE_GATHERING}?limit=25 returns exact source identities from the already-verified, current, private R2 snapshot cache. No new provider fetch, no owner data and no writes.
* Offline expanded_artwork_review_cli accepts yugioh, lorcana and magic source packs (up to 25 exact references). The Magic extension checks original MTGJSON crosswalk IDs, set, collector number, finish, paper status, Scryfall UUID and trusted image locator. Multiple-faced prints require additional review.
* All candidate records remain PENDING_PUBLISHER_PERMISSION; image bytes unverified; can_mirror=false and can_publish=false. This code never modifies physical inventory, ownership, prices, Shopify, eBay or Whatnot.

## Follow-on release gates

1. Establish documented commercial use rights for official full-card art, separately from API data access. Wizards WPN authorised retail marketing materials may be relevant where eligible.
2. Obtain reviewed original provider source samples and exact 25 released R2 printing IDs for each game.
3. Verify image raster bytes, resolution, checksum, correct set/card/printing/variant, and source rights; stage approved immutable copies in private R2 and read back hashes.
4. Materialise exact reference links and store approved canonical media with rights evidence, no silent source approval.
5. Verify a 25-print signed-in app and Shopify grid. Graded items require exact slab images; eBay used-card requirements stay separate. Then expand in bounded batches with rollback.

## Testing / release criteria

Run test_expanded_artwork_pilot.py, test_expanded_artwork_mtg.py, test_expanded_artwork_coverage.py, all existing backend, dashboard, n8n and safety CI. Production is not complete until live readback and media display are independently verified.
