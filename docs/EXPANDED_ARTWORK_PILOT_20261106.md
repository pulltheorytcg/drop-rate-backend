# Drop Rate — expanded catalogue artwork pilot (6 November 2026)

**State: source-candidate review code only. No artwork mirrored, approved, rendered or published.** Tracks #966. No new source credentials, paid providers, provider scans, DB writes, R2 uploads, Shopify edits, settlement changes or deployment flags.

## Why the cards are blank

The newer Yu-Gi-Oh!, Disney Lorcana and Magic catalogues were intentionally imported to private R2 as factual **metadata only**. The new source adapters discard third-party image URLs. The 66,218 source-verified R2 artwork objects belong to the original Pokémon / One Piece / Dragon Ball / Naruto reference library, not to the new games. The independent first-party **physical-copy** photography pipeline (including PSA/BGS/ACE slabs) remains required for listings and is not replaced by catalogue art.

Production checked 6 Nov (read-only): `tcg_private.r2_first_catalogue_publications` contains active English YGOPRODeck **45,418** rows, Lorcast **3,505**, and MTGJSON **153,662** stored / **151,613** released rows. Riftbound has **no active approved source**. This patch does not change that registry or these rows.

## What this pilot code adds

`backend/app/expanded_artwork_pilot.py` offers two **offline** pure review functions:

- `preview_yugioh(source_payload, published_rows)`: re-normalizes a bounded set of YGOPRODeck v7 source cards with the **existing** passcode+set+rarity hashed provider identity. Compares every identity field and the optional R2 stable key. Only a single card-level image ID matching the logical card's own ID and exact official HTTPS image host is eligible for **review**. Multiple alternate artworks, missing set, unknown images, wrong source, changed set/rarity or invalid URL are rejected/classified. Card-level art never proves a specific reprint or foil/alternate artwork.
- `preview_lorcana(source_bundle, published_rows)`: uses the **existing** Lorcast exact `crd_` printing ID, set and language normalizer. Only its explicitly supplied matching digital normal AVIF locator can enter **review**. Digital art may differ from physical collectible printings; matching IDs and permissions are separate gates.

Both methods accept **at most 25 published reference rows** and return reason-coded candidate records. They do no network I/O and do not return ownership, source market prices, or sensitive source fields. Every output is `PENDING_PUBLISHER_PERMISSION`, `image_byte_verified=false`, `printing_image_verified=false`, `can_mirror=false`, `can_publish=false`. Not one candidate can be handed to the existing display/Shopify resolver. A source image URL is merely a review lead, not a proven image or licence.

The pilot is deliberately **not** registered as a live worker, API route, image fallback or cron job. To run it against actual release records requires a trusted, offline source snapshot and a bounded 25-reference exact-ID read from the verified R2 generation; perform that in a separately scoped reviewed step, without changing the source permissions or copying image bytes first.

## Rights and sources to verify

1. **Yu-Gi-Oh!**: official YGOPRODeck v7 API docs: https://ygoprodeck.com/api-guide/ . It lists `card_images` separately from `card_sets` and requires users to download/rehost images **rather than hotlink**. API access and rehosting guidance do **not**, by themselves, prove Drop Rate has permission to commercially publish Konami artwork. Need applicable publisher/image rights evidence before fetching/mirroring bytes and before any customer-facing display.
2. **Lorcana**: https://lorcast.com/docs/api/cards and https://lorcast.com/docs/api . Its `image_uris.digital.normal` links exact Lorcast printing IDs, but Lorcast's public metadata access and community-code statement are not a commercial Disney/Ravensburger artwork licence. Record independently valid permission scope.
3. **Magic**: MTGJSON MIT facts are not a Wizards card-image licence. Choose independently permitted media source/usage and match exact UUID, set, collector, treatment/finish and face. No MTG artwork is processed by this pilot.
4. **Riftbound**: existing #902; Riot app/key approval remains a precondition. Sports/Funko/LEGO also remain metadata-only unless a separate approved source or original item photography is available.

## Failure points and testing

- Alternate YGO image not mapped to exact set: `ALTERNATE_ART_SET_MAPPING_UNKNOWN`, no thumbnail.
- Changed/duplicate provider ID, wrong set/rarity/variant, locale mismatch or stale R2 key: hard error or `SOURCE_IDENTITY_MISMATCH`.
- Image host/ID not precisely sourced (including query injection, HTTP, lookalike hosts): `UNTRUSTED_IMAGE_LOCATOR` or `NO_VERIFIED_PRINTING_IMAGE_LOCATOR`.
- Lorcast unknown art/photo or different `crd_` ID: no candidate.
- Any candidate: **rights review required** even if the provider URL looks correct. No source content or card photo automatically approved. No fallback to a different language, raw art for graded slab, or another owner's photograph.

`tests/test_expanded_artwork_pilot.py` runs these offline in CI without provider calls or credentials. After any later explicit rights clearance, a separate image mirroring stage must verify provider usage rights, exact source response, raster/AVIF decode, size/format, content SHA-256, R2 exact-byte readback, original edition artwork by human review, and a 25-image signed-in mobile/desktop grid acceptance, with a release-specific rollback pointer. No bulk job before that test succeeds.

## Rollback

Because this code is pure and disconnected, rollback is reverting its PR. No source generation, live price, physical ownership, Shopify products, inventory or R2 object is touched.
