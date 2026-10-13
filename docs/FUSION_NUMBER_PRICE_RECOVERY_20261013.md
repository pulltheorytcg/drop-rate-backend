# Fusion World exact-number guide recovery

After PR #627, production has 34,730 priced references out of 69,538. English
Fusion World has only 730 of 4,360 priced. The general matcher rejects a repeated
character name even when both sources explicitly identify different collector
numbers. For example, Gowasu FB01-040 and Gowasu FB01-041 have separate Cardmarket
products 756881 and 756882 in the exact Awakened Pulse expansion 5552.

The additional reference-only matcher uses the existing full official and
Cardmarket checklists. It requires exact game, English release, full name and
collector number, one official printing per number and one market product per
expansion/number. Every source row with the number contributes to collision
checks, including unpriced variants, other names and unsupported suffixes.
Only the official base `set_id:card_number` identity qualifies. Masters and
Japanese guides keep their existing source rules. The previous matcher stays
unchanged, and the new quote basis is excluded from physical-copy valuations.

No new data provider, service, paid calls, schema, inventory or Store Price
mutation is introduced. The same daily worker and downloads run revision 15;
receipts report numbered recoveries, positive prices and conflicts. Old evidence
and immutable history remain intact. Roll back code through the normal PR path;
do not delete observations.

Read-only replay against 13,362 English Dragon Ball references and the 13 October
Cardmarket products / 12 October guide identifies **475 additional exact matches**
and **422 previously unpriced positive guide candidates**. The exploratory count
of 457 excluded fewer printing IDs; the production rule deliberately rejects
35 of those. No price is guessed from another collector number or parallel.

| Official release | Candidate prices |
|---|---:|
| FB01 | 51 |
| FB02 | 60 |
| FB03 | 38 |
| FB04 | 26 |
| FB05 | 33 |
| FB06 | 26 |
| FB07 | 20 |
| FB08 | 40 |
| FB09 | 43 |
| FB10 | 45 |
| Manga Booster SB01 | 18 |
| Manga Booster SB02 | 22 |
| Total | **422** |

Regression checks cover independent same-name numbers, official/market duplicate
printings, mismatched names, suffixes, languages, providers, releases and regions.
The worker persistence test confirms GBP conversion, original reference identity,
the reference-only quote basis and physical-valuation rejection. The full backend
suite passes **5,675 tests**. Release acceptance requires all current-head CI,
Railway readiness, revision-15 completion, actual source-aware price delta and an
unchanged physical inventory ownership/Store Price fingerprint.

This does not close the remaining source-access, exact-quote and printing-mapping
gaps. Source guides remain estimates, separate from five-sale market valuations.
