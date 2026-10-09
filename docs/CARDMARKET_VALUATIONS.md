# Cardmarket valuation fallback

The founder explicitly requested Cardmarket valuations alongside eBay on
9 October 2026. This extends the earlier eBay-only inventory policy. It uses
existing daily Cardmarket evidence through TCGdex, without a new paid provider
or a direct Cardmarket account/API subscription.

## How a value is produced

1. Scan every canonical catalogue product, including unowned products. For
   supported Pokémon references, match the full name, set, collector number
   including its denominator, known rarity, language where specified, and exact
   Normal/Holofoil/Reverse Holofoil finish. A unique reference and a single
   explicit variant/product quote are required. Review/rejected provider links,
   ambiguous printings and missing finish IDs stay excluded. No canonical
   identities or provider mappings are approved or changed by this process.
2. Require a positive, recent Cardmarket EUR trend quote with its original
   timestamp and validated ECB EUR/GBP conversion. The existing cache parser
   already requires the provider's explicit printing/finish IDs. US prices,
   active asking prices and stale/malformed quotes cannot enter this path.
3. Run that observation through `drop-rate-market-v4` as `PRICE_GUIDE`, with
   evidence quality 0.65 and confidence capped at 0.60. Original source language
   and condition remain unspecified: the public guide mixes both. Zero sold
   transactions are recorded; there is no invented five-sale evidence or sale
   date. Keep the original source date when recalculating.
4. Save immutable public catalogue snapshots and Cardmarket observations. The
   current canonical identity digest is checked again before insertion/display.
   A fresh exact eBay UK catalogue value takes display priority.
5. Apply the guide as a labelled estimate to identity-confirmed, ungraded Near
   Mint raw inventory of the matching reference language. Draft/inspection/
   approved states are eligible for valuation; reserved/sold/withdrawn states,
   slabs, worn copies, unknown conditions and mismatched languages are excluded.
   A current exact eBay value is retained. Every update checks owner/version and
   physical basis in a short transaction and stores its source snapshot ID.

This estimates a raw copy using a general EU guide. It does **not** claim a
condition-adjusted English/Japanese UK sold value. Customer-facing rows say
**Cardmarket estimate**, catalogue details describe the mixed language/condition
basis, and portfolio totals count estimates separately. Market Value retains
the calculated amount; the existing £1 floor applies to recommended retail,
not to the source quote. Seller Store Price is never changed. Automatic price
publication remains false regardless of engine confidence.

## Daily and immediate use

The existing daily maintenance job calculates cached guides before slow source
imports and again after a reference-price fill. Separate CARDMARKET_VALUES
receipts count all canonical products, guide bases, inventory updates and
provider calls (zero). It does not require Trawl/eBay quota. The existing
03:00 Europe/London schedule, advisory lock and one-hour failure retry apply.

Intake/manual recalculation can use an already saved, valid catalogue guide
immediately when five matching eBay sales are unavailable. Repeating the same
guide/physical basis is a no-op. Evidence remains available after the last copy
is sold because catalogue snapshots have no owner/inventory linkage. Exact
eBay refresh retains priority and recognizes valid guide snapshots during its
cleanup pass. Guide values do not create five-sale UK weekly movers.

This does not establish Cardmarket mappings for every game. One Piece and
Pokémon sealed guides continue separately as packaging references. Public
product guides do not price slabs, and unconfirmed Japanese translations,
special treatments, other-game mappings and sparse/missing quotes remain
unknown. No name-only fallback or language/condition multiplier is invented.

## Verification and rollout

Unit checks cover exact identity/number/finish/rarity/language, conflicting
quotes, stale/future dates, invalid FX/currency, graded/worn-state rejection,
eBay priority and retry behavior. The real PostgreSQL fixture exercises the
whole worker, unowned catalogue values, persistence, original evidence dates,
owner isolation, immutable history, same-quote retries, cached intake, stale
version rollback and coexistence with the eBay worker. Catalogue UI checks
verify the visible estimate label and explanation.

Apply `20261009193333_cardmarket_valuation_fallback.sql` only after current-head
CI. It permits an explicit zero-sale guide snapshot with a null sale date and
adds a source-labelled security-invoker reader. Existing forced RLS and the old
eBay-only helper remain. Deploy normally, verify the durable receipt and actual
inventory changes, and confirm that Store Prices/owners/status are unchanged.
No theme publication or test stock is part of verification.

Rollback requires reverting the worker/readers together, while retaining all
new observations and snapshots. The previous eBay cleanup removes current
guide outputs but preserves their history and seller prices. No row deletion
or identity reset is part of rollback.

Sources: [TCGdex market data](https://tcgdex.dev/markets-prices),
[Cardmarket public datasets](https://insight.cardmarket.com/en/Articles/the-state-of-cardmarket-2024),
[Cardmarket API availability](https://help.cardmarket.com/en/cardmarket-api).
