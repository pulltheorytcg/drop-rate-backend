# One Piece official-base guide recovery — 29 October 2026

## Why a guide was missing

The public Cardmarket One Piece export identifies singles by release, name and
printed number. The reference library also preserves separately identified
parallel artwork. Previously, any parallel with the same printed number caused
`matched_products` to reject the **entire** group, including the original base.

Read-only database inspection found 95 card-number groups with an official
unsuffixed base plus another printing (92 with consistent names and rarities).
These are **investigation candidates**, not newly verified prices. The fix is
deliberately narrower, limited to ordinary OP/EB booster releases whose every
printing ID in the group is independently present in `Bandai Official`
`OFFICIAL_CHECKLIST` evidence. That evidence must explicitly identify the
base and the separately suffixed `_pN` printings. Unknown suffixes, unverified
printing IDs, starters, different names/rarities/finishes or conflicting source
releases continue to fail closed.

The Cardmarket export must still contain **exactly one** single with the same
release ID, name and printed number. Prices never choose between competing
products. Original and parallel references are never merged.

## Valuation limitations and safeguards

- Only the unsuffixed published base can receive a recovered reference guide.
- Its quote records the `OFFICIAL_CHECKLIST_BASE_WITH_SEPARATE_PARALLELS`
  match basis and `physical_valuation_eligible=false`.
- The physical-inventory guide fallback does not recognise this basis. It
  cannot update inventory valuations, grades, conditions, Shopify prices,
  ownership or settlements.
- The source remains `CARDMARKET_BULK_SINGLES`: a mixed-language, mixed-condition
  guide, **not** a verified UK sold transaction.
- No database migration, credentials, additional provider or eBay requests.

## One-time, opt-in live recovery

The regular bulk market import runs on Monday. To apply this narrowly scoped
fix sooner, the catalogue-maintenance worker supports an explicit one-time
opt-in: `TCG_ONE_PIECE_BASE_RECOVERY_ENABLED=true`. The default is `false`.

Only while the usual global maintenance advisory lock and database-capacity
guard are held, the worker downloads the same publicly available Cardmarket
bulk exports and scans the existing One Piece references. In recovery mode it
**writes only positively priced, officially confirmed unsuffixed base rows**.
All parallels, unmatched bases, and unrelated existing reference prices remain
unchanged. Physical inventory and Shopify are never written.

The durable `tcg.catalogue_job_runs` receipt uses job
`ONE_PIECE_OFFICIAL_BASE_GUIDES` with `RUNNING` followed by `COMPLETE`,
`INCOMPLETE`, or `FAILED`. After one complete run it is not repeated on
future ticks even with the flag still set. Failures back off for an hour.
The receipt's `one_piece.official_base_priced` counts the recovered prices,
not verified sold-market prices or newly valued physical inventory.

Operators must check the successful Railway deployment and receipt after
enabling, and can reset the flag to `false` after completion. The feature
does not change the usual Monday bulk-price job or its provider quotas.

## Verification

Run `python -m pytest tests/test_one_piece_market.py tests/test_cardmarket_valuations.py
tests/test_inventory_catalogue_reference.py -q` in the pinned test environment.
Positive tests require published base/parallel evidence; negative tests cover
missing official provenance, extra unverified printings, conflicting names,
rarities and finishes, unknown suffixes, starter releases, duplicate Cardmarket
products and physical-copy fallback isolation. Additional recovery tests assert
that a one-time pass writes only official base rows, respects the maintenance
advisory lock, stops after a completed receipt and backs off after failures.

The live first-party One Piece importer must run on the tested commit to obtain
any new guides. Its receipt reports `official_base_groups_matched` and
`official_base_priced`. Before claiming a coverage gain, compare the full
denominator using `docs/evidence/market_coverage_20261029.sql`, and verify that
parallel IDs remain unpriced, physical-inventory snapshots are unchanged and
fresh values retain the exact source/reference identity. No gain is claimed
from code, tests or candidate counts alone.
