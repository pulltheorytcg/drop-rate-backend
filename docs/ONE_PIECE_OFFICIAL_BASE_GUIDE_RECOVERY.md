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

## Verification

Run `python -m pytest tests/test_one_piece_market.py tests/test_cardmarket_valuations.py
tests/test_inventory_catalogue_reference.py -q` in the pinned test environment.
Positive tests require published base/parallel evidence; negative tests cover
missing official provenance, extra unverified printings, conflicting names,
rarities and finishes, unknown suffixes, starter releases, duplicate Cardmarket
products and physical-copy fallback isolation.

The live first-party One Piece importer must run on the tested commit to obtain
any new guides. Its receipt reports `official_base_groups_matched` and
`official_base_priced`. Before claiming a coverage gain, compare the full
denominator using `docs/evidence/market_coverage_20261029.sql`, and verify that
parallel IDs remain unpriced, physical-inventory snapshots are unchanged and
fresh values retain the exact source/reference identity. No gain is claimed
from code, tests or candidate counts alone.
