# TCGGraph reference media

Drop Rate may use TCGGraph as an optional exact-card reference provider for supported games.

No AI-generated card artwork is used.

TCGGraph is **not** treated as granting Drop Rate the underlying publisher artwork rights. Its terms permit API data/image use and caching inside products, while explicitly stating that publisher artwork and trademarks remain owned by the relevant publishers. Therefore TCGGraph imports are fail-closed as internal reference candidates until a separate storefront-rights decision is made.

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
   - rights tier: `INTERNAL_REFERENCE_ONLY`
   - provider: `TCGGraph`
   - rights status: `VERIFIED` for the recorded TCGGraph API-use basis
   - approval status: `PENDING`
7. A human exact-print review and a separate publisher/storefront-rights decision are required before any later promotion to storefront-eligible media.
8. Existing Shopify readiness/product publishing rules remain unchanged.

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

New TCGGraph imports are `INTERNAL_REFERENCE_ONLY` and `PENDING`, therefore they are not eligible for Shopify Files sync or publication.

The existing `/sync-shopify` endpoint only processes assets that have separately become:

- `STOREFRONT_ALLOWED`
- `APPROVED`
- `VERIFIED`
- source-active

Changing a TCGGraph asset to that state must be an explicit later rights + human-review decision; provider matching alone is insufficient.

## Rights record

Each imported asset records:

- provider and provider asset ID,
- TCGGraph CDN image URL,
- confirmed local language/variant,
- TCGGraph terms URL as the provider-use evidence,
- explicit internal-reference rights tier,
- source-check metadata and audit history.

Relevant provider terms:
- TCGGraph terms: https://tcggraph.com/legal/terms
- TCGGraph acceptable use: https://tcggraph.com/legal/acceptable-use

Publisher-specific artwork restrictions remain separate from the provider API licence and must be respected.
