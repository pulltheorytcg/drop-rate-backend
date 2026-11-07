# Masters paired leader-face reference prices — 13 October 2026

## Problem and source proof

The official Masters checklist stores both faces of leader cards separately. The ordinary matcher correctly rejects repeated collector numbers, but that also leaves a verified two-sided card without a guide when Cardmarket names both faces together.

For example, the official records `428020:BT20-023.png` (Android 18) and `428020:BT20-023_b.png` (Android 18, Impenetrable Rushdown) share collector number BT20-023 and LEADER card type. Both official images were downloaded and visually inspected from `https://www.dbs-cardgame.com/images/cardlist/cardimg/`; the first shows the Leader Front and Awaken instruction, and the second shows its awakened face. Cardmarket product **697740**, expansion **5272**, names the exact pair `Android 18 // Android 18, Impenetrable Rushdown`. Independent English Power Absorbed booster packaging confirms the expansion.

The existing `evidence.face` field currently labels both example records front. This recovery does not use that field as identity evidence or modify it: exact official image/file pairs, LEADER metadata and both complete source names must agree.

## Narrow matching and values

- English Bandai Official Masters only, two records with identical collector number, rarity and release; canonical BT/SD/EX number and exact `.png` / `_b.png` identities.
- Both records must declare LEADER and OFFICIAL_CHECKLIST, and their image URLs must equal the exact official file URLs.
- Every official printing participates in name/number ambiguity checks. A third face, parallel, prerelease or reused name blocks the pair. Neither member is selected by price availability.
- One independently confirmed base release and one Cardmarket singles product must contain both complete face names in the correct order with one ` // ` separator. Duplicate/unpriced products, conflicting releases and source-product reuse block recovery.
- Adapter disagreements reject both faces. Both records carry their original reference identity, the pair IDs and the selected face in quote provenance.
- Prices retain the original dated Cardmarket fields and ECB conversion. Match basis `EXACT_MASTERS_OFFICIAL_LEADER_FACE_PAIR_REFERENCE` and `physical_valuation_eligible=false` prevent these guides from valuing physical stock.

No owner, seller Store Price, status, Shopify, subscription, service, schema or secret changes. Existing reference worker revision **18** refreshes the current cache; history remains append-only.

## Replay and acceptance

The current public source export matched **344 face records**, with positive trends for **314 previously unpriced records**, representing **157 two-sided cards**. Read-only live checks confirmed the required LEADER/OFFICIAL_CHECKLIST and exact image URL metadata for all 314 candidates. They are 314 database reference rows, not 314 new physical cards. Actual gain must be read back after deployment; source changes, conflicts or unavailable quotes can reduce it.

Tests cover real paired identity, reversed order, missing/extra faces, same-name alternate printings, wrong collector number/file/image, provider/game/language/release/rarity/card-type drift, duplicate/unpriced products, wrong source labels/categories/IDs, source reuse, whole-pair conflict handling, database persistence and exclusion from physical valuation. Full backend suite: **5,750 passed** (one existing dependency deprecation warning). Full CI, deployment readiness and a completed revision-18 receipt remain required.

Baseline after revision 17: **38,684/69,538** priced reference rows; **28,374/67,058** physical references missing; **2,480** digital Pocket records N/A. Physical inventory **613**, valued **327**, ownership/Store Price/status fingerprint `820fee0063fe48d9e4a774b4b9f98301`.

Rollback: revert this matcher integration and importer revision together; the existing successful refresh clears unsupported current reference guides without editing historical evidence. Do not manually rewrite history or fill missing values with zero.

## Verified production result

PR #631 merged as `9a7096e498c59019bdd2a57c750a46a7655eac1c` after all four applicable CI workflows passed. Railway deployment `3904737b-3d75-463d-b3b4-1f238a52cc13` succeeded. Revision 18 completed at **2026-10-13 18:06:15.952883 UTC**, with zero provider failures and zero conflicting leader pairs.

Actual recovery is **344 priced face records**, representing **172 paired source products**. The normal-trend replay's 314 candidates were conservative: 30 further records had eligible foil-field prices. All 344 quote records are explicitly excluded from physical stock valuation and retain the original 12 October source timestamp.

Independent coverage readback confirms **39,028/69,538** priced references, net gain **344** over revision 17 and **5,056** over the session baseline. Physical inventory remains **613 / 327 valued**, and owner/Store Price/status fingerprint is unchanged. Remaining physical pricing gap: **28,030**. Full per-game source requirements are in docs/PRICING_RECOVERY_LIVE_RESULTS_20261013.md.
