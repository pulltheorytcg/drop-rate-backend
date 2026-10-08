# Seller Hub market references — 8 October 2026

The catalogue sync imports TCGdex set checklists, which omit the pricing carried by individual card-detail responses. Unmapped references therefore had no prices even when the existing provider exposed them. Physical inventory benchmarks are a separate path and must not be confused with catalogue coverage.

The browser now renders results immediately, then requests prices for at most 40 known reference keys per request. FastAPI fetches fixed-host TCGdex card details for English Pokémon references, checks the provider printing ID, set, name and local number, and accepts only standard normal/holo/reverse variants with explicit variant IDs and matching TCGplayer product IDs. It uses that finish's positive `marketPrice`, never high/asking prices or another finish's value. Missing, ambiguous, future or stale data remains pending. No raw value is applied to a slab.

USD values use the existing historical ECB converter for the provider observation date. PostgreSQL stores original amounts, finish and product IDs, GBP values, source timestamps and the exact FX provenance in the new reference cache. This cache is public reference information, separate from immutable physical-inventory observations and snapshots. No inventory ownership, identity approval, Store Price, media approval, market-ingestion switch or storefront publication changes are made by this path.

The cache lasts 12 hours for prices and six hours for missing coverage. Provider failures retain recent known quotes and retry after five minutes. Quotes older than seven days stop displaying. Six concurrent provider requests, fixed URLs, no redirects, a 1 MB response cap and bounded timeouts constrain upstream work. Network requests run outside database transactions. Cache writes reject older concurrent attempts; browser updates reject responses from a previous search/session. Value sorts use saved quotes before pagination. They can only rank prices already available in the cache, not the entire unpriced catalogue.

Different finishes display a GBP range with individual finish prices, date and source in product details. A late price response changes only the price content, preserving an open condition form and keyboard focus. Failure leaves cards and existing prices usable. Existing physical snapshot references retain priority over the broad reference range.

## Access and rollout

`POST /api/v1/catalogue-browser/market-values` uses the same authenticated owner/founder access dependency as catalogue search. Its body accepts only bounded reference keys, never prices, owners or URLs. The new table has forced RLS; only the trusted server role can cache authenticated requests. Public/anonymous/Supabase browser roles have no privileges. Apply `20261008182234_reference_market_prices.sql` before the code deployment. Reverting the code is safe with the additive cache left in place.

The optional `seller_market_provider_probe.py` script reads the existing sealed OP-17 eBay/CardTrader providers without database writes or secret output. It neither approves mappings nor substitutes a box for a pack. It is an operator diagnostic, not a recurring job.

## Verification

Targeted backend checks cover identity/finish/marketplace mismatches, invalid money/currency/timestamps, FX provenance, ambiguity, stale expiry, cached retry, provider outages, bounded request validation and authentication. UI tests cover asynchronous prices/ranges, retained form state, stale-search isolation and provider failure. The complete backend and UI suites pass. A live public-provider check returned Seel Normal and Reverse Holofoil and Umbreon VMAX Holofoil with their separate exact IDs and historical FX. Many newly indexed references still have no provider pricing; Japanese, other games and graded cards are not silently covered by English raw Pokémon quotes. The additive migration is applied, RLS/role privileges are verified, and both normal and value-sorted production queries returned the two saved quotes and their artwork. CI, production deployment and HTTP read-back are distinct remaining release gates at this checkpoint.

Provider documentation: https://tcgdex.dev/reference/card, https://tcgdex.dev/markets-prices and https://tcgdex.dev/faq. The FAQ's warning about broad price mappings is why this implementation requires `variants_detailed` and explicit per-variant marketplace IDs.
