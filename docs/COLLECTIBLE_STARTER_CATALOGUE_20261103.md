# Sports Cards and Figures: reviewed starter catalogue

Reviewed on **3 November 2026**. This is a six-reference metadata starter for the new Sports Cards and Figures search categories. It is deliberately small; manual entry remains available for items outside this coverage.

## Exact references

| Category | Reference | Edition identifiers | Scope |
| --- | --- | --- | --- |
| Sports Cards | Bukayo Saka, Arsenal | Topps Premier League 2025/26, Base Players #12 | English catalogue scope |
| Sports Cards | Cole Palmer, Chelsea | Topps Premier League 2025/26, Base Players #100 | English catalogue scope |
| Sports Cards | Mohamed Salah, Liverpool FC | Topps Premier League 2025/26, Base Players #174 | English catalogue scope |
| Sports Cards | Erling Haaland, Manchester City | Topps Premier League 2025/26, Base Players #195 | English catalogue scope |
| Figures | Hatsune Miku, Nendoroid 3.0 | Good Smile product 1136133; JAN 4571697188655 | Standard individual figure; February 2026 |
| Figures | Hatsune Miku, Nendoroid 3.0 [Basic] | Good Smile product 1139898; JAN 4580828662797 | Separate Basic individual figure; February 2026 |

The Topps records have `parallel=Base` and no stated print run. Autographs, relics, numbered parallels, other subsets and other language editions are separate identities. Team names come from the season checklist rather than the athletes' current teams.

The two Miku entries are distinct. Basic omits the standard optional parts and additional face plates; neither entry represents the six-figure Piapro Characters Special Box or guarantees a retailer bonus. Manufacturer SKU, exact retail release day and release region remain unknown. Figure language is not assigned. The official shipment notice supports February 2026 and the two JANs; it explicitly says retail dates vary by location.

## Source provenance

Every manifest entry includes the official URL, review date, supported fields and a page/section locator. No retail price or artwork is copied into the catalogue.

- [Topps Premier League 2025/26 official checklist page](https://www.topps.com/pages/checklists/topps-premier-league-2025-26) links the [official Hobby checklist PDF](https://cdn.shopify.com/s/files/1/0739/2015/1805/files/Topps_Premier_League_2026_Hobby_Checklist.pdf?v=1756731624). PDF pages **1–4**, respectively, establish the four numbers, surnames, printed teams and Base Players subset. The rendered pages were visually checked alongside extracted text.
- [Topps UK Hobby product](https://uk.topps.com/products/topps%C2%AE-premier-league-2026-hobby-box) lists **Product Year 2025**, Topps, Premier League and Football. That supports `release_year=2025` even though the product title and PDF filename contain “2026”. The Hobby box SKU and release day are not assigned to individual cards.
- Full names are corroborated by official club pages for [Bukayo Saka](https://www.arsenal.com/news/bukayo-saka-signs-new-long-term-contract-aFcin3f65ht4), [Cole Palmer](https://www.chelseafc.com/en/teams/profile/cole-palmer), [Mohamed Salah](https://www.liverpoolfc.com/info/mohamed-salah) and [Erling Haaland](https://www.mancity.com/news/mens/erling-haaland-manchester-city-transfer-complete-63790702).
- The [Good Smile 3.0 product](https://www.goodsmile.com/en/product/1136133/Nendoroid%2BHatsune%2BMiku%2B3.0) and [3.0 Basic product](https://www.goodsmile.com/en/product/1139898/Nendoroid%2BHatsune%2BMiku%2B3.0%2BBasic%2B) provide the manufacturer, series, editions, Nendoroid line, non-scale specification and release month. The [official feature page](https://info.goodsmile.com/sp/nendoroid_hatsunemiku_3/en/) distinguishes the editions and the special box.
- [Good Smile's February 2026 release notice](https://www.goodsmile.com/en/news/6706) lists the standard and Basic titles with their separate JANs under the 19 February shipment group. The seed records the month, not a universal retail release date.

English on the four sports references denotes the English UK checklist scope. The source does not prove the language, condition, authenticity or parallel of any collector's physical copy. Those still require the existing intake and verification workflow.

## Storage and safety

The data lives in `backend/data/collectible_catalogue_starter_20261103.json`. The renderer is `backend/scripts/seed_collectible_catalogue.py`.

The renderer validates the app's `SportsCardCreate`, `FigureDetailsCreate` and canonical catalogue fields. It uses the separate `official-collectible:v1:` namespace and deterministic UUIDs derived from stable official source IDs. Website product IDs are provenance, not manufacturer SKUs.

Profiles use the existing **VERIFIED** enum, `identity_source=OFFICIAL_CATALOGUE` and `verification_scope=OFFICIAL_REFERENCE_METADATA_ONLY`. This verifies a reference edition's metadata. It does not set a physical item's `identity_confirmed`, approve a listing, approve media rights or assert a valuation.

Reference insertion is atomic and append-only. Once every reference passes validation, the same transaction updates each seeded category's metadata to `reference_catalogue_available=true`, `reference_catalogue_coverage=STARTER_METADATA` and the actual count of verified official references. Other taxonomy metadata is preserved:

- An identical replay makes no product, profile, coverage or timestamp changes.
- Changed existing metadata causes a review error rather than an overwrite.
- An equivalent identity under another key, including an unreviewed seller entry, causes the whole batch to roll back. It is never merged, promoted or reassigned automatically.
- Short transaction and lock timeouts limit the import. A brief table lock prevents a concurrent manual insert from racing the identity check.
- Inventory, ownership, quantities, prices, artwork and storefront publication are untouched.

The Sports/Figures schema migration (`20261103145218_seller_sports_figures_intake.sql`) must be applied before this seed. The reviewed catalogue visibility migration and matching backend/frontend release must also be present. A failed seed leaves category availability metadata unchanged.

## Render and verify

From the repository root, render reviewable SQL without connecting to a database:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/seed_collectible_catalogue.py > /tmp/collectible-starter-20261103.sql
```

Apply reviewed SQL through the normal database release procedure. This document and renderer do not apply it to a hosted environment.

Local checks:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_collectible_catalogue_seed.py
node tests/collectible_catalogue_seed_pglite.mjs
```

The Python tests check exact editions, explicit unknowns, canonical fields, source origins, dates, duplicate keys and rejected stock/price/artwork input. The PGlite test executes the actual schema migration, validation trigger and generated seed in disposable PostgreSQL. It verifies six inserts, accurate category counts, unchanged replay, changed-reference refusal, atomic rollback on a seller-entered collision (including coverage metadata), and unchanged stock, price and media records. No hosted database or provider is contacted by either test.
