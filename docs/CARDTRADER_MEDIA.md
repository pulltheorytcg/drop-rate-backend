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

## Original-size image policy

CardTrader Blueprint payloads may return a `preview_...` derivative. Production checks on
30 September 2026 confirmed those preview files were typically only about **180 x 251 px**,
while the same exact Blueprint path without the `preview_` filename prefix returns the
larger provider original.

The adapter now canonicalises only that filename prefix on the same HTTPS CardTrader host,
Blueprint directory and provider asset. It does not change card identity, set, language,
finish or provider asset ID.

Observed original sizes vary by era/source and are still not necessarily 4K:

- older Masters examples: about 251 x 350;
- Dawn of the Z-Legends examples: about 313 x 437;
- later Masters examples: up to about 1279 x 1782;
- Fusion World promo examples: about 600 x 838 to 716 x 1000.

Therefore "4K" must never mean enlarging a thumbnail and calling it a higher-quality
canonical image. For a genuine 4K-class storefront source (2160+ px long edge), Drop Rate
should use an exact first-party high-resolution capture/scan when no permitted provider
offers one. A 1200-DPI scan of a standard trading card is roughly 3000 x 4200 px and clears
that quality target without reconstructing or hallucinating artwork/text.

## Winner promo matching

Fusion World Winner promos may encode the Winner distinction in two places at CardTrader:
the Blueprint version (for example `Tournament Pack 06 | Winner`) and a provider collector
suffix such as `FB05-039w`.

Drop Rate accepts that `w` suffix only when the local physical inventory explicitly says
Winner and its Tournament Pack number matches the provider version. The same suffix is
rejected for ordinary/non-Winner local cards. Pack-number mismatches remain blocked.

## Current Dragon Ball backlog

As of 30 September 2026, 25 Dragon Ball Shopify products are published and their
CardTrader preview derivatives have been replaced in place with the same Blueprint's
verified larger original.

Eight FOR_SALE Dragon Ball cards remain unlinked:

- Vegeta FB05-039 Winner 06 now has an exact CardTrader Winner candidate registered in
  `PENDING_REVIEW`; its former `MEDIA_UNRESOLVED` exception is resolved;
- six Masters pre-release copies remain genuinely media-unresolved because CardTrader's
  Blueprints expose only the ordinary base-set printing;
- Nappa FP-046 remains genuinely media-unresolved because the local physical item is
  Tournament Pack 07 while CardTrader currently exposes Tournament Pack 08.

That means the unresolved-media count is now seven, even though eight physical Dragon Ball
units are still not linked to Shopify.

The no-photo fallback is the already-built TCGGraph exact-media adapter. TCGGraph supports
both Dragon Ball lines and exact-print image candidates, but production does not currently
have `TCG_TCGGRAPH_API_KEY` configured. No paid provider dependency is silently enabled.

External public pages may be used as identity evidence only. They are not automatically
promoted into storefront media: TCGplayer's public terms restrict crawling/scraping and
outside use of its content, while Bandai's public Masters card list exposes the ordinary
card image and does not itself prove the stamped pre-release physical printing. The seven
special prints therefore remain fail-closed until a storefront-permitted exact provider
credential is configured. CardTrader is never used to infer the language of the user's
physical card.

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


## Fusion World tournament-promo proof

Production CardTrader diagnostics show the current tournament-pack cards are stored under
`Fusion World Promos` (expansion 3678), not under `Tournament & Championship Promos`.

Drop Rate therefore maps the local canonical set `Tournament and Championship Promos` to
CardTrader `Fusion World Promos`, but only with exact Blueprint proof:

- collector number remains mandatory;
- the local Tournament Pack label must match the Blueprint `version` text exactly;
- a local `Winner` label cannot match an ordinary Tournament Pack Blueprint;
- a Pack 07 import cannot match a Pack 08 Blueprint.

Production evidence currently confirms:
- FP-045 Tien Shinhan → Tournament Pack 07: eligible for exact-match resolution;
- FP-047 Vegeta (Mini) : DA → Tournament Pack 07: eligible for exact-match resolution;
- FP-046 Nappa local Pack 07 vs provider Pack 08: blocked;
- FB05-039 Vegeta local Winner 06 vs provider ordinary Tournament Pack 06: blocked.


## Masters bare collector-number suffixes

Production CardTrader data has a small number of Dragon Ball Super Masters Blueprints whose
`collector_number` omits the set prefix, for example:

- Drop Rate `BT18-067` -> CardTrader `067`
- Drop Rate `BT18-138` -> CardTrader `138`
- Drop Rate `BT13-142` -> CardTrader `142`

The resolver may treat a bare numeric provider value as the suffix of a local Masters
`BTxx-yyy` number only when all normal identity gates already match and CardTrader's
explicit rarity property also matches the local canonical rarity. The returned resolution
preserves both the full local collector number and the raw provider collector number for
provenance.

This fallback is deliberately unavailable to Fusion World, FP/P promos and other number
families.
