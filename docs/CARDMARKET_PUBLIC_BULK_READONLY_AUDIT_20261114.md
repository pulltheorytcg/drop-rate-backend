# Cardmarket official bulk feeds — read-only multi-game audit

**14 November 2026 | REVIEW ONLY | No production change**

## What this builds and why
Reuse the existing `app.cardmarket_public_pilot` strict date and Cardmarket-ID helpers to inspect official downloadable catalogue files and guide files. This adds **source-side coverage and corruption diagnostics** for Magic, Pokémon, Yu-Gi-Oh!, One Piece, and Lorcana (including the separate sealed/non-single product list). It does **not** create a competing pricing engine or infer a Drop Rate printing from a Cardmarket ID.

## Integration
- Official source download: `https://downloads.s3.cardmarket.com/productCatalog/` (two bounded unauthenticated GETs per manual invocation, with no redirects/retries).
- Existing code: `app.cardmarket_public_pilot` for checks, existing FastAPI sold-only pricing untouched.
- Supabase Pro is still the source of truth. No migration, credentials, DB writes, provider mappings, cards, inventories, market observations or store prices changed.
- No Railway service, scheduled job, n8n workflow, Shopify edit, R2/Cloudflare migration or external paid provider.
- The account's `tcg.provider_catalogue_mappings` had **zero Cardmarket mappings** on 14 November read-only SQL; therefore none of the source-side joins proves catalogue-level or physical-copy pricing coverage. Separately validate exact mapping by game, set, card number, variant, language, finish and source evidence before considering a future intake pipeline.

## Run manually (operator-controlled pilot)
```bash
PYTHONPATH=backend python backend/scripts/audit_cardmarket_bulk_feed.py --game pokemon --kind singles --read-only
PYTHONPATH=backend python backend/scripts/audit_cardmarket_bulk_feed.py --game magic --kind nonsingles --read-only
```
Allowed game keys: `magic`, `pokemon`, `yugioh`, `one_piece`, `lorcana`. Per game product IDs: 1, 6, 3, 18, 19 respectively. Reconfirm file links and category IDs against Cardmarket's download page before any production scheduler is approved.

The command prints **counts, createdAt timestamps, SHA-256 hashes and byte sizes only**. It deliberately neither reports guide amounts nor returns matched physical card identities. `source_id_intersection_count` is *not* market-price coverage; it counts Cardmarket provider IDs occurring in both Cardmarket exports, not matched Drop Rate printings. Price guide records are statistical regional aggregates, not independently verified individual completed sales.

## Failure modes and protections
- Unknown game/format, duplicate or malformed ID, inconsistent category, unknown schema version, future/stale source timestamp, conflicting feed dates, HTTP error, redirect, invalid JSON and files over 64 MB all fail closed.
- No source-specific finish, condition, language or grade is assumed from a Cardmarket aggregate. No alt-art/reprint/slab/foreign-language match is inferred.
- Cardmarket's publicly downloadable data is not a licence to republish prices: see https://help.cardmarket.com/en/general-terms-and-conditions section 9, which requires prior written agreement for external presentation in the API context. Clarify direct-feed commercial display and downstream use with Cardmarket in writing. Preserve `commercial_display_permission=NOT_VERIFIED` until then.
- The existing `DROP_RATE_CATALOGUE_BULK_HOLD` and permissions gates remain unchanged. **Never promote a source guide, active listing or per-game ID overlap into `Market Value`.**

## Tests and release gates
Run `PYTHONPATH=backend pytest -q tests/test_cardmarket_bulk_feed_audit.py`. Mocked network and fixture tests cover each allowed game, sealed format, malicious/malformed IDs, duplicate source IDs, mismatched categories, stale dates, unknown export version, rogue guide prices, redirects, byte ceilings and no publication. Full CI, official live feed receipts and written source-rights decision are separate release gates. No automatic deployment or changes to customer-facing prices are authorised.

**Rollback:** close/revert this isolated PR. No database rollback is necessary.
