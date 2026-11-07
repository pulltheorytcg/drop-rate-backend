# A collection-first add flow

The founder asked for the Collectr-like route: scan/search → check the item → add.
Condition, cost, sale price and channel setup should not block owning an item.
The Phase 2 manual was reviewed; this is the explicitly requested simplification
of the existing Seller Hub, with no storefront theme publication or new service.

## Changes

- Home shows collection count/value, recent additions and price insights. Existing
  payout, selling-price and listing-progress panels move to More → Selling.
- The primary Inventory destination is labelled Collection. Personal copies show
  In collection; internal DRAFT/INSPECTION terms do not headline these items.
- Search accepts a single explicit Add to collection action. Unknown raw condition
  remains null; quantity defaults to one. Optional details are collapsed. The
  same exact reference/language is still read server-side. Sealed items require
  sealed confirmation in the Add explanation and an explicit language if unknown.
- Scan uses the same Add wording; optional raw-copy details are collapsed. Slab
  label requirements remain visible. Unknown batch values do not appear as £0.
- Book copy details are optional; no selling-price field appears during collection
  entry. A catalogue book carries its publisher-cover preview into confirmation,
  with already-filled metadata collapsed. Editing identity removes that preview.
- Item details lead with the picture, identity, market value and quantity. Selling
  and detailed specifications are separate disclosures. Price evidence/source age
  remain available; a reference guide is never recast as an exact sold value.
- Every save retains immutable retry payloads and idempotency keys. Admission
  remains DRAFT + PERSONAL_COLLECTION, with no automatic identity/media approval,
  pricing recalculation, publication, ownership reassignment or financial action.

## Current artwork and price evidence

Read-only Supabase audit, 17 October 2026:

| Gap | Evidence |
| --- | --- |
| Pokémon missing image URLs | 10,904: Japanese 9,124; English 1,780 |
| Other existing card feeds missing URLs | 0 (URL presence does not prove every image loads) |
| Supported physical-card values/guides | 40,443 / 67,060 (60.31%) |
| No permitted exact data source | 13,064 physical references |
| Unresolved provider mappings | 9,358 physical references |
| No eligible exact quote | 4,167 physical references |
| US context only | 28 physical references |
| Database size/history | 405,662,867 bytes; 50,378 retained history rows |

Coverage uses the application's complete COVERAGE_SQL, including mixed-language
labelled guides and excluding 2,480 digital Pocket references. It is not an eBay
last-sale coverage count. A raw count of reference_market_prices expiry is not the
application's source-age/identity-qualified coverage calculation.

Public source readback: TCGdex `/v2/en/sets/swsh4.5sv` returned all 122 entries
with no image fields; Japanese `/v2/ja/cards/S8b-001` also returned no image.
Consequently these gaps cannot be repaired by retrying the current image URL.
The opt-in `pokemon_artwork_probe.py` checks the existing CardTrader connection
for up to two Shining Fates releases (at most four API calls, 45 seconds). It
outputs public blueprint identity/artwork only and never writes to the database.
It does not approve a replacement, invent a URL or claim all Pokémon art fixed.

Bulk market ingestion remains behind the existing 400 MB guard. The separate,
previously authorised history archive must be completely restored and verified
against the correct private Drive account before reclamation. No history deletion,
capacity bypass, new paid source or eBay cooldown retry is part of this UI change.
The source-data work is outstanding; this release must not be reported as complete
artwork/market-price coverage.

## Verification and release

Local full Python and DOM checks, then the six existing PR workflows. Added a real
PostgreSQL/signed-HTTP browse-intake test covering optional condition, server-read
identity, cross-owner retry refusal, concurrent duplicate prevention and sealed
boundaries. Chromium/WebKit exercise the actual HTML/CSS/scripts at 320, 390 and
1440 pixels: one Add action, hidden optional controls, separate selling, image
rendering and lost-response retry. Existing scanner, book, import and selling
regressions remain gates. All browser/API accounts and writes are synthetic.

Final commit, CI runs, screenshots, deployment and live byte hashes will be recorded
in the release PR. Physical-phone/new-user timing remains to be measured; this
release does not claim an observed novice speed or universal recognition accuracy.
Rollback: redeploy prior main 4d2560056358559f99bf00dc3c214e0d91ec9d04 / successful
Railway deployment 5a2c838a-becd-40f3-bb29-42d10ff75471. No schema rollback required.
