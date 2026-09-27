# TCGGraph canonical media

Drop Rate uses TCGGraph as the canonical card-image provider for supported games.

No AI-generated card artwork is used.

## Configuration

Railway environment variables:

- `TCG_TCGGRAPH_API_KEY` — server-side TCGGraph secret key.
- `TCG_TCGGRAPH_MAX_CONCURRENCY` — concurrent provider lookups, default 8.

The API key never reaches browser JavaScript.

## Workflow

1. Founder opens Media & Condition.
2. **Preview matches** calls `POST /api/v1/media/tcggraph/resolve` with `apply=false`.
3. Drop Rate queries only approved, unsynced, low-risk card identities which do not already have approved canonical storefront media.
4. Each TCGGraph response is checked against Drop Rate's deterministic identity.
5. **Import exact matches** repeats the lookup with `apply=true`.
6. Exact matches are inserted into `tcg.media_assets` as:
   - scope: `CANONICAL_CARD`
   - side: `FRONT`
   - source type: `LICENSED_PROVIDER`
   - rights tier: `STOREFRONT_ALLOWED`
   - provider: `TCGGraph`
   - rights/approval: verified + approved
7. **Sync images to Shopify** stages the approved TCGGraph images into Shopify Files.
8. Existing Shopify readiness/product publishing rules remain unchanged. No TCGGraph endpoint publishes a product.

## Exact matching

Common requirements:

- supported game,
- exact language,
- normalized exact card name,
- collector number equivalence,
- HTTPS image,
- stable TCGGraph card ID.

### One Piece

TCGGraph documents that parallel art shares the printed card number and is represented with suffixes such as `_p1`.

For a Drop Rate `Normal` card:

- the provider collector number must match the unsuffixed base card;
- `_p1`, `_p2`, manga/parallel records are rejected.

For a non-base local variant, an unsuffixed base record is rejected. If more than one provider treatment remains, Drop Rate fails closed instead of guessing.

### Pokémon

Pokémon collector numbers repeat between sets, so the TCGGraph query includes set name.

Finish mapping is deterministic:

- `Normal` -> normal/base printing, otherwise card image when the record has no explicit normal printing;
- `Holofoil`, `Holo`, `Foil` -> a non-reverse foil/holo printing;
- `Reverse Holo`, `Reverse Holofoil`, `Reverse Foil` -> reverse printing.

If the requested finish is absent or multiple different finishes remain, the card stays unresolved.

## Physical-photo boundary

The TCGGraph adapter does not override physical-photo policy.

Graded, high-value, condition-sensitive and exception cards remain in physical evidence / condition review and are skipped by TCGGraph canonical-media import.

## Idempotency

Cards with an existing active approved `STOREFRONT_ALLOWED` canonical front image are excluded from future TCGGraph resolution.

Database uniqueness plus `ON CONFLICT DO NOTHING` prevents repeated runs from duplicating the same canonical media row.

## Failure handling

Unresolved reasons include:

- unsupported game/language,
- no exact provider identity,
- provider finish mismatch,
- multiple exact candidates,
- missing HTTPS image,
- missing provider ID,
- TCGGraph authentication/rate-limit/service failure.

Provider failures are returned to the UI without raw credentials or response bodies.

## Shopify Files sync

`POST /api/v1/media/tcggraph/sync-shopify` processes only approved, source-active TCGGraph storefront media.

It may create or poll Shopify File records and update:

- `shopify_file_gid`
- `shopify_file_status`
- `shopify_cdn_url`
- source check metadata

It never calls Shopify product creation or publication.

## Rights record

Each imported asset records:

- provider and provider asset ID,
- TCGGraph CDN image URL,
- language and variant,
- TCGGraph terms URL as permission evidence,
- Drop Rate's product-listing-only rights basis,
- verification timestamps and audit history.

Current TCGGraph terms: https://tcggraph.com/legal/terms
