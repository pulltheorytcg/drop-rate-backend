# DR108 — Live image candidate check for Yu-Gi-Oh!, Lorcana and Magic

**7 November 2026. Release scope: real provider API lookups, bounded raster-byte verification, and founder-only preview.** This is a diagnostic/QA stage. It never approves use rights, mirrors image objects, publishes media, or changes card and inventory records.

## What it builds and why

The previously merged DR107 release could sample precise live R2 metadata and compare against **locally supplied** source JSON, but it did not run live image checks itself. DR108 connects five verified R2 printings per request to explicitly fixed provider endpoints. Founders can review up to 25 per game across five batches in **Founders dashboard → Official artwork review**.

- `YUGIOH`: YGOPRODeck `cardsetsinfo.php?setcode=<exact printed set code>`, then `cardinfo.php?id=<confirmed passcode>`. Validate code, set name and rarity against the exact existing R2 reference. A card's one full-size artwork can be a candidate, but card-level art alone does not prove edition-specific artwork.
- `DISNEY_LORCANA`: Lorcast `/v0/cards/<set>/<collector_number>`, validate `crd_` ID, set, print details and the direct digital-image URL. Lorcast asks for 50–100 ms between API calls and 24-hour caching for bulk uses; this five-at-a-time pilot is intentionally much smaller than an ingest.
- `MAGIC_THE_GATHERING`: Scryfall `/cards/<set>/<collector_number>` using the exact MTGJSON source set/number. Validate paper English, name, set, rarity and finish; only allow an exact Scryfall UUID-based front JPEG. **Do not treat a matched set/card number as the original MTGJSON `identifiers.scryfallId` crosswalk**. This remains an explicit blocker, as do multiface cards and publisher rights.

All three use HTTPS-only fixed source domains, validated encoded identifiers, bounded streamed responses with no redirects, a maximum 5 rows per request, sequential provider calls with delay, and optional original JPEG/AVIF binary readback. The binary check uses Pillow for image format/dimensions and outputs SHA-256, byte count and dimensions. No original bytes are returned to the browser; the UI offers a link for an operator to inspect the source.

## How it connects

Authenticated R2 source snapshot (from DR107) → selected immutable source manifest SHA → five exact source keys → provider-specific live metadata lookup → optional raster-byte verification → **candidate-only receipt** → founder-owned review UI → future separately approved R2 staging/media attachment.

New endpoint: `GET /api/v1/artwork/pilot/{YUGIOH|DISNEY_LORCANA|MAGIC_THE_GATHERING}?limit=5&offset=0&verify_bytes=true`. It is mounted under existing `require_platform_admin_request` authorization. Requests are limited to offsets within the first 25 source records. The original read-only `/api/v1/artwork/coverage` reports zero approved images until actual reviewed canonical art has been linked.

## Failure modes and checks

Incorrect set/code/finish/language/card ID, duplicate IDs, source permission failure, HTTP 429, HTTP redirects or invalid types, unsupported AVIF decode, wrong dimensions, oversize image or absent image → deterministic failure record, not silent image fallback. Cross-owner access is blocked by the existing admin-only route and source-published exact identity. An image URL existing or a verified file hash **does not** grant commercial use of image intellectual property.

Tests: `tests/test_expanded_artwork_live_pilot.py` (YGO/Lorcast/Scryfall mocked real endpoint responses, no network, wrong IDs, invalid URLs, 429, 5-row cap, SHA/raster) and `tests/test_expanded_artwork_live_api.py` (admin mount, read-only request, bounds, UI safety) plus full backend/dashboard/n8n and R2-first safety CI. **No repository merge before passing tests.**

## Remaining work for actual storefront coverage

1. Prove real live endpoint reachability and approved access for artwork, with a human visual review of 25 exact rows per source; report acceptance percentages rather than counting URL leads as coverage.
2. Resolve exact alternate print art (YGOPRODeck card artwork is not necessarily an edition image), multiface Magic and digital-versus-print Lorcana.
3. Review provider/publisher permissions, then fetch authorised imagery into private content-addressed EU R2. Validate SHA, dimensions and bytes on readback and retain provenance/source version and approval events.
4. Materialise exact R2 source-to-canonical links (currently zero), create and approve canonical media only for printings with matching image rights, and verify Drop Rate and Shopify displays. Keep eBay actual-item used-card requirements and graded slab photo matching.
5. Scale in bounded batches with rollback and exceptions. Do not remove `SAMPLE` or other notices.

The release doesn't claim that the missing 200,536 catalogue thumbnails have been delivered. It gives a real way to check source images before authorising that step.
