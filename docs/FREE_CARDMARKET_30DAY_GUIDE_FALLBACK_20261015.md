# Free Cardmarket 30-day guide fallback — 15 October 2026

## What and why
Drop Rate's existing **official Cardmarket bulk price guides** have a dated `trend` and a separately published 30-day average field. Previously the three single-card processors only selected `trend` (and where present `trend-foil` / `trend-holo`). A product with an exact cross-provider printing match could remain unpriced when the trend was absent even though an eligible 30-day aggregate might be available in **that same official file**.

This patch introduces a strictly **source-field-labelled guide fallback**, *only for an already-proved exact product*. It is not another provider, webpage scraping, a subscription, a new API credential or an inference of an independently verified sale.

## Existing system connections
Official Cardmarket bulk files → existing `one_piece_market`, `dragon_ball_market` and `pokemon_catalogue_market` identity checks → deterministic `choose_bulk_price_field` → existing `reference_market_prices`/`reference_catalogue_prices` cache → shared global catalogue displays. Existing cache evidence includes original EUR amount, exact source field (`trend` or `avg30`), ECB currency conversion, source date, provider product/expansion/printing IDs, language status and evidence tier.

- Positive trend retains absolute precedence; there is **no averaging or mixing** between fields.
- A missing/explicit zero trend may use positive `avg30` from the **same already verified product**.
- Foil `trend-foil` may only use `avg30-foil` for the same verified foil slot in Dragon Ball. Pokémon alternate/holo stays on the existing strict source-field policy; do not guess a foil treatment from a root average.
- Invalid negative, bool, nonfinite, excessive, nonsensical or tiny rounding-to-zero trend values **do not** permit fallthrough to a second field. Invalid/absent 30-day averages remain missing.
- Fallback quotes carry `source_field='avg30'` (or `avg30-foil`), `guide_window_days=30` and `physical_valuation_eligible=false`. The source remains `CARDMARKET_BULK_SINGLES`/`CARDMARKET_CATALOGUE`; these are explicitly mixed-language/mixed-condition references.
- Physical-copy Cardmarket application requires `source_field='trend'`. This prevents a fallback average from silently determining a user's physical valuation, retail recommendation, asking price or auto-publish status.
- Existing unpriced duplicate printing/parallel/source-ID mapping checks are unchanged. A valid price never chooses between identities.

## What this cannot solve
An exact printing *without a unique approved Cardmarket product mapping* remains unpriced. This fallback cannot resolve the majority of the 26,617 physical-reference gaps, and it cannot price Naruto or an ambiguous Japanese/parallel card. No provider call or price-cache write is performed by this PR alone; **live priced-count gain is zero until a subsequent verified normal refresh**.

## Failure points and tests
- Ambiguous release, name, collector number, parallel or language → existing matching rejects.
- Unavailable or malformed `trend` or `avg30` → returns no quote.
- USD-only, asking-price-only and stale date → remains excluded by existing shared-price validation.
- Physical/graded/condition-specific valuations → fallback always ineligible.
- Provider outage → existing cache retention and failure logs unchanged.
- Supabase Free capacity: **do not force-run the full catalogue refresh while the database exceeds the safe threshold.** See [capacity incident](DATABASE_READ_ONLY_INCIDENT_20261014.md), [open capacity issue](https://github.com/pulltheorytcg/drop-rate-backend/issues/651), and verified archive runbook.

`tests/test_market_guide_fields.py` validates exact source fields, trend precedence, bad-input rejection, strict One Piece release identity, Dragon Ball base/foil separation, Pokémon foil no-guessing, GBP conversion, and that fallback data cannot become a physical value. Existing complete backend and market-provider tests remain release gates.

## External source context
Cardmarket announced first-party public product-catalogue/price-guide downloads in June 2024 and expanded them to non-singles in October 2024. Its API documentation identifies `AVG30` and `Foil AVG30` as 30-day sales aggregates. These aggregates do not expose individual transaction IDs, conditions or languages and cannot be passed off as UK sold comparisons.
