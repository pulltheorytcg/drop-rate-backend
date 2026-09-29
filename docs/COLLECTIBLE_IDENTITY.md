# Collectible identity foundation

Drop Rate models a physical object separately from the canonical collectible it represents.

The universal relationship is:

`physical inventory item -> exact catalogue printing/product -> underlying collectible identity`

This prevents a correct character/name from being treated as the correct sellable variant when the artwork, rarity, finish, language, edition or printing differs.

## Identity layers

### Physical inventory

`tcg.inventory_items` remains the source of truth for the physical object Drop Rate owns or consigns.

It continues to hold ownership, acquisition cost, condition/grade, location, pricing, status and the unique Inventory ID.

This foundation does not move ownership or financial data into the catalogue layer.

### Catalogue product profile

`tcg.catalogue_product_profiles` classifies a canonical catalogue row as one of:

- CARD
- SEALED
- COMIC
- ACCESSORY

The legacy `catalogue_products.variant` and `catalogue_products.rarity` fields remain for compatibility during migration. New recognition logic should prefer the structured identity model.

### Card gameplay identity

`tcg.card_gameplay_identities` represents the underlying gameplay card.

For games such as One Piece, multiple artworks with the same native card number can point to one gameplay identity while remaining different exact printings.

### Exact card printing

`tcg.card_printings` is one-to-one with the sellable canonical catalogue product.

This is the level used for image matching, market matching, pricing and Shopify product identity.

A One Piece SEC base card and the same numbered Manga / Parallel printing therefore remain separate catalogue products even when they share a gameplay identity.

## Taxonomy registry

Game terminology is data, not hard-coded schema.

`tcg.taxonomy_schemas` defines dimensions such as:

- CARD_TYPE
- RARITY
- ART_TREATMENT
- FINISH
- SPECIAL_CLASSIFICATION
- COLOR
- ATTRIBUTE
- DOMAIN
- SEALED_TYPE
- EDITION
- COMIC_COVER_VARIANT
- COMIC_TREATMENT
- COMIC_PRINTING_CLASS

`tcg.taxonomy_values` stores the allowed values per collectible system.

`tcg.catalogue_taxonomy_assignments` attaches one or more values to an exact catalogue product.

Dimensions can be SINGLE or MULTI. This is required because some games support more than one type/treatment on a card.

Every dimension has an `UNKNOWN` value carrying `fail_closed=true`. A newly introduced game mechanic is therefore unresolved rather than silently coerced into the closest known value.

## Supported systems in foundation v1

The registry is prepared for:

- Pokémon TCG
- One Piece Card Game
- Dragon Ball Super Card Game Masters
- Dragon Ball Super Card Game Fusion World
- Disney Lorcana
- Riftbound
- future Naruto Bandai support
- Marvel Comics
- DC Comics

Naruto is registered as an announced future system only. No unsupported Naruto card taxonomy is invented before authoritative product/rules data is available.

## Sealed products

`tcg.sealed_product_details` supports manufacturer SKU, barcode/GTIN, contents and structured attributes.

The taxonomy supports product classes such as Pokémon Elite Trainer Boxes (ETBs), booster boxes, booster bundles, packs, collections, tins, decks and cases, plus One Piece booster products, starter decks, premium collections, tin pack sets and cases.

A sealed product is never represented as a card.

## Comics

`tcg.comic_printing_details` supports:

- series
- volume
- issue number
- printing number
- release year
- cover code
- cover artist
- barcode/GTIN
- extensible cover/printing treatments

The exact cover/printing is the sellable catalogue identity.

## Provider mappings

`tcg.provider_catalogue_mappings` records exact external-provider identity separately from the catalogue itself.

Important safety rule:

- `AI_SUGGESTED` mappings can never be VERIFIED.
- deterministic exact evidence can be stored for review.
- human verification records the verifying user.
- provider identities are versioned/audited.

The existing TCGdex/Punk Records media matches are imported only as REVIEW evidence. Human image approval does not silently convert them into fully verified canonical identity.

## Provider-exact import language evidence

Imported physical cards may arrive without an explicit language marker. Drop Rate must not
solve that by assigning one blanket language to an import batch.

When TCGGraph is configured, import enrichment may probe the supported candidate languages
for the existing canonical printing. Automatic identity confirmation is allowed only when:

- the original import still exactly matches the canonical name, set, collector number and
  variant/finish;
- exactly one candidate language produces a deterministic exact TCGGraph match;
- the provider request itself completed successfully for every language probed;
- the inventory version has not changed before the write.

The resulting identity event uses `verification_method=PROVIDER_EXACT` and stores the
provider ID/language evidence. Zero matches, more than one language match, a provider/API
error, or a concurrent inventory edit fails closed and leaves the item in Identity Review.

This is identity evidence only. It does not auto-approve media, condition, grading, Shopify
publication or any ownership/price mutation.

## AI recognition contract

The future recogniser must identify into this model rather than returning only a card name.

For a card, candidate evidence should include as applicable:

- collectible system/game
- underlying gameplay identity
- exact card number/set
- language
- card type(s)
- rarity
- special classification
- artwork treatment
- finish
- exact provider printing ID
- canonical visual match
- OCR evidence
- candidate margin / conflicting candidates

The deterministic backend decides whether that evidence is enough to accept the exact printing.

An AI confidence score alone is never sufficient.

## Fail-closed states

Structured records use identity states:

- LEGACY_UNREVIEWED
- STRUCTURED
- VERIFIED
- NEEDS_REVIEW

Existing imported catalogue rows begin as LEGACY_UNREVIEWED. Missing/ambiguous identity remains NEEDS_REVIEW.

Unknown taxonomy values, conflicting provider mappings, ambiguous alternate art, language mismatch and exact-printing uncertainty must go to Action Required rather than being guessed.

## Migration approach

The foundation is additive.

It does not:

- change Inventory IDs
- change ownership
- change acquisition costs
- merge existing catalogue rows
- rewrite Shopify links
- rewrite prices
- mark legacy identities verified

Legacy rarity/variant data is copied only as `MIGRATED_UNVERIFIED` evidence when a clean mapping exists.

This allows Shopify, pricing and inventory workflows to continue operating while the structured identity layer is progressively verified.
