# Catalogue, pricing and artwork reconciliation — 4 November 2026

## Problem and released behaviour

The price-coverage endpoint reported the SQL reference tables as the entire
catalogue. It omitted the published R2-first games, so the previous status report
incorrectly presented 67,217 physical card references as the full TCG catalogue.
The original price-reference percentage is not a global market-value percentage.

The authenticated coverage endpoint now includes separate publication counts,
SQL artwork-link counts and the current automatic-refresh capacity gate. The
Founders dashboard displays this evidence when opened, with a manual recheck.
Existing numeric SQL coverage fields remain compatible; the top-level scope is
corrected to `SQL_REFERENCE_CARDS_AND_SEALED_PRODUCTS`. The new `catalogue`
object supplies the expanded stored count without adding imports to the old
price-coverage denominator. No canonical products or inventory are created.

Expired exact-identity catalogue references previously disappeared from the
coverage join and could be classified as missing provider mappings. They now
appear as `STALE_EVIDENCE`; expired values still cannot count as current prices.
No price is relabelled, recalculated, refreshed or made eligible by this change.

## Production evidence before release

| Stored physical TCG references | Count |
| --- | ---: |
| Original SQL card references, excluding digital Pocket | 67,217 |
| YGOPRODeck / Yu-Gi-Oh! | 45,215 |
| Lorcast / Disney Lorcana | 3,505 |
| MTGJSON / Magic paper printings and finishes | 153,662 |
| Total source printing/finish references | 269,599 |

These are source references, including future releases, not distinct card names
or physical inventory. The prior Magic publication receipt excluded 2,049
future-release references from then-current search. Sports and figures are
reported separately and do not inflate the TCG total. Riftbound has no active
publication. The three new TCG imports are metadata-only: they do not establish
artwork or market-value coverage.

Pricing receipts show 43,761 counted references on 31 October, including 280
provisional internal model estimates. PR #863 stopped counting those estimates
toward source-backed coverage on 1 November. The 3 November 22:40 UTC receipt
recorded 41,083 current source price references. A read on 4 November recorded
39,771 (59.17% of the original 67,217), including market guides. Replaying the
same current records at the 3 November receipt time reproduces 41,083: the
subsequent 1,312 decline is evidence ageing out, not deletion of card records.
The original 39,863 read earlier on 4 November had already fallen by another 92
as individual seven-day evidence windows elapsed. These figures are dated
observations and must not be hardcoded into the application.

The corrected read classified 3,801 original physical card references as stale.
The database measured 430,394,515 bytes and the Supabase organization remains on
the Free plan. Production logs repeatedly record
`BULK_REFRESH_DEFERRED_CAPACITY`: the existing 400,000,000-byte bulk-refresh
threshold pauses automatic ingestion before the 500,000,000-byte limit.
This code neither disables that guard nor purchases capacity. The largest
relations are audit events (~106.6 MB), reference cards (~77.2 MB), reference
market prices (~58.6 MB), and reference catalogue prices (~50.1 MB).
Existing audit/financial history must remain recoverable and auditable.

Original physical artwork remains 63,901 links out of 67,217; 3,316 are blank.
These are link counts, not an end-to-end image-delivery certification. A bounded
repair using the existing exact-identity TCGdex mappings checked 252 of 380
candidates in its first 120-second pass: all returned HTTP 404, with zero image
updates. The remaining 128 candidates were resumed from the saved cursor and
also returned HTTP 404: all 380 reviewed candidates were checked, with no safe
image repair available from this source. Slab
photos remain tied to their own physical inventory items; raw artwork and other
owners' photos are not substitutes.

## Validation and failure behaviour

- Coverage tests verify the expanded total, digital/sealed/sports exclusions,
  missing publication status, metadata-only pricing semantics, and private
  manifest-field filtering.
- Disabled readers and overlapping SQL/R2 games cannot claim a complete global
  count; invalid or duplicate publications fail closed. Registry errors are not
  cached as successful partial coverage.
- The shared cache still coalesces authenticated global reads for two minutes.
  Capacity reads do not write data or start provider requests.
- Dashboard tests cover founder-only loading, counts and scope wording, refresh
  pause display, logout cleanup and revoked access. Existing owner isolation,
  grading, artwork and financial checks remain required in CI.
- Production read-only SQL validates the revised classification and unchanged
  eligible-price counts; source histories and old job receipts are preserved.

## Outstanding work

Automatic price refresh needs actual database headroom. Removing the guard or
extending evidence freshness would conceal the cause. Capacity expansion or a
separately verified archive/reclamation operation must precede a full backfill.
New-game artwork and market data require independent permitted feeds and exact
printing/finish mappings. Metadata import completion does not complete those
adapters. Riftbound remains subject to its reviewed Riot access requirements:
https://developer.riotgames.com/policies/riftbound .

Rollback is a code revert, retaining all source data and publication pointers.
This change performs no schema migration, historical-price deletion, inventory
mutation, provider-access change, ownership change or Store Price update.
