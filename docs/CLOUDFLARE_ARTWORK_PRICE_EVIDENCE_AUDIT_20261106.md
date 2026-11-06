# Drop Rate — actual image bytes, inventory photos and sold-evidence audit
**6 November 2026, read-only source counts checked around 20:26–20:43 GMT.**
These figures are source aggregates, not proofs that every linked file is fit to publish.

## 1. Verified R2 bytes vs. mere mirror metadata

- Real one-shot private Railway run `e27e8689-26cd-4bb6-bee0-329cabe0fd72` finished at **20:35:42 GMT**. It downloaded and SHA-256 / byte-size / WebP checked **481 of 481** selected R2 objects: **all 401 `tcg.media_object_mirrors` entries** and **80 reference artwork samples** (20 each from the four currently approved providers).
- Zero mismatches or missing objects in that exact checked scope. Private verified receipt SHA256: `e805b45c73fa68f99648edd9a448aeb18f5984b50d4e1797b830b700d27b5046`.
- The **401 media-object mirrors are approved canonical/catalogue media**, not 401 inventoried, individually photographed copies. Source code `backend/app/r2_media.py` intentionally refuses to mirror seller/private scans in that path. Do not call them `physical-copy photographs` or infer that product-specific slab images exist.
- Reference mirror source has **66,218** entries marked `VERIFIED`, 4 in `RETRY`, with 5,738,634,354 recorded bytes (~5.74 GB decimal). A `VERIFIED` metadata status is not R2 byte-level evidence. Full-scope byte audit PR #953 was merged after tests; live full R2 job must separately finish with a full readback receipt before claiming all 66,218 bytes verified.
- Image sources in the reference index: TCGdex 33,448; Punk Records 8,480; Bandai Official 17,124; Naruto Card Game Archive 7,166. Original provider reproduction/Shopify publication rights remain distinct from byte integrity.

## 2. The inventory-image gap is real

Read-only live PostgreSQL cross-checks:
- **621** individual physical inventory items, including **12** graded items.
- `tcg.media_assets` has **50** media records explicitly attached to **43** distinct inventory IDs; **48** of these records are `OFFICIAL_PROVIDER` and **2** `CONSIGNOR_UPLOAD`. Thus an inventory attachment is **not automatically a photograph of the actual copy**.
- `tcg.media_object_mirrors` currently matches **0** of those 43 inventory-linked asset records; **0/621 inventory items** have an inventory-linked verified R2 mirror; **0/12 graded items** have one. This does not prove that *no* image is visible on Shopify: **13** inventory media records carry Shopify file IDs and CDN URLs, but R2 has no inventory-specific mirror proof for them.
- `backend/app/inventory_reference_media.py` already contains a deterministic guard that a graded item needs `scope=INVENTORY_ITEM` and `capture_context=GRADED_SLAB`; generic raw-card artwork must never silently become the slab image. The separate Shopify/media selection and scanner-photo handoff need end-to-end tests, not assumptions.
- **Do not populate missing physical photos by copying a raw card/reference image**. Request a real photo/review when required.

**Engineering path, not yet implemented:** keep approved canonical R2 mirrors separate from owner-controlled private FIRST_PARTY_CAPTURE media. For owner photos: authenticated, owner/consignor-scoped upload; exact inventory version, side and grading capture-context checks; private content-addressed R2 bytes; separate original-upload and transformed-WebP hashes; deterministic `media_assets` / R2 linkage; staff approval; no storefront listing before policy passes; replay-safe retries and no wrong-owner writes. Source already has Shopify upload receipt + staff review workflows. Extending those flows requires tests for failed Shopify/R2 storage, role isolation, slab vs raw fallback, upload replays, and deletion/revocation.

## 3. Actual UK Market Value source evidence

Read-only PostgreSQL counts at ~20:26 GMT:
- `tcg.market_observations`: **6,241** records: **1,083 `EBAY` `SOLD`**, all marked GB / GBP (1,052 ungraded, 31 PSA); **5,158 `CARDMARKET` `PRICE_GUIDE`**.
- Only **1,040** of the GB eBay `SOLD` observations have positive GBP value and an observed timestamp inside the last 90 days, spanning **145 distinct catalogue product IDs**. This is a *candidate* pricing evidence count, **not** 1,040 independently verified, licensed, distinct finished sales or 145 eligible final Market Values.
- Existing `reference_market_prices` non-null records: 32,514; `reference_catalogue_prices` non-null records: 23,331. Those fields are **not evidence of verified recent sale price**; do not promote their mere presence to Market Value coverage.
- Evidence source permission, source IDs, exact printing/grade/condition/language, sale-vs-listing semantics, shipping/FX and outlier filtering must be verified before deterministic FastAPI pricing and publication.
- A separate **private Market Value D1 schema** was provisioned at protected-main run 42285658009; it did **not** publish prices, create a live pointer, or turn guides/RRP/asks into eligible Market Values.

## Acceptance gates before a live switch

1. Owner-specific **real scan images**, consent and Shopify/media processing tests; graded slab receives only the exact photographed slab. A source image missing in R2 triggers Action Required, never image substitution.
2. All R2 source bytes independently sampled or fully verified by scope. Ownership/finance private 10/11 table backup stays **partial** until all six owner memberships have a separate approved archive, even though all six are already in exact-parity private D1.
3. Robust lawful sold-evidence pricing, immutable history and all catalogue/category coverage, with missing values explicitly missing rather than unverified guides.
4. Replacement authentication, owner isolation, transactional orders/settlements and refunds, live delta replay, source-vs-D1 reconciliation and rehearsed rollback.
5. No Supabase/Shopify live cutover, no RLS relaxation, no automatic payment movement, no paid upgrade without explicit cost approval.
