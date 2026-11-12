# Regional catalogue sales

Opening an English or Japanese TCGdex Pokémon reference without an eligible UK value requests its exact regional sale aggregates. Existing cached observations are checked first. Background reference refreshes also attach these aggregates to future cached quotes. Legacy catalogue guides alone do not qualify.

The source mapping uses the provider printing ID, set, number, locale, variant, finish and marketplace product ID. Cardmarket supplies the seven-day sale average in EUR. TCGplayer supplies Market Price in USD. The app shows each qualifying finish and region separately in GBP with the observation date. The existing ECB converter uses the observation date. Inputs expire after seven days. A failed feed or missing finish leaves the reference unavailable.

Regional quotes span conditions. They cannot price a physical copy, slab, owner portfolio, store listing or settlement. The authenticated single-reference lookup persists a successful response through the existing catalogue cache writer **with derived market-value columns explicitly NULL**, so Cardmarket trend guides cannot be promoted during lookup. Expired or empty regional responses cannot replace previous evidence. A bounded process cache coalesces repeated checks. Browsing result pages does not initiate provider requests. No paid provider is used.

## 12 November review corrections

Physical Market Value remains fresh, exact, eligible UK completed-sale evidence only. Regional catalogue aggregates are labelled **Regional context** and require a current server permission decision; they never outrank an eligible UK value. They do not write reference_market_prices, reference_catalogue_prices, inventory, snapshots, portfolios or financial records.

Successful permitted context uses the additive Supabase regional context/history tables. The history is append-only. Full exact-reference metadata hashes prevent a reused key from returning a different printing/language. A shared PostgreSQL advisory lock, durable UTC-day counter, per-reference lease and provider-wide Retry-After backoff coordinate replicas. Reservations commit before HTTP. Failed/empty/rate-limited requests retain original quotes, evidence dates and expiry. Daily limit defaults to zero; the 500/day hard safety cap is not a claim about a published TCGdex allowance. The operator bulk hold stays unchanged.

**Source decision:** regional display is disabled for both derived feeds until the documented permission basis covers this commercial use. TCGplayer's published terms restrict competitive commercial redistribution and obtaining automated content from third parties. TCGdex's integration documentation does not resolve that permission. Cardmarket's permission for its direct public download mechanism is not proof for TCGdex's derived feed. Specific source blockers live in backend/data/regional_price_display_permissions.json; no new agreement-location question or paid scraper is required. These blockers do not stop independent first-party media and other permitted-source repairs.

Links reviewed 12 November: https://tcgdex.dev/markets-prices ; https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions ; https://insight.cardmarket.com/en/Articles/the-state-of-cardmarket-2024 . Do not turn on the display gate merely because a response is HTTP 200.

Rollback: revert the optional catalogue-context caller or keep the source permissions disabled and daily ceiling zero. New regional tables contain no financial authority; preserve their history. No destructive rollback, price rewrite, source-date extension, plan change or R2 asset deletion.

## Failure expiry correction (12 November 2026)

The physical/reference cache now keeps retry scheduling in a separate `retry_after` column. Failed or empty refreshes preserve existing quotes, checked/observed dates, expiry, amounts and revision. Expired evidence cannot regain eligibility through a retry delay. Apply the bounded additive `20261112121000_reference_refresh_backoff.sql` migration before deploying writers; reads tolerate the column being absent during schema-first rollout. Rollback may retain the unused nullable column. No existing evidence or inventory values are rewritten.

Regression coverage includes expired evidence with recent observations, empty responses, retry suppression and a real PostgreSQL assertion that all evidence fields remain identical across repeated failures.
