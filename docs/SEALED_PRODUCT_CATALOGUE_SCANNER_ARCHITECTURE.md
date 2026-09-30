# Sealed Product Catalogue & Scanner Architecture

_Status: approved backlog architecture, deferred behind the Phase 2 storefront launch/stability gate._

## Goal

Make sealed TCG products a first-class Drop Rate catalogue type, not an exception around card singles.

The first sealed formats to support are explicitly:

- **Elite Trainer Boxes (ETBs)**
- **Booster Boxes / Displays**
- **Single Booster Packs**

The catalogue should also be extensible to:
- Pokémon Center ETBs / exclusive ETBs;
- booster bundles;
- sleeved boosters / blister packs;
- starter / structure decks;
- collection boxes;
- premium collections;
- tins;
- display cases / sealed cases;
- gift sets;
- deck boxes or other official sealed TCG products where they are themselves the sellable product.

## Canonical model: Set vs Sealed Product

Do not model “sealed” as one row per set.

A **TCG Set** is the parent release identity.

Example:
- Set: `Pokémon — Surging Sparks`

A **Sealed Product** is a specific official sellable product under that set.

Examples:
- Surging Sparks Elite Trainer Box
- Surging Sparks Pokémon Center Elite Trainer Box
- Surging Sparks 36-Pack Booster Box
- Surging Sparks Single Booster Pack
- Surging Sparks Sleeved Booster
- Surging Sparks Booster Bundle

Each sealed product must have its own canonical ID because product type, pack count, packaging, MSRP, image, dimensions, weight, region/language and market value differ.

## Core entities

### TCG set

Suggested fields:
- `set_id`
- game
- set_name
- set_code
- release_date
- series/block
- region(s)
- languages
- manufacturer
- parent franchise

### Canonical sealed product

Suggested fields:
- `sealed_product_id`
- `set_id`
- game
- product_name
- sealed_product_type
- manufacturer SKU / UPC / EAN / GTIN where available
- region
- language
- release_date
- pack_count
- cards_per_pack where applicable
- box/display count where applicable
- MSRP / launch RRP where known
- official dimensions
- official/packed weight where known
- official front/back/side images
- distinguishing packaging markers
- edition / reprint / wave
- product status
- provider mappings

### Physical inventory item

Every physical sealed item still uses a unique Drop Rate Inventory ID and keeps:
- owner
- owner type
- acquisition cost
- location
- language
- region
- seal condition
- box/package condition
- quantity
- store price
- market value
- status
- Shopify Product ID / variant mapping

Canonical sealed identity and physical ownership remain separate.

## Scanner UX

The scanner entry should eventually support:

- **Raw Card**
- **Graded Slab**
- **Sealed Product**

### Sealed Product scan flow

1. User chooses **Sealed Product**.
2. Capture front packaging image.
3. Optionally capture barcode / back / side.
4. Detect game + set.
5. Detect sealed product type:
   - ETB
   - Booster Box
   - Single Booster Pack
   - etc.
6. Read visible text / barcode / product code.
7. Detect language/region.
8. Match against canonical sealed-product catalogue.
9. Return confidence + candidate evidence.
10. User confirms exact sealed SKU.
11. Store the canonical sealed product ID on the physical Inventory Item.
12. Record seal/package condition and acquisition details.
13. Retrieve exact permitted product imagery.
14. Run sealed-specific valuation/pricing.
15. Publish only if required sealed evidence/shipping inputs are complete.

## Recognition evidence

Sealed recognition should combine:
- packaging OCR;
- set logo/name;
- manufacturer/product code;
- UPC / EAN / GTIN;
- pack count;
- box dimensions/shape;
- official packaging artwork;
- language;
- region;
- known product-specific text;
- release wave / reprint markers where relevant.

Barcode alone must not be the only identity input because:
- some products share regional packaging patterns;
- reprints can reuse or overlap external identifiers;
- imported Japanese/Chinese/Korean products may follow different identifier conventions;
- loose packs may have no useful barcode visible.

## Language and region

Initial language support should align with the scanner language architecture:
- English
- Japanese
- Chinese
- Korean

For sealed products, **language and region are separate fields**.

Examples:
- English / UK-EU
- English / North America
- Japanese / Japan
- Chinese / Simplified Chinese market
- Korean / Korea

Two otherwise similar sealed products from different regions or languages must not be treated as interchangeable automatically.

## Pricing architecture

Sealed products need their own market-data normalization and pricing logic.

Do not price a booster box by averaging singles or multiplying pack value.

Store observations at the exact sealed-product level:
- source
- provider product ID
- timestamp
- exact sealed product ID
- region/language
- sale/listing status
- price/currency
- shipping
- condition / seal condition
- quantity where relevant

Pricing should consider:
- recent sold comps;
- active listings;
- sealed liquidity;
- release age;
- print/reprint waves;
- region/language;
- product type;
- outliers;
- shipping impact;
- supply changes.

Outputs remain:
- Market Value
- Recommended Retail Price
- Quick-Sale Price
- Target Acquisition Price

## Market-data adapters

The sealed catalogue must support provider mappings independently from card singles.

Potential sources may include permitted data from:
- eBay
- Cardmarket
- TCGplayer
- Collectr
- CardTrader
- official manufacturer catalogue/UPC data
- other legitimate provider APIs

No scraping assumption. Provider ToS and permitted access still apply.

## Shopify

A sealed canonical product may have multiple physical copies owned by different founders/consignors.

Shopify should present one customer-facing product when the physical units are truly interchangeable on:
- exact sealed product ID;
- language;
- region;
- seal/package condition policy;
- store price.

Supabase continues to own the exact physical-item allocation after sale.

## Shipping

Sealed products need real shipping inputs before publication:
- packed weight;
- dimensions;
- shipping profile;
- fragile/oversize handling if relevant.

Do not guess dimensions/weight for publication when real physical data is required.

## Sealed condition / authenticity

Suggested seal states:
- FACTORY_SEALED
- SEALED_WITH_WEAR
- SEAL_DAMAGED
- OPEN_BOX
- LOOSE_PACK
- UNKNOWN_REVIEW

Potential counterfeit / reseal indicators must enter Action Required.

High-value vintage sealed products should always receive human review before publication.

## Catalogue-building strategy

Build a governed sealed corpus by game and product line, not ad hoc per scan.

Priority:
1. Pokémon ETBs
2. Pokémon Booster Boxes
3. Pokémon Single Booster Packs
4. One Piece Booster Boxes / Displays
5. One Piece Single Packs
6. Dragon Ball Booster Boxes / Displays
7. Dragon Ball Single Packs
8. Naruto sealed products where official product data is available
9. Expand into bundles/tins/collections/decks/cases

The corpus should include canonical metadata + exact reference images + provider mappings so the scanner can recognize a sealed product that has never previously been scanned by a Drop Rate user.

## Failure handling

Raise Action Required for:
- low-confidence sealed identity
- ambiguous ETB/booster-box variant
- language/region conflict
- missing barcode/product-code evidence
- potential reseal/counterfeit
- missing shipping dimensions/weight
- missing exact reference image
- insufficient pricing data
- high-value vintage sealed
- provider lookup conflict

## Phase 2 gate

This architecture is approved now and must remain in the backlog.

Implementation remains deferred until Brand Redesign is live and the written Phase 2 stability threshold explicitly reopens recognition/catalogue expansion.

When reopened, sealed should be one of the first recognition expansions because it is commercially important and already exists in founder inventory.
