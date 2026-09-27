# Free canonical card images

Drop Rate's primary canonical-image workflow uses free, no-key providers.

## Routing

- Japanese Pokémon -> TCGdex
- Japanese One Piece -> Punk Records / Kuroro1990 OPTCG
- TCGGraph remains an optional paid backend fallback and is not the primary Founder HQ workflow.

No AI-generated card artwork is used.

## Pokémon / TCGdex

TCGdex is queried without an API key.

Japanese set identity is resolved from TCGdex's maintained
`jp_set_translations.ts` map rather than assuming the English API contains
Japanese-only releases. The map is cached in memory for one hour.

Example:

- `SV3` -> Ruler of the Black Flame
- `SV4a` -> Shiny Treasure ex
- `SV4M` -> Future Flash
- `SV8a` -> Terastal Festival ex

The resolver then fetches the Japanese card using:

`/v2/ja/sets/{set_id}/{local_id}`

Validation requires:

- exact stable set ID,
- card-number/local-ID equivalence,
- official set card count when the local denominator is known,
- requested finish supported by TCGdex variants,
- image hosted on `assets.tcgdex.net`.

Storefront image quality is `high.webp`.

Supported local finish mapping:

- Normal/Base/Regular -> `normal`
- Holofoil/Holo/Foil -> `holo`
- Reverse Holo/Reverse Holofoil/Reverse Foil -> `reverse`

Unmapped finishes stay Action Required.

## Japanese One Piece / Punk Records

The resolver downloads the Japanese `cards_by_id.json` index once per process
window and caches it for 15 minutes.

For a normal/base card such as `EB04-021`:

1. find exact unsuffixed ID `EB04-021`;
2. read its `pack_id`;
3. fetch `japanese/cards/{pack_id}/EB04-021.json`;
4. require the returned ID to remain `EB04-021`;
5. require `img_full_url` to be HTTPS on `onepiece-cardgame.com`.

Records such as `EB04-021_p1` are not substitutes for the base card.

Non-base One Piece variants currently fail closed until Drop Rate has an
explicit local variant -> provider suffix mapping. We do not guess parallel,
manga, anniversary or alternate-art treatments.

## Rights / audit metadata

The provider datasets do not transfer ownership of Pokémon or One Piece artwork.

For exact imported media Drop Rate records:

- source provider and stable provider asset ID,
- provider record URL,
- image URL,
- exact language and local variant,
- product-listing-only rights basis,
- UK CDPA 1988 section 63 reference,
- approval / verification actor and timestamps,
- subsequent source-health and Shopify-file state.

The rights scope is product-listing-only. It is not a blanket permission for
social creative, generic SEO artwork, merchandise, AI training or unrelated
marketing.

## Founder HQ workflow

Media & Condition now shows **Free canonical images**.

1. **Preview matches**
   - no database writes;
   - shows exact, unresolved, unsupported and physical-proof counts.
2. **Import exact matches**
   - inserts only deterministic matches into `tcg.media_assets`;
   - repeated runs are idempotent.
3. **Sync images to Shopify**
   - stages approved TCGdex/Punk Records images in Shopify Files;
   - never creates or publishes a Shopify product.

The existing Shopify readiness resolver remains the gate after file staging.

## Physical-item boundary

Free canonical imagery does not override physical evidence policy.

Graded, high-value, condition-sensitive, uncertain or exception inventory
continues to require first-party physical evidence where configured.

## Failure handling

The resolver fails closed for:

- unsupported game/language,
- missing Japanese set mapping,
- set/card-count mismatch,
- card-number mismatch,
- unsupported Pokémon finish,
- missing or untrusted image host,
- missing One Piece base ID,
- unmapped One Piece alternate art,
- provider timeout/rate limit/outage.

Provider failures never silently choose a different card.
