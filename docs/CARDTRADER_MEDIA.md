# CardTrader exact Dragon Ball media

## Purpose

CardTrader is an optional read-only identity/media provider for Dragon Ball Super Masters
and Dragon Ball Super Fusion World cards whose physical inventory identity, language and
variant have already been confirmed.

The adapter exists to resolve an exact provider Blueprint and its `image_url` so Drop Rate
can register a storefront image candidate without scraping CardTrader pages.

## Provider contract

- API base: `https://api.cardtrader.com/api/v2`
- Authentication: Bearer token from the merchant's CardTrader profile settings.
- Games: `GET /games`
- Expansions: `GET /expansions`
- Blueprints: `GET /blueprints/export?expansion_id=...`
- Marketplace evidence fallback: `GET /marketplace/products?blueprint_id=...`
- Provider terms: `https://static.cardtrader.com/en/pages/terms-of-service`
- API reference: `https://www.cardtrader.com/en/docs/api/full/reference`

CardTrader's terms expressly permit API use for handling inventory on CardTrader or other
sales channels. Provider API permission is not treated as a blanket publisher-artwork
licence. Drop Rate therefore restricts returned images to the Shopify product listing
advertising the sale of that exact physical card under the project's UK CDPA 1988 s63
sale-advertising basis.

The image must not be repurposed for social posts, generic SEO artwork, merchandise,
AI training or unrelated marketing.

## Exact-match gates

The adapter fails closed unless all of the following are true:

1. local game is Dragon Ball Super Masters or Dragon Ball Super Fusion World;
2. physical card language has already been confirmed;
3. exactly one CardTrader expansion matches the local set and correct game line;
4. blueprint name matches exactly after normalization;
5. collector number is proven by the Blueprint payload or a language-filtered marketplace
   product property;
6. local normal/foil family is supported;
7. exactly one Blueprint remains;
8. the returned image URL is HTTPS and hosted on a CardTrader-owned hostname.

A missing collector number, unknown image host, ambiguous expansion/Blueprint, provider
error, unsupported variant or missing physical language leaves the item unresolved.

## Human review boundary

Resolved CardTrader media is registered as:

- scope: `CANONICAL_CARD`
- side: `FRONT`
- source type: `LICENSED_PROVIDER`
- rights tier: `STOREFRONT_ALLOWED`
- rights status: `VERIFIED`
- approval status: `PENDING`

The provider result never auto-approves the asset and never publishes a Shopify product.
A human exact-print review remains required before Shopify Files/bootstrap can use it.

## Production configuration

Optional environment variables:

- `TCG_CARDTRADER_API_TOKEN`
- `TCG_CARDTRADER_MAX_CONCURRENCY` (default 8)

No token is stored in source control or returned to the browser.

## Current Dragon Ball backlog

The production backlog is 35 unlinked raw cards:

- 29 Dragon Ball Super Masters
- 6 Dragon Ball Super Fusion World

All already have a positive store price, Near Mint condition and registered storage
location. Before this adapter can process them, production still requires a CardTrader API
token and explicit physical-language confirmation for the imported copies. CardTrader is
not used to infer the language of the user's physical card.

## Production response normalization

The production CardTrader account currently returns `GET /games` as an object wrapper:

`{"array": [...]}`

rather than the bare list shown in the public reference. `GET /expansions` still returns the documented bare list. Marketplace products are documented as an object keyed by Blueprint ID. The client normalizes these shapes explicitly and fails closed for unknown wrappers or missing Blueprint keys.


## Dragon Ball naming/printing normalization

Production CardTrader data exposed two provider-specific representation differences that are
handled deterministically:

- Drop Rate catalogue `and` and CardTrader `&` are treated as equivalent in expansion names.
- Collectr-style promo suffixes such as `- FP-045 (Tournament Pack 07)` are removed from the
  local comparison name, while collector number remains a mandatory hard identity gate.
- If a local set is explicitly a pre-release printing and CardTrader has no separate pre-release
  expansion, the resolver may fall back to the base expansion only when the Blueprint's own
  version text explicitly proves `Pre-Release`.
- Base-set inventory rejects Blueprints whose version is marked pre-release.

These rules do not relax collector-number, language, game-line, exact Blueprint uniqueness or
trusted image-host checks.
