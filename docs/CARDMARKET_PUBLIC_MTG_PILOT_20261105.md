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


## Verified bounded real export result — 5 November 2026

- GitHub Actions **Cardmarket official daily guide read-only MTG pilot** workflow run **42093048789** succeeded using **the official, unauthenticated 5 Nov 2026 public snapshots** and ECB FX. Unit tests and real download both passed.
- **125,365** Cardmarket Magic singles product records and **130,534** price-guide records read; **771** MTGJSON Foundations English paper source cards had unique cross-provider `mcmId` product IDs, with **zero** duplicated crosswalk IDs.
- The numeric `idExpansion` cohort gate accepted **4** separately corroborated expansion groups and produced **1,164** *finish-specific GBP guide candidates* (not distinct sold cards, not physical stock, not verified transaction-based market values). Each candidate was generated from an exact provider product ID, a matching literal card name and the appropriate guide finish. **Zero inter-set expansion conflicts** were detected within this single-set pilot.
- Rejections: **1** name disagreement (must stay rejected), **2** insufficiently proven expansion identities (must stay rejected), and **11** unavailable eligible finish-specific guide prices. These are counts of rejected source/finish checks, not necessarily distinct collectible products.
- Snapshots: Cardmarket guide `createdAt=2026-11-05T01:49:44+00:00`; product file **20,846,474 bytes**, SHA-256 `b5bc92baae1c6b4481f82fae3960d44606b402e8c5de5cfcbbb6f579c7242355`; guide **26,566,077 bytes**, SHA-256 `09f09ab2c1f2a59b739ff58e673e2b3fdeff5f6424ccf157c4d21e02677ba7ff`; MTGJSON Foundations **4,922,572 bytes**, SHA-256 `f0e0cc0e12c7916506f65e7325d8deb36c0f0893f3710c1b64bc98d212f8ab77`.
- Audit result: `PILOT_ONLY_NO_PUBLICATION`, **zero** verified UK individual sold comparables, **zero** Supabase/R2/Shopify writes; no public API route, no new user-visible market values, and no change in reported global genuine market-value coverage.

**Limitations for scaling:** This pilot examines one MTGJSON set; a multi-set candidate registry must refuse any reused Cardmarket expansion ID that maps to conflicting sets and retain its own exact ID/finish evidence, release-date gate and rights review. `mcmId` itself is an original source cross-ID, not independently validated permission to advertise Cardmarket's pricing data as a precise condition/grade-specific market value. Extend to Yu-Gi-Oh! and Lorcana only after verifying each game's exact printing/product ID relationships; published metadata counts are not market-coverage claims.
