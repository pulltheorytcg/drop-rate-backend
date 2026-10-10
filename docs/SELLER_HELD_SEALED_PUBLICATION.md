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

The original record is `INV-D715B0E9B3C4451BA9095FA233F8A0E5`, owner `cba99d5c-fedf-4544-86aa-ab9a2785860f`, catalogue `24393ecd-59f6-4561-a7c4-971bb3482f2d`. Read-back still finds one physical copy at version 5, Inspection/For Sale, price 1000p. Operations must recheck the active count before adding the second confirmed copy. No acquisition cost or Drop Rate storage location is inferred.

The exact [official Japanese pack image](https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp) was uploaded to the verified Drop Rate store as `gid://shopify/MediaImage/58904403149147` and read back READY. Its exact catalogue media approval is separately recorded under the user's instruction. The seller's exact-product shipping profile must be resolved before publication; image readiness alone is not a successful sync.
