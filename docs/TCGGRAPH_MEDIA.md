# TCGGraph exact-listing media

Drop Rate may use TCGGraph as an optional exact-card data/image provider for supported games.

No AI-generated card artwork is used.

TCGGraph's terms (last checked 29 September 2026; terms updated 28 September 2026) expressly permit API data and images to be displayed to users inside paid products and cached by the product. TCGGraph does **not** grant the underlying publisher artwork rights. Drop Rate therefore applies a second, narrower use restriction: an exact TCGGraph image may be used only on the Shopify product listing advertising the sale of that exact physical card, under the project's UK CDPA 1988 s63 sale-advertising basis. It is not approved for social media, generic SEO artwork, merchandise, AI training, or unrelated marketing. Human exact-print approval remains mandatory before Shopify use.

## Configuration

Railway environment variables:

- `TCG_TCGGRAPH_API_KEY` — server-side TCGGraph secret key.
- `TCG_TCGGRAPH_MAX_CONCURRENCY` — concurrent provider lookups, default 8.

The API key never reaches browser JavaScript.

The adapter remains dormant when the key is absent.

## Workflow

1. A platform admin requests a TCGGraph preview with `POST /api/v1/media/tcggraph/resolve` and `apply=false`.
2. Drop Rate selects only approved, unsynced card identities that do not already have approved storefront canonical media.
3. Physical-photo policy is evaluated first. Graded/high-value/condition-sensitive cards that require exact first-party photos are skipped.
4. TCGGraph is queried server-side.
5. Provider results are checked against deterministic Drop Rate identity fields.
6. `apply=true` may insert exact provider matches into `tcg.media_assets` as:
   - scope: `CANONICAL_CARD`
   - side: `FRONT`
   - source type: `LICENSED_PROVIDER`
   - rights tier: `STOREFRONT_ALLOWED` **only for the exact product-sale listing**
   - provider: `TCGGraph`
   - rights status: `VERIFIED` for the recorded TCGGraph terms + product-sale advertising basis
   - approval status: `PENDING`
7. A human exact-print review is still required. Provider matching never auto-approves media.
8. Only an `APPROVED` + `VERIFIED` + source-active TCGGraph asset can proceed to Shopify Files; existing product publication rules remain unchanged.

The adapter must never auto-publish a Shopify product.

## Exact matching

Common requirements:

- supported game,
- exact confirmed language,
- normalized exact card name,
- collector-number equivalence,
- HTTPS image,
- stable TCGGraph card ID.

Unknown local language remains unresolved. TCGGraph's available language does not silently become Drop Rate's physical-card language.

### One Piece

TCGGraph documents that parallel art shares the printed card number and is represented with suffixes such as `_p1`.

For a Drop Rate `Normal` card:

- the provider collector number must match the unsuffixed base card;
- suffixed parallel records are rejected.

For a non-base local variant, an unsuffixed base record is rejected. If more than one provider treatment remains, Drop Rate fails closed instead of guessing.

### Pokémon

Pokémon collector numbers repeat between sets, so the TCGGraph query includes set name.

Finish mapping is deterministic:

- `Normal` -> normal/base printing, otherwise card image when the record has no explicit normal printing;
- `Holofoil`, `Holo`, `Foil` -> a non-reverse foil/holo printing;
- `Reverse Holo`, `Reverse Holofoil`, `Reverse Foil` -> reverse printing.

If the requested finish is absent or multiple different finishes remain, the card stays unresolved.

### Dragon Ball Super — Masters vs Fusion World

TCGGraph represents both Bandai lines under:

`game=dragon-ball-super`

and distinguishes them with:

`gameData.line=masters`

or:

`gameData.line=fusion-world`

Drop Rate stores these as separate game names:

- `Dragon Ball Super` -> `masters`
- `Dragon Ball Super Fusion World` -> `fusion-world`

The adapter must send the corresponding `line` filter and must also reject a returned record whose `gameData.line` does not match the local Drop Rate game.

This prevents a same/similar identifier or name from crossing the two incompatible game lines.

## Physical-photo boundary

The TCGGraph adapter does not override physical-photo policy.

Graded, high-value, condition-sensitive and exception cards remain in physical evidence / condition review and are skipped by TCGGraph reference import.

For graded inventory:

- canonical/reference media supports identity;
- the exact physical slab FRONT + BACK remains required for Shopify.

## Idempotency

Database uniqueness plus `ON CONFLICT DO NOTHING` prevents repeated runs from duplicating the same provider reference.

Provider imports remain PENDING. Re-running the adapter must not silently upgrade approval state.

## Failure handling

Unresolved reasons include:

- unsupported game/language,
- unknown local physical language,
- no exact provider identity,
- wrong Dragon Ball line,
- provider finish mismatch,
- multiple exact candidates,
- missing HTTPS image,
- missing provider ID,
- TCGGraph authentication/rate-limit/service failure.

Provider failures are returned without raw credentials or sensitive response bodies.

## Shopify boundary

New exact TCGGraph imports are `STOREFRONT_ALLOWED` for the narrowly recorded product-sale-listing purpose but remain `PENDING`, so provider matching alone still cannot send them to Shopify.

The existing `/sync-shopify` endpoint processes only assets that are:

- `STOREFRONT_ALLOWED`
- `APPROVED`
- `VERIFIED`
- source-active

Human exact-print approval is therefore still a hard gate. Shopify use is limited to advertising the sale of the exact physical card represented by the listing; the same asset must not be repurposed into social, generic SEO, merchandise, AI-training or unrelated marketing workflows.

## Rights record

Each imported asset records:

- provider and provider asset ID,
- TCGGraph CDN image URL,
- confirmed local language/variant,
- TCGGraph terms URL as the provider-use evidence,
- explicit exact-product-listing rights tier,
- TCGGraph provider terms URL,
- UK CDPA 1988 s63 statutory-use reference in the recorded rights basis,
- source-check metadata and audit history.

Relevant provider terms:
- TCGGraph terms: https://tcggraph.com/legal/terms
- TCGGraph acceptable use: https://tcggraph.com/legal/acceptable-use

Publisher-specific artwork restrictions remain separate from the provider API licence and must be respected. This policy is a narrow operational basis for product-sale listings, not a general artwork licence.
