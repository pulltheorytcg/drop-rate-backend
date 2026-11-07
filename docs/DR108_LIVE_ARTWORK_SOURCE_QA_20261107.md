# DR108 — Live five-by-five official image candidate review

7 November 2026 — Release candidate for actual source-image QA, not storefront publishing.

## Purpose and source of truth

The previous DR107 release added identity-only 25-record samples and offline source matching. DR108 adds real, on-demand API lookups for those **exact R2-snapshot card printings**, without requiring someone to assemble source JSON manually. Each founder/admin reviews five printings per click, up to 25 per game, from Founders dashboard → Official artwork review.

Authoritative input is the currently active verified R2-first snapshot from `r2_first_service.read`, pinned to `source_manifest_sha256`. No browser passes an image URL, card ID, storage key, seller ID or rights override.

## Live connections

| Game | Query | Identity checks | Missing permission state |
|---|---|---|---|
| Yu-Gi-Oh | YGOPRODeck v7 `cardsetsinfo.php?setcode=...` then `cardinfo.php?id=...` | Printed set code, set name, set rarity, passcode, exact hashed source printing/provider ID, single vs alternate art | Card-level candidate pending print and rights review; no multi-art inference |
| Disney Lorcana | Lorcast `v0/cards/{set}/{collector_number}` | Exact Lorcast `crd_` ID, set code/ID/name, collector, English, digital image URI version | Digital art pending physical printing and rights review |
| Magic: The Gathering | Scryfall `cards/{set}/{collector_number}` | Exact MTGJSON recorded set, number, name, rarity, finish, paper/English, Scryfall UUID and image host | Original MTGJSON `identifiers.scryfallId` crosswalk still required before canonical approval |

Five-record calls are serialised and paced at >=130 ms between source records; provider requests have explicit UA, accept header, HTTPS fixed base URLs, no redirects, 9-second per-request bound, 256 KB JSON cap and 4 MB image cap. Any HTTP 429 stops the batch rather than retrying or ignoring restrictions.

Optional `verify_bytes=true` downloads **only a trusted candidate URL** into transient RAM, checks content type, JPEG/AVIF decoding, dimensions >=200 pixels, max dimension 4096, computes SHA-256 and drops the bytes after the request. A successful byte hash does **not** grant reproduction/publishing rights or exact-printing proof.

## Read-only API and owner UI

Existing admin-guarded `GET /api/v1/artwork/pilot/{YUGIOH|DISNEY_LORCANA|MAGIC_THE_GATHERING}?limit=5&offset=0&verify_bytes=true` supports offsets 0,5,10,15,20, yielding the first 25 published R2 printings in stable name order. Founders dashboard displays candidate counts, byte verification and links to inspect originals. All candidates remain `PENDING_PUBLISHER_PERMISSION`, `can_mirror=false`, `can_publish=false`.

No R2 uploads, Supabase modifications, media approval, Shopify/eBay edits, image hotlink `<img>` elements, Whatnot work, watermark removal or ownership changes are triggered. Provider API access and copyright permissions are separate gates. YGOPRODeck explicitly warns against continued hotlinking; the UI links to source images rather than automatically loading 25 external thumbnails per session.

## Failures and tests

* Outdated source generation, malformed stable key, wrong card passcode/set/rarity, fake image URLs, multi-art/alternate variants and cross-game references → refused.
* Lorcast exact set/card mismatch → refused; untrusted AVIF URI/version → refused.
* Magic wrong finish, rarity, number, set, language, paper status, forged Scryfall host or multiface → refused.
* Missing or blocked provider, 429, bad JSON/mime or damaged/oversized raster → per-card failure receipt, never silent success.
* Owner not active platform admin → route blocked by existing `require_platform_admin_request` router dependency.
* Original scan and graded slab photos never substituted by provider artwork.

CI: `tests/test_expanded_artwork_live_pilot.py`, `tests/test_expanded_artwork_live_api.py` plus existing DR107 and full backend/dashboard/n8n/RLS suites. Deployment requires merge then successful Railway API health. Actual provider response availability and first 25 visual matches must still be checked as authenticated founder; mock-based CI proves rules, not live provider availability.

## Follow-on true image release

1. Run all five 5-print slices for each game against live provider API and record candidate+SHA receipts. Fix any provider-specific API drift (no source URL substitution).
2. Approve exact print/variant/language, image cleanliness and applicable commercial use. Data-source licences are not automatically publisher image licences.
3. In a **separate explicitly gated** process, mirror approved immutable image bytes to private Cloudflare R2 with verified SHA readback, insert exact generation-pinned source→canonical links and `tcg.media_assets` approval evidence.
4. Verify actual app and Shopify images and graded slabs on signed-in desktop/mobile before increasing batches. Whatnot remains a future adapter.

**DR108 creates the operational live-source QA gate. It does not yet make the new card artwork appear in storefront listings.**