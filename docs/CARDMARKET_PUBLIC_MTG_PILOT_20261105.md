# Cardmarket public daily export: exact-ID Magic feasibility pilot

**5 November 2026; disabled by design and non-publication.**

## What and why
Cardmarket announced that its once-daily public product catalogue and price guides are available without restricted API access ([official announcement](https://news.cardmarket.com/en/Magic/were-making-the-price-guide-and-product-catalogue-available-for-download)). Start with a **source-provenance-only** Magic pilot because MTGJSON's `identifiers.mcmId` links to a Cardmarket product ID ([schema](https://mtgjson.com/data-models/identifiers/)). There is no name-only fallback and no paid API or scraping. These feeds are **statistical guides, not verified UK completed-sale observations**.

## Connected existing components
- R2-first Magic canonical IDs are `mtgjson:<uuid>:<finish>`. Existing published Magic data does not include `mcmId`, so an external, separately reviewed UUID→MCM-ID crosswalk must be computed from the original upstream metadata. The pilot takes original metadata as input and **does not change R2 partition formats**.
- Product catalogue `products_singles_1.json`, daily guide `price_guide_1.json`, both separately fetched/validated in a controlled import process. The pilot assumes their expected `createdAt`, `products` and `priceGuides` fields only from documented public examples; a **live schema/readback** is still required before any full ingest.
- Same product ID must agree in MTGJSON, Cardmarket product catalogue and Cardmarket guide. Exact name, set and normal/foil treatment must match. Normal uses `trend`/`avg30`, foil uses `trend-foil`/`avg30-foil`; etched and uncertain versions are excluded. ECB's historical EUR→GBP quote is mandatory.
- No current market price can be asserted for physical ownership, grading/condition, Japanese cards, sealed products or seller asking/sales. A partial source guide is never proof of UK sold market value.

## Guarantees and limitations
- `backend/app/cardmarket_public_pilot.py` accepts **already provided** provider payloads and exact MTGJSON metadata. It never executes HTTP, SQL, storage, Shopify or payment code. Source timestamps older than 3 days and cross-source date/FX disagreement are refused.
- Every output is `PILOT_ONLY`, `publishable=false`, `physical_valuation_eligible=false`, `sold_observation_count=0`. There is deliberately no `market_value_minor` key or API response route. Conflicting shared Cardmarket IDs are quarantined, not selected by lowest price.
- Commercial redistribution/display rights for these downloads have not yet been verified against applicable Cardmarket terms; publication remains disabled.
- Other games (Yu-Gi-Oh!, Disney Lorcana, Riftbound) need their own **exact approved** product-ID crosswalk. No invented IDs, game-number matching, or fresh valuation coverage is claimed.

## Tests and next checks
Run `PYTHONPATH=backend python -m pytest -q tests/test_cardmarket_public_pilot.py`. Tests cover correct distinct finishes, duplicate price rows/IDs, name/set mismatches, nonpaper cards, ambiguous MCM crosswalks, stale/future files, FX rejection, invalid prices, preservation of original inputs and no production pricing writes.

**Next gate**: bounded official export live-read on an isolated runner (no database credentials); SHA/date/schema receipt, crosswalk yield and rejection counts, rights validation, then a separate reviewed R2 sidecar proposal with live-read parity and a release switch. No SQL capacity bypass; existing PostgreSQL/R2 ownership and media rules are unaffected.


## 5 November live pilot and expansion evidence correction

An actual GitHub Actions read-only download on 5 Nov reached the current Cardmarket Magic `products_singles_1.json` and `price_guide_1.json` and the MTGJSON Foundations set. The first strict result had **771/771 exact `mcmId` source-product links**, but zero accepted candidates: **770** were rejected solely because the public singles product file does not provide the assumed `expansionName` field, and **one** name mismatch was observed (`Vivien Reid Emblem` against MTGJSON `Vivien Reid`). The latter must remain rejected; no blanket suffix-stripping is permitted.

The public product file does contain a numeric `idExpansion`. The pilot now accepts a **numeric set cohort only when eight different card names independently agree** on (1) exact MTGJSON `mcmId` → Cardmarket `idProduct`, (2) identical card name, (3) the same MTGJSON release, (4) the same positive Cardmarket `idExpansion`, and (5) no other observed MTGJSON set mapped to that expansion. A contradictory explicit `expansionName` always rejects, even if the cohort agrees. Weak/coincident identifiers, name-only matches, duplicated names, zero/unknown expansion IDs and ambiguous inter-set expansion IDs fail closed.

Even a successful cohort remains **only a pilot indicator**, not independently certified official set-name equivalence across every set. A production valuation adaptor would require a full multi-set crosswalk, independent released-set verification, provider rights and price-source classification. Statistical price-guide candidates remain `PILOT_ONLY_NO_PUBLICATION`; all outputs have `sold_observation_count=0`, no `market_value_minor`, no owner-grade/condition match and **zero production writes**.
