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

## Dragon Ball set-name aliases verified in production

CardTrader uses `Tournament & Championship Promos` while the Drop Rate canonical set is `Tournament and Championship Promos`. Set-key normalization treats ampersand and the word `and` as equivalent before exact matching.

Pre-release inventory remains intentionally stricter. CardTrader's base `Supreme Rivalry` and `Dawn of the Z-Legends` blueprints expose the same card numbers/names but no provider-level pre-release evidence for the six physical pre-release copies in the current import. Drop Rate must not fall back those local `... Pre-Release Cards` records to ordinary base-set media; they remain unresolved until exact pre-release media evidence is available.


## Printing safeguards after production diagnostics

The provider's production catalogue uses `Tournament & Championship Promos` while Drop Rate
stores `Tournament and Championship Promos`; ampersand/word-`and` equivalence is normalized
before exact expansion matching.

Collectr-style local names may include a redundant suffix such as
`- FP-045 (Tournament Pack 07)`. That suffix may be stripped from the name comparison only;
collector number remains a mandatory hard identity gate.

For a local pre-release set, the resolver first looks for an exact pre-release expansion. If
none exists, it may inspect the base expansion only when the chosen Blueprint's own version
text explicitly proves `Pre-Release`. Base inventory rejects pre-release Blueprints. Current
CardTrader production data does not expose that proof for the six outstanding Drop Rate
pre-release copies, so those six remain unresolved rather than receiving base-print media.
