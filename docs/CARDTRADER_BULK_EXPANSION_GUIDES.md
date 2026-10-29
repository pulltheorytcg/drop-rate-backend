# Drop Rate — official CardTrader bulk-expansion asking guides

## Goal

Increase **global reference-card** pricing coverage without spending a separate
eBay search per card. Official CardTrader `/marketplace/products?expansion_id=...`
normally returns the 25 cheapest active offers per blueprint in an expansion.
One expansion read therefore evaluates hundreds or thousands of cards/listings.
The separate `/blueprints/export?expansion_id=...` binds each offer to a source
printing. No scraping or paid provider is introduced.

## Controlled initial scope

- English **Dragon Ball Super Masters** and **Pokémon TCG** reference cards.
- Explicit release-name mapping, collector number, card name, rarity (Masters),
  complete Pokémon checklist, exact singleton source blueprint identity.
- Multiple alternate printings with the same name/number/rarity are **not**
  resolved by choosing a cheap seller; the entire ambiguous identity is skipped.
  Independent artwork matching must be added and tested separately for these.
- If the source's foil/edition signatures conflict, all those offers are skipped.
- Accept only raw (`graded=false`), confirmed single-unit (`bundle_size=1`,
  or `bundled_quantity=1` when the primary field is absent or zero), English,
  *Near Mint* offers from at least **three independent seller IDs**. Exclude
  signed, altered, out-of-stock and vacation inventory. Take the lowest offer
  per seller, use the lowest seven distinct sellers, reject more than a 3×
  high/low spread, and round the median to GBP pennies with dated ECB FX.
- Enforce a £1 floor and a seven-day expiry. Label as
  `INDICATIVE_ACTIVE_ASKING_GUIDE`, not a completed sale or an appraisal of
  a scanned physical card. Shipping is not included. Do not treat this as a
  precise UK sold price or automatically change Shopify/store price.
- Writes use the existing identity-guarded
  `tcg.reference_catalogue_prices` SQL; no DDL, inventory, owner or listing writes.
  Positive guides from other sources are never overwritten.

## Configuration

Already configured: `TCG_CARDTRADER_API_TOKEN` (do **not** log its value).
All new flags default off:

| Railway variable | Initial | Meaning |
| --- | --- | --- |
| `TCG_CARDTRADER_BULK_GUIDES_ENABLED` | `false` | Enable a bounded hourly official API scan. |
| `TCG_CARDTRADER_BULK_GUIDES_APPLY_ENABLED` | `false` | Report only when false. When true, write verified catalogue-only guides. |
| `TCG_CARDTRADER_BULK_GUIDES_EXPANSION_LIMIT` | `15` | 1–30 expansions per hourly run. |

The existing maintenance lock, database-capacity guard, read permissions,
hourly cadence, bounded batch, request pacing and immutable `catalogue_job_runs`
receipts apply. Changing from trial to apply replays the *trial input cursor*,
so the tested release window isn't accidentally skipped.

If the live endpoint returns more than 25 offers for a blueprint, preserve
the full validated array under strict ceilings (2,500 per blueprint and 100,000
per expansion), instead of discarding the entire release. Rejection reports
separate graded/unknown grading, seller vacation, bundle size, quantity,
blueprint identity, condition and language; they do not expose seller details.
One additional documented CardTrader field, `bundled_quantity`, can confirm
a single unit when `bundle_size` is missing or zero; a reported multi-unit
`bundle_size` is never overridden. The receipt records which field supplied
that confirmation, and unknown unit counts still fail closed.
Some live marketplace cards omit *both* unit fields. For an exact, unique
publisher-to-CardTrader match in the **single-card blueprint category only**,
accept no-reported-unit offers when there is no seller lot/bundle/playset hint,
while still requiring raw, near-mint, English, three distinct sellers and
finish consistency. Explicit bundles are always rejected. Each accepted
catalogue-only quote records `unit_evidence` and is never used to value a
physical card or change its store price.

## Verification and roll-out

1. Deploy code and confirm Railway production deployment `SUCCESS`.
2. Set `...ENABLED=true`, leave `...APPLY_ENABLED=false`. Check the
   `CARDTRADER_EXPANSION_GUIDES` receipt: `references_examined`,
   `exact_printings`, `eligible_quotes`, `provider_failures`, `by_release`.
   Each release also reports candidate offer counts, seller qualification
   counts, rejection categories, and non-sensitive source error details.
   Isolated missing expansion errors do not discard other release scans.
3. Only when source records are actually eligible, enable `...APPLY_ENABLED`.
   Confirm `writes_applied` and independent `CATALOGUE_COVERAGE` delta.
4. Review accidental mix-ups/identity conflicts before increasing the limit.
   Leave unsuitable sources, Japanese cards, Naruto, new recognition games,
   physical-copy pricing and storefront writes outside this import.

Success is *measured new GBP reference guides*, not total offers fetched or
unverified market estimates. If there are fewer than three qualifying sellers
for a printing, it remains unpriced and is reported honestly.
