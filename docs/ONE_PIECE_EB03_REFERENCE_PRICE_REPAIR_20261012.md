# Existing Cardmarket source repair: One Piece Heroines Edition EB-03

Date: 12 October 2026

## 1. What is built

A narrow, code-gated alias for the English official EB-03 title, `EXTRA BOOSTER -ONE PIECE HEROINES EDITION- [EB-03]`, to the first-party Cardmarket lots label `Heroines Edition (EB03)`. The mapping requires **both** the specific full release title and printed code `EB03`.

No source provider is added. The existing `one_piece_market.matched_products` matcher still requires:
- `Punk Records` / `Bandai Official`, English language and the exact One Piece system;
- a unique source-side printing ID, name and collector number for the release;
- a uniquely identified Cardmarket English expansion supported by its lots checklist;
- exactly one product with the same printed name and collector number in that expansion, even if other regional expansions contain another such product;
- a current, valid Cardmarket category/price with EUR-to-GBP ECB conversion.

A unique product is not a verified physical condition, grading company or independent exact sales sample. Stored quotes are **mixed-language/condition reference guides**, never graded or auto-publishable sold valuations.

## 2. Why this matters

The existing release-title matcher returned `('onepieceheroinesedition','EB03')`; Cardmarket publishes the English set as `('heroinesedition','EB03')`. Consequently **none** of 90 EB-03 English card references had a current cached GBP guide.

A bounded one-shot replay of the 12 October official published product and price guide files against the **90 existing public Supabase EB-03 reference identities** returned:
- Before scoped alias: **0** product matches;
- After scoped alias: **44** matches;
- 44 have a published source `trend` field;
- 46 remain unmatched because of ambiguous printings or missing matching products, and must stay without a fabricated price;
- Every new match uses Cardmarket English expansion `6449`; the separate Asia-region expansion `6379` is never selected;
- Previously matched product IDs did not change.

This is a verified **read-only replay**, NOT evidence of 44 rows already persisted to production. The official product exports were dated **11 October 2026**; the pricing download was dated **12 October 2026**.

## 3. Connections and guarded operation

`backend/app/one_piece_market.py` -> existing official Cardmarket daily JSON catalogue and pricing exports -> existing FastAPI deterministic adapter and FX conversion -> existing `tcg.reference_market_prices` price/history trigger -> existing shared catalogue browser and Seller Hub reference price APIs. The unchanged `tcg.catalogue_products` remain canonical for actual owned items.

The existing reference job revision changes from **7 to 8**, so the next normal catalogue-maintenance worker tick rechecks Cardmarket and writes only eligible source-reference guide rows with their exact recorded identity. The existing separate inventory/market snapshot calculation is called by the same worker. It must **not** overwrite owner Store Prices or silently qualify special cards for automatic Shopify publication. Since no currently owned physical cards map to EB-03 according to the read-only inventory query, no immediate inventory price lift is claimed.

The existing paid eBay sold-data *social research probe* was inadvertently run on every Railway pre-deploy despite a Trawl rate/credit-limit error. It is now **opt-in** via `DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN=1` for an explicitly approved one-off call; its default execution reports SKIPPED and makes no Trawl/FX calls. The existing actual eBay market refresh still observes its global 429 backoff and cached sold-data rules. This change does not restore the exhausted sold-provider credit balance.

## 4. Potential failure points

- Incorrect regional expansion, name/number/variant collision, missing/invalid marketplace quote, nonpositive converted price or provider outage: reject the reference rather than guess; old historical market observations remain immutable.
- Expired price metadata: shared UI must show missing/stale, not a fresh quote.
- Worker restart during backfill: existing advisory lock and idempotent cache/upsert; no duplicate inventory records.
- Deploy probe disabled by default: researching eBay sold evidence requires **explicit opt-in**; not a full eBay pricing disable.
- No data source for many Japanese, Naruto or rare cards: remain unpriced, no Collectr redistribution and no TCGGraph integration.

## 5. Verification

- Public provider replay: 0 -> 44 unique product matches, 44 source prices present, only English expansion 6449, original matches preserved (GitHub Actions workbench run 38319672129).
- Regression tests: EB-03 exact English mapping, unrelated release-code exclusion, region exclusion, wrong name/number/provider/language, ambiguity and multi-product conflicts, deterministic GBP conversion, global reference writes only and no inventory/Shopify writes.
- eBay probe tests: default no paid calls even with credentials present; deliberate one-off opt-in with no credentials stays blocked.
- Full backend and dashboard JavaScript checks, existing PostgreSQL tests, pre-deploy and production health, then **read-only production coverage receipts before and after** (actual delta recorded in release comment).

No new service, paid subscription, source-provider licence change, secrets, schema/DDL or n8n workflow.
