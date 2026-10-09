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

## Verified release — 9 October 2026

PR [#557](https://github.com/pulltheorytcg/drop-rate-backend/pull/557) merged as
`b0e9668d9faf190bde0bd209079a9bae010b3f07`. Its final head `7558704` passed all
four workflows: Backend checks, Live market persistence, Catalogue maintenance
persistence and Independent catalogue valuations. The backend passed 2,759
tests, and the catalogue UI passed 34 scenarios alongside the other UI suites.

The versioned migration was applied as `cardmarket_valuation_fallback` at
19:56:35 UTC. Railway deployment `999d9e89-b8fd-4c45-be4c-8b172531a5bd` reached
SUCCESS at 19:57:57 UTC; readiness returned 200. All original pre-deploy checks
remain configured, including financial checks and the social evidence probe.
The probe still reports the existing eBay provider limit; a successful deploy
does not imply that the sold-data quota has recovered.

Production read-back confirms the new helper is SECURITY INVOKER with a fixed
`pg_catalog` search path. Anonymous/authenticated Supabase roles cannot execute
it; the API role can. Catalogue snapshots retain forced RLS and denied API
UPDATE/DELETE privileges. Security advisors show no additional findings from
this migration. Shopify confirms Brand Redesign is UNPUBLISHED and Horizon is
MAIN. No new service or provider subscription was created. This release has
automated UI evidence; fresh signed-in browser and iPhone acceptance are not
claimed.

The first production calculation at 20:02:55 UTC stopped with
`InsufficientPrivilegeError`: `FOR SHARE` on canonical products requires an
UPDATE privilege that the API role deliberately does not have. Its first
transaction rolled back; no guide observations/snapshots or inventory values
were committed. The INCOMPLETE receipt records attempted work, not coverage.
Revision 2 removes that catalogue lock while retaining the inventory row lock,
and atomically rechecks catalogue ID/digest together with owner/version during
the value update. No production privilege is expanded. The PostgreSQL fixture
now mirrors read-only canonical identity, column-scoped inventory writes and
append-only pricing evidence, and checks a printing changed after selection.
The revision schedules a retry without rewriting the failed receipt.
