# Full-slab Collection media and reviewed raw-card fallback — 7 November 2026

## What and why
Authenticated Founder HQ / Seller Hub Collection grid must show the **entire photographed slab** at its original aspect ratio, including grading label; the prior 90px × 126px thumbnail made genuine slab images difficult to see. Only graded cards get the taller image canvas. Raw, sealed, figures, books and list layout retain their current proportions.

When an exact slab photo is absent, a graded item can show a clearly labelled private **card-only reference**, without implying that the card artwork depicts the actual physical slab. The item, certificate, owner and status remain unchanged.

## Deterministic priority and eligibility
`inventory_reference_media.MEDIA_SQL` implements, in order:
1. APPROVED first-party, owner/inventory-bound `GRADED_SLAB` front photo.
2. APPROVED official PSA/ACE/BGS/CGC `GRADED_SLAB` image, private `INTERNAL_REFERENCE_ONLY`, exact owner/Inventory ID, provider/grader and certificate match in both `source_reference` and `provider_asset_id`.
3. APPROVED official PSA/ACE/BGS/CGC **raw-card photo** bound to the exact same certificate/owner/inventory, with existing `RAW_UNSLEEVED` context and `INTERNAL_REFERENCE_ONLY` rights.
4. **Exact canonical card artwork** of the approved printing (same language, variant, catalogue ID), only for `CARD` items with PSA/ACE/BGS/CGC, nonempty certificate length at least six, current status APPROVED/RESERVED/SOLD, `identity_confirmed=true`, `condition_review_status=VERIFIED_GRADED`, and a recorded staff condition reviewer.
5. No image where none qualifies.

Step 4 is a **staff-reviewed identity artwork fallback**, *not* evidence that the grader looked up or photographed this exact certificate. Do not call it a certificate photo. Never construct a synthetic slab, and never attach unrelated grade labels to artwork.

`graded_card_art_allowed` is derived within the private media SQL selector only; the owner Collection API does not need to expose a certificate number or identity-review fields. The Python response refuses canonical artwork unless the server-resolved candidate carries that eligibility flag. For official raw certificate photos, existing media-approval checks and exact provider+certificate matching are required; no new upload source is inferred and no media row is auto-approved.

## Live inventory example before rollout
Charizard V, Darkness Ablaze 019/189, PSA 9, certificate 62398872, has **no approved inventory-bound provider image**. Its physical identity was confirmed and staff reviewed, and the exact printing's approved English/Holofoil TCGdex artwork is in the catalogue. The updated read-only SQL selects this **matching card artwork**, labelled 'Card artwork · not slab photo', until a verifiable certificate-bound raw image or genuine slab photo is approved. Do not claim the shown fallback comes from PSA.

## Security and unchanged behaviour
- Both owner list and detail remain behind authenticated owner-scoped queries and RLS; no cross-owner media references.
- Never promote grader/canonical references into first-party images or change `media_resolver` public Shopify/eBay readiness. Channel-specific publication still requires the original eligible photo/media rights; frontend labels do not constitute permission.
- No database migrations or writes, no changes to ownership, settlement, inventory status, market value, or actual source assets.
- No scraping or automatic PSA data ingestion.

## Failure and release tests
- Python: missing/unapproved media, wrong grader, weak certificate, raw fallback vs slab precedence, staff-reviewed exact canonical eligibility, no unreviewed canonical borrowing.
- UI: actual slab vs official raw vs canonical artwork alt text, captions, mobile full-height `object-fit: contain`, cache-busted CSS/JS.
- Production read-only SQL: Charizard V 62398872 resolves to its matching canonical art and Mega Charizard X ex 160349012 continues resolving to its actual PSA front asset.
- PR CI (Python, JS, SQL fixtures), merge, production Railway deploy, owner and consignor signed-in visual checks. External account acceptance remains unverified until performed.
- Rollback by reverting this PR, restoring prior media selection and styling; no database rollback necessary.
