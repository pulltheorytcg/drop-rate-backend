# UK/EU Browse and Cardmarket estimate

## Purpose

Combine independently matched eBay UK active listings and an exact Cardmarket
guide into a transparent Drop Rate reference estimate. This extends the existing
pricing system; PostgreSQL remains authoritative and the existing observation
history remains intact.

The new estimate is provisional and has not been calibrated against later sales.
It must not be described as a sold price, a condition-specific valuation of a
physical copy, or proof that catalogue pricing coverage is complete.

## Evidence and calculation

- Reuse the official Browse client and the exact-reference asking matcher. Keep
  GB item location distinct from the eBay marketplace. Require fixed-price GBP
  listings and explicit matching game, printing, language, finish and raw condition.
- Use at least three independent sellers after item/seller deduplication and
  robust outlier removal. An updated snapshot of a listing is not a new sale.
- Recalculate the eBay statistic from item prices, excluding postage. Cardmarket
  guide prices use the same item-only basis; original EUR amounts and recorded
  ECB conversions must reconcile to the GBP amounts.
- Require an exact current Cardmarket product/finish quote. Ambiguous treatments,
  unbound catalogue ranges, stale observations, invalid FX and source conflicts
  cannot produce a blend.
- Use a robust eBay item-price estimate and freshness-weighted source influence.
  The starting influence is equal; the existing evidence half-lives are three
  days for active listings and seven days for guides. These are explicit initial
  rules, not fitted accuracy claims.
- Large source disagreement stops the combined estimate. Confidence stays at or
  below 0.60. Source estimates, dates, range and method remain inspectable.

## Delivery and ownership boundaries

The read path derives the estimate from existing validated source caches. It
makes no provider calls or database writes while rendering a catalogue page.
The UI labels it **Drop Rate UK/EU estimate** and identifies its asking/guide
basis. Verified sold values retain precedence. A missing raw inventory value may
show the estimate as a separate catalogue reference; owner balances, physical
valuation totals, store prices and retail recommendations do not inherit it.

The first combined source path supports raw card references. Cardmarket guides
must not be applied to manga, comics, figures, graded cards or sealed products.
Those categories require their own exact physical matching and evidence. The
existing category-specific sold and book-discovery paths remain separate.

## Acquisition and live verification

The existing asking backfill defaults to missing references only. Its explicit
priced-reference mode and bounded exact reference keys allow useful overlap with
Cardmarket without another indiscriminate scan. Scope persists in the run receipt
and must match on resume; quota reservations, idempotent history/cache writes,
identity checks and capacity limits remain enforced.

The separate manual `probe_uk_eu_market.py` performs a small, read-only live check.
Planning is its default; explicit execution uses up to three reference keys and
at most 25 Browse requests, respects provider quota headroom and request pacing,
and never writes run receipts, prices, inventory or store records. Its result is
a diagnostic, not a persisted valuation or a completed backfill.

On 4 November 2026, read-only database inspection found no cached accepted Browse
estimates. The latest persisted batch used 860 requests and accepted none. The
database was approximately 430 MB, above the existing 400 MB bulk-refresh pause.
The implementation does not raise that limit or delete history to make a run pass.

## Validation and release

Tests cover source identity/finish/FX/time validation; known free versus unknown
postage; fixed-price, expiry and exact grade checks; duplicate/conflicting items;
independent seller counts; outliers and disagreement; stale display removal;
read-only rendering; inventory isolation; targeted resume scope; request budgets;
and explicit UI labels. Full Python, UI and PostgreSQL contract CI is required.

The source-integrity prerequisite was merged as PR #911 and deployed successfully
at commit `83caff3ce9466e5a8fbab8f424d8ca40ff19cd06`. This new integration requires
its own passing CI and verified deployment. Actual live probe outcomes and final
release checks belong in the pull request evidence; do not infer them from this
implementation description.

API credentials and technical access are not representations of data-use rights.
Provider terms, permissions and retention obligations remain applicable. No
identity masking, quota circumvention or contact with provider support is part
of this implementation.
