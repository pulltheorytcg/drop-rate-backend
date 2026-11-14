# 14 November 2026 — Cardmarket source-locked 8,307-record catch-up

## What and why
The first 100 and subsequent 500 source-qualified Pokémon records are now present in Supabase Pro, with a one-to-one append-only history row and no inventory/Shopify/owner mutation. The existing RLS-protected worker already supports 500-reference commands, but it would require 17 more manual deployments and re-download Cardmarket twice each time.

This change **only orchestrates** reuse of the existing exact ID matching, GBP conversion, RLS importer, immutable history and source permission. No new pricing engine, database migration, connector, scraper or public API.

## Connections / released proof
- Production 14 November full read-only verified Cardmarket source, [run #43607783746](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/43607783746): 8,907 eligible canonical English Pokémon references, 13,703 finish-specific guide averages and 14,506 broader review candidates. Preserve approved product/guide/canonical crosswalk SHA-256 digests as explicit release invariants.
- Production Supabase readback after initial batches: 600 current, 600 history, 918 GBP quotes, no changes to 621 physical inventory rows / 244 existing valued copies / £1,386.88 aggregate seller Store Prices.
- Production source actor still uses existing `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID` with `user_connection` and `require_platform_admin`. There is no bypass of RLS. The existing `DROP_RATE_CATALOGUE_BULK_HOLD` remains active.
- `--apply --max-references 500 --start-index 600 --end-index 8907` runs up to 500 references per mini-batch, reusing the same official file download and ECB price normalisation once. Requires both `DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED=YES` and `DROP_RATE_CARDMARKET_FULL_APPLY_CONFIRMED=YES`.
- No daily cron or new provider workload; the one-off service has `restartPolicyType=NEVER`, no domain, no volume, <=1 vCPU/1 GiB and commit SHA pinned.

## Failures and tests
Fails closed before any remainder writes if game/source guide files change, canonical crosswalk digest changes, unexpected candidate/reference/variant counts, missing operator gate or wrong cursor. Stops subsequent chunks immediately if any individual RLS append, identity or expiry check is blocked. Each past completed chunk is safe on re-entry because history has a SHA-based unique key and source-specific quote replacement is idempotent.

Run `PYTHONPATH=backend pytest -q tests/test_cardmarket_approved_remainder.py tests/test_cardmarket_bulk_crosswalk.py tests/test_cardmarket_bulk_context.py tests/test_cardmarket_bulk_persistence.py` plus full backend, dashboard and n8n CI. Monitor actual `tcg.reference_regional_price_context` and `..._history` row counts per chunk. Do not claim completion until both independently report 8,907 and exactly reviewed source provenance.

**Limitations:** EU seven-day price guide aggregates, not UK completed individual sales, not specific condition/language or PSA slabs. This fixes source-qualified catalogue context, not seller Store Prices or physical Market Value. Separate official-source crosswalk is needed for One Piece, Dragon Ball, MTG, Yu-Gi-Oh!, Lorcana and other newly added products.

## Rollback
Stop one-off worker; revert UI/source adapter if needed. Historical observations are append-only, never deleted. All physical/Shopify/financial fields remain untouched.
