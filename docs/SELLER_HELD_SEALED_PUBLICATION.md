# Seller-held sealed publication — 10 October 2026

The seller confirmed two Japanese OP-17 booster packs, their saved £10 price and reuse of the exact Seller Hub catalogue image. The earlier seller controls incorrectly carried warehouse intake requirements into this self-held consignment flow. This request changes that workflow; it does not authorize the Brand Redesign launch or other sellers' stock.

## Behavior

- A consignor can explicitly approve an intact SEALED product with a verified catalogue identity, matching language and no raw-card/slab attributes. The owner-scoped, version-checked action records identity-bound approval provenance and queues the existing automatic publisher.
- Approved canonical product media can represent an intact verified sealed product. Exact catalogue, language and variant, source status, rights/approval and Shopify file readiness still apply. Reference-only images are not automatically promoted.
- Physical cost and warehouse location remain unknown for seller-held stock. Each copy retains its exact Inventory ID and owner. Draft, personal, sold, reserved and withdrawn guards, retries and channel withdrawal remain intact.
- Shopify omits an unknown purchase cost. The immutable sale snapshot may retain NULL cost only for explicitly approved, exact seller-held sealed consignment. A database insert trigger enforces that exception. Commission, fees, net proceeds and payout balances are unchanged; cost/profit displays remain unknown until supported, rather than fabricating zero cost.
- Existing separately tracked Shopify listings and copy-group metadata are retained. This change does not introduce sealed pooling or alter allocation priority.

## Verification

Local full backend suite: 5,050 passing cases. Seller inventory UI: 24 scenarios. The restricted-role PostgreSQL gate executes both migrations twice, ownership isolation, concurrent copy receipts, approval transitions, NULL-cost restrictions and actual finance aggregate SQL with mixed known/unknown and returned costs. Chromium fixtures cover phone and desktop layouts. Exact-head CI, migration application, deployment and live publication are pending at this checkpoint.

The original record is `INV-D715B0E9B3C4451BA9095FA233F8A0E5`, owner `cba99d5c-fedf-4544-86aa-ab9a2785860f`, catalogue `24393ecd-59f6-4561-a7c4-971bb3482f2d`. At the original checkpoint it was one physical copy at version 5, Inspection/For Sale, price 1000p. No acquisition cost or Drop Rate storage location is inferred.

The exact [official Japanese pack image](https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp) was uploaded to the verified Drop Rate store as `gid://shopify/MediaImage/58904403149147` and read back READY. Image readiness alone is not a successful sync.

## Resumed approval and production evidence

The user requested the expired action again. PR #571 merged as `5759a8b4a7b28ba68f6f3045a0570421d943e628`; all five exact-head CI gates passed. Migration `20261010145452_seller_held_sealed_publication` is applied. Railway deployment `80f7bf34-ee2d-4c9f-9cb0-c308828b9e1f` reached SUCCESS at 14:56:11 UTC, with 5,050 pre-deploy backend tests passing and readiness 200. Live owner.html and owner-inventory.js match the release.

- The original copy is version 6, APPROVED / FOR_SALE at 1000p. Exactly one additional copy was added: `55fe97fc-7bfa-4a73-a269-664ec56d3004`, version 2 with the same approval/price. Both retain NULL cost and warehouse location. Receipt `e3d61f0a-f959-439b-9aac-373e12bd6574` prevents a duplicate addition. The operation used the existing connected PostgreSQL administration role, with exact owner/identity/version/count preconditions and normal audit triggers; an attempted switch to the runtime role was rejected before any stock write.
- Canonical product media is registered under this seller's owner scope, with the exact Japanese language/variant and the user's explicit catalogue-image approval. It is labelled official publisher imagery, not a physical capture. Shopify file readback confirms READY, 690 by 720 pixels.
- Shipping profile `SEALED_24393ECD59F64561A7C4971BB3482F2D` records **15 g as a nominal product-weight estimate**, rounded up from independently listed [13.51 g](https://paypayfleamarket.yahoo.co.jp/item/z671874880) and [13.71 g](https://paypayfleamarket.yahoo.co.jp/item/z673873184) Japanese OP-17 single packs. This is not a measurement of these two copies and excludes postal packaging. No English-pack/box/case weight, dimensions, carrier or postage price is invented.
- The first worker attempt at 15:03 UTC created drafts `gid://shopify/Product/10788230791515` and `gid://shopify/Product/10788230857051`, then failed with ShopifyApiError before price/media/stock completion. Readback shows both are already members of Sealed and One Piece, whose `ruleSet` values confirm they are automatic collections. Manual `collectionAddProducts` is the incompatible call. Repair skips that call only for automatic collections; draft and final membership verification remain mandatory. Deterministic inventory handles reuse the two existing drafts.
- The baseline for all 509 unrelated inventory records is `b6c8fdfacd3b3c5b2890f44ec4adcf8e` over ID/owner/catalogue/status/sale-intent/price/cost/location. Compare after successful publication. Exact final links, remote stock and final release checks remain pending here. No fresh signed-in phone acceptance is claimed.

## Branding continuation

The seller explicitly requires all Shopify images and copy to match the existing products. The OP-17 draft and official image were compared with live Japanese Premium Card Collection and Portgas.D.Ace tin listings, plus card-title samples. The current shared sealed template and complete official pack artwork follow those conventions. The [listing brand standard](SHOPIFY_BRAND_STANDARD.md) records the repeatable review requirements.

Tightened readback from "approved image is present" to "gallery equals the entire approved selection", so an unexpected extra file blocks publication. A live comparison also reproduced Shopify's equivalent HTML indentation and apostrophe entity rewrites, which the old byte-oriented description check rejected. Parse description structure/content for equality; text, elements and attributes still have to match. Regression cases cover changed copy, SEO, styling, escaped text turned into markup, and missing/additional media. The full local suite passes **5,063 cases**, and the actual OP-17 draft copy matches its generated sealed template under this comparison. Current-head CI and final publication remain required.
