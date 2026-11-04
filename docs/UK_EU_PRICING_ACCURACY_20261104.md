# UK/EU pricing evidence and accuracy - 4 November 2026

## Objective and current implementation

Continue Drop Rate's existing valuation engine across cards, manga, comics,
figures/Funko, graded and sealed products. Reuse collected observations and
verified history. Do not start a second pricing engine or substitute arbitrary
fixed source weights for measured accuracy.

The existing `pricing_engine.py` (v4, source-integrity revision) already uses
recency-weighted medians, robust outlier filtering, source deduplication,
UK/EU anchors, grade/condition/language matching and review thresholds.
`pricing.py` currently chooses five exact eBay GB sold observations; Cardmarket
is a separately labelled guide fallback. `catalogue_valuations.py` also rebuilds
catalogue values from five accepted comparable sales. This diagnostic does not
alter those production paths.

## Verified read-only evidence

- Stored canonical observations: 1,083 eBay GB SOLD rows spanning 145 catalogue
  products; 5,158 Cardmarket guide observations. Of those guides, 5,157 span
  244 products with EU attribution; one earlier guide has no country.
- Recorded archive receipts: 92 R2 archives / 117,148 history rows and five
  Drive archives / 900,705 history rows, all with recorded restore verification.
  This pass inspected receipts, not the archive bytes. Do not add these counts
  to distinct-sale coverage: histories include repeated guide snapshots.
- Latest recorded CARDMARKET_VALUES pass (3 November 22:39 UTC): 244 catalogue
  snapshots and 167 inventory valuation updates; zero Store Price changes.
  Latest recorded CATALOGUE_VALUES pass: 133 valued products.
- Current Cardmarket observations do not specify condition/language. They
  cannot be represented as five independent exact English Near Mint sales.
- Stored sold evidence currently covers Pokemon, One Piece and six sealed
  observation rows. No manga/comic/figure observations occur in this export.
  Catalogue references and price evidence are separate completeness measures.

## Offline replay

`backend/scripts/replay_pricing_accuracy.py` reads at most 10,000 normalized
observations / 20 MiB from a local JSON export. It performs no network requests,
database writes, source imports, automatic repricing or tuning. Outputs are
aggregate metrics and category labels; no listing IDs, catalogue IDs, owner IDs,
credentials or provider payloads are printed.

For every later sale, use only strictly earlier observed sales that had already
been ingested before the held-out sale. Keep exact catalogue, condition, grade,
language and seal basis. Collapse repeated receipts and quarantine contradictory
sale IDs, including IDs assigned to different products. Future corrections
cannot retroactively change the information available for a prediction.
Compare 5/10/20 prior-sale windows on the same eligible later transactions.
Item and delivered prices are separate runs; missing postage is never zero.

Private input: 1,083 normalized rows; zero malformed rows; one conflicting
provider sale ID excluded (two contradictory rows); 1,081 independent outcomes.
Of these, 333 later sales had five earlier eligible independent sales.

| Price basis | Holdouts | Median absolute percentage error | Median absolute GBP error | Within 10% |
| --- | ---: | ---: | ---: | ---: |
| Item, excluding postage | 333 | 23.4483% | GBP 0.47 | 24.32% |
| Delivered, known postage included | 333 | 22.3585% | GBP 2.20 | 39.34% |

These rows assess different price targets; GBP errors are not directly
comparable. Neither is a claim of market-leading accuracy.

All scored holdouts had **exactly five** eligible prior sales. Consequently,
the 5/10/20 windows produced identical predictions. The data cannot select
a superior window or justify changing the existing five-sale rule.

| Category | Independent sale outcomes | Scored later sales |
| --- | ---: | ---: |
| Pokemon | 637 | 183 |
| One Piece cards | 438 | 149 |
| Sealed | 6 | 1 |
| Manga / comics / figures | 0 | 0 |

For item prices, 275/333 holdouts were under GBP 5, 53 were GBP 5-50,
and just five were GBP 50+. The sample is not representative of high-value,
graded, manga/comic or figure pricing. Error against one later sale includes
normal transaction variation; it is not an error against an unknowable single
true market value. Collection/selection bias remains.

## Regional and postage limitation discovered

740/1,083 sold rows have recorded postage at least as high as the item price;
median recorded postage is GBP 6.76. All contain a shipping value, including
168 zeros. This alone does not establish that a listing is overseas.

The current eBay importer sets `source_country="GB"` from its eBay GB request
and does not preserve seller/item location fields in those observation metadata.
The benchmark therefore measures **stored eBay GB marketplace observations**,
not an independently verified UK-domestic cohort. Do not infer seller country
from currency, hostname or postage. Source-location and shipping normalization
must be validated against actual permitted provider fields before treating these
results as a UK-domestic price accuracy claim.

## Connection and next implementation work

1. Preserve every accepted independent comparable and its original timestamp,
   exact edition/variant/physical basis, marketplace and available location
   evidence; retain permitted raw evidence in R2. Keep source observations
   immutable and existing ownership/financial authority in PostgreSQL.
2. Separate item-price, delivery-inclusive buyer cost and regional guide
   estimates. Use dated FX for EUR conversion. Keep Cardmarket's unspecified
   condition/language limitation explicit.
3. Compare the existing UK-only estimate against an evidence-weighted UK/EU
   candidate on a larger chronological holdout. Regional/location and exact
   physical-basis eligibility must be satisfied before blending.
4. Score per category, language, grade and price band. New manga/comic/figure
   sources need exact edition/box/variant matching and their own holdouts.
5. Promote a change only when independent validation improves accuracy without
   degrading coverage/matching. Store price and publication remain separate
   deterministic decisions. No arbitrary 60/40 source weighting is proposed.

No archive restoration, history deletion, DB-capacity bypass, provider purchase,
fresh scrape, source-rule relaxation, inventory/owner change, Store Price
change or Railway service change was performed by this diagnostic.

## Reproduce and validation

Export authorized normalized observations with the fields documented in
`backend/scripts/replay_pricing_accuracy.py`. Export `evidence_quality` as
its PostgreSQL numeric string or a JSON number; the CLI normalizes it.
Use the actual provider sale ID as `external_id` when available.
Set category to the collectible category, separating sealed from card games.
Keep raw exports private and outside version control.

```sh
PYTHONPATH=backend python backend/scripts/replay_pricing_accuracy.py \
  --input /private/normalized-observations.json \
  --category MANGA --category COMICS --category FIGURES --category SEALED
PYTHONPATH=backend python backend/scripts/replay_pricing_accuracy.py \
  --input /private/normalized-observations.json --price-basis delivered
PYTHONPATH=backend python -m pytest tests/test_pricing_accuracy.py \
  tests/test_pricing_engine.py tests/test_pricing_engine_hardening.py
```

Local validation: 37 tests pass, including the existing engine regression/stress
tests and new replay, leakage, duplicate, cross-product conflict, stale, physical
basis, absent-category, postage and PostgreSQL numeric-export tests.
GitHub CI is a separate gate. No production accuracy improvement is claimed.
Rollback is removal of the isolated offline module/script/tests/document.

