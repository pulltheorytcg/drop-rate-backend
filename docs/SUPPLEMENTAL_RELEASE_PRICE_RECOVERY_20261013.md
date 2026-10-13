# Expansion and deck pricing recovery — revision 20

Several complete card checklists were missing guide prices because their release labels were outside the existing booster/starter parser. The connected first-party Cardmarket export already supplies eligible prices for these releases.

## Repair

- Dragon Ball Masters: exact official titles and number families for 25 expansion/anniversary releases (EX01–EX25) and three expert decks (XD1–XD3), independently corroborated by the named Cardmarket packaging category and release ID. The 2024 premium anniversary label explicitly matches Cardmarket's “Premium 7th Anniversary Box 2024”. Versions of the 2019, 2020 and 2021 boxes corroborate only the shared release.
- One Piece: nine exact official ST10/12/13/15/17/19/20/21/22 deck labels, including Ultra/Ultimate naming, colour-prefix differences, Zoro and Sanji, EX Gear 5 and EX Ace & Newgate. Each alias requires its full official title and ST code; no general stripping of colours, regions or EX text.
- Every match still requires one unambiguous official card and one Cardmarket product. Masters EX/XD parallel suffixes also participate in number collision detection, including differently named parallels. Conflicting release IDs and unpriced duplicate products block matching.
- Prices retain the source's original timestamp, EUR amount, ECB GBP conversion and full reference identity. New quotes are explicitly reference-only, with separate match bases and `physical_valuation_eligible=false`. No new providers, credentials, schema or services are required.
- Existing daily reference maintenance advances from revision 19 to 20. Provider outages leave prior dated evidence untouched.

## Predeployment evidence

First-party exports replayed from `https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_13.json`, `products_nonsingles_13.json`, the corresponding game-18 exports, and `priceGuide/price_guide_13.json` / `price_guide_18.json` against complete imported reference checklists:

| Scope | Reference records checked | Unique matches with positive source quotes |
|---|---:|---:|
| Masters expansion/anniversary/expert releases | 526 | 396 |
| One Piece deck aliases | 194 | 75 |
| Total | 720 | 471 |

These are replay candidates. Production gain must be measured after the revision-20 job completes.

Source-aware production baseline: **39,204 / 69,538** reference cards have supported GBP values/guides. **27,854 / 67,058** physical references remain unpriced; 2,480 digital Pocket references are explicitly N/A. Masters English **4,020 / 9,002**; One Piece English **2,123 / 4,527**. Physical inventory: 614 records, 327 stored values. The predeployment owner/status/Store Price fingerprint is `de5af2619bdfbc03127b64c179df03c5`, computed with ordered newline-separated `concat_ws('|',id,owner_id,status,store_price_minor)`.

## Acceptance

Regression tests cover actual source labels, all nine deck aliases, wrong regions/years/game/number families, parallel and unpriced duplicates, conflicting expansions, dated GBP quote persistence and outage preservation. Existing full unit and PostgreSQL CI suites, successful deployment, completed refresh and independent source-aware coverage readback are required before claiming a live gain.

Local validation: **5,805 tests passed**, including 29 new regressions; Python compilation and whitespace checks passed. One existing Starlette/AnyIO deprecation warning remains.

This repair supplies catalogue references; it does not create exact-language, graded or condition-specific sold evidence for physical inventory. Remaining provider mapping/source gaps are tracked in `PRICING_RECOVERY_LIVE_RESULTS_20261013.md`.
