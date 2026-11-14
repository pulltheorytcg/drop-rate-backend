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
- Cardmarket explicitly authorised incorporation of its direct public-download product and price data into applications on 15 July 2025; this is distinct from restrictions on use of the *authenticated API*. Source provenance and precise scope remain important. See the continuation below. Preserve `commercial_display_permission=NOT_VERIFIED` until then.
- The existing `DROP_RATE_CATALOGUE_BULK_HOLD` and permissions gates remain unchanged. **Never promote a source guide, active listing or per-game ID overlap into `Market Value`.**

## Tests and release gates
Run `PYTHONPATH=backend pytest -q tests/test_cardmarket_bulk_feed_audit.py`. Mocked network and fixture tests cover each allowed game, sealed format, malicious/malformed IDs, duplicate source IDs, mismatched categories, stale dates, unknown export version, rogue guide prices, redirects, byte ceilings and no publication. Full CI, official live feed receipts and written source-rights decision are separate release gates. No automatic deployment or changes to customer-facing prices are authorised.

**Rollback:** close/revert this isolated PR. No database rollback is necessary.


## 14 November continuation — live, exact-identity price preparation (still draft)

The founder expressly requested increasing missing catalogue market reference coverage, instead of indefinitely protecting empty values. Accordingly the implementation extends beyond read-only audit, but remains gated so incorrect provider aggregates cannot be represented as individual UK sale evidence.

### Verified actual public downloads (GitHub Actions #43603764641)

| Game | Product IDs in both official public product and guide files |
| --- | ---: |
| Pokémon | 75,731 |
| Magic | 125,485 |
| Yu-Gi-Oh! | 87,771 |
| One Piece | 12,736 |
| Lorcana | 3,691 |
| **Total source-side intersections** | **305,414** |

**These are Cardmarket-to-Cardmarket feed joins, not priced Drop Rate canonical references.**
The existing MTGJSON/Cardmarket Foundations pilot separately returned 738 accepted Cardmarket product IDs and 1,145 finish-specific guide candidates. No pricing records were inserted.

Read-only production Supabase queries discovered 30,425 Pokémon references with candidate Cardmarket links in historical TCGdex/CardTrader data, and 345 Cardmarket IDs shared by two different canonical references within the direct TCGdex cohort. A further one-to-one-source-ID query found 11,631 English and 9,578 Japanese reference IDs with no source-ID reuse. These are **potential candidates**, not validated full matches. Conflicted source IDs are quarantined.

The independently tested 28-item Fusion Strike canary verified exact sourced Cardmarket IDs against the current feed: 28 source/finish matches, 0 rejected. The first live failures exposed the accented official `Pokémon Single` category and Cardmarket's bracketed move names; both are now handled only when an independently existing exact source ID is present. The code never uses that normalization to infer a product ID by name.

### Rights distinction, corrected from earlier assumptions

Cardmarket's 15 July 2025 public-download statement explicitly says anyone can import and incorporate its downloadable product catalogue and price parameters into their applications without additional access or permission: https://insight.cardmarket.com/en/Articles/scryfall-x-cardmarket . The general terms' section 9 separately limits the **restricted account API** and requires prior agreement for certain API uses: https://www.cardmarket.com/en/Pokemon/Policies/GeneralTermsAndConditions/GB . This source distinction is documented; no signed-in, restricted API or resale of personal seller data is used. The TCGdex-derived Cardmarket/TCGplayer commercial redistribution policy flags remain **disabled**; direct first-party Cardmarket bulk is separately granted a narrowly scoped contextual display permission.

### Implemented components (pending review)

- `app.cardmarket_bulk_crosswalk`: existing, source-ID-backed canonical set/name/number/variant/finish matching, numeric cohort safeguards, collisions, and explicit rejection reasons
- `app.cardmarket_bulk_context`: only direct exact-variant seven-day **aggregated European sales** averages, not active low/retail. Historical official ECB EUR/GBP FX with source timestamp, source file hashes, observed timestamp, mixed-language/condition cautions and no grade authority. No individual UK sold claims
- `app.cardmarket_bulk_persistence`: bounded manual import (1–500 canonical reference keys per invocation) into existing Supabase `reference_regional_price_context` plus append-only `reference_regional_price_history`, with PostgreSQL RLS founder-admin verification, per-key locking, source-specific replacement, lease and identity isolation, source-age expiry and idempotent history. No DB migration
- `scripts/pilot_cardmarket_live_crosswalk.py`: existing maintenance-actor identity, explicit `--read-only` mode and separately gated `--apply --max-references 100 --start-index 0`. Apply requires the explicit environment approval `DROP_RATE_CARDMARKET_BULK_APPLY_CONFIRMED=YES` **after a real backup/restore verification**, code review and CI. No new Railway service, scheduler or paid API
- Existing catalogue browser bounded RLS lookup and regional-source renderer: qualifying cached price signal shown as **"Market value (Cardmarket EU 7-day sales average)"** with individual normal/reverse variant distinctions and date. This is a source-qualified European catalogue reference, never a claim about the condition/grade of a specific physical item. No raw guide price is permitted to overwrite physical owner, checkout, Shopify Store Prices or settlement values
- Full test additions: malformed/corrupt/stale feeds, source collisions, altered names, explicit/ambiguous sets, actual official canary, ECB timestamp/FX, invalid amounts and source scope, RLS transaction, immutable append-only history, and failure before any unrelated price/owner change.

### Release conditions, verification and failure handling

1. Full GitHub CI including real PostgreSQL RLS and UI passes on the **final PR commit**; live official source receipts are dated, and no sensitive inventory/owner data leaks in CI logs
2. Read-only full-source crosswalk runs with the existing maintenance actor. Record exact accepted reference/finish counts, per-game/language totals, excluded ambiguous IDs and digest; prove no mixed condition/language premium is claimed
3. Verify Supabase Pro backup **restore**, not merely a backup entitlement, and confirm `DROP_RATE_CATALOGUE_BULK_HOLD` and unrelated schedules unchanged
4. Run an operator-authorized, bounded **100-reference apply** only; verify exactly that many source-specific history/current rows, check idempotent repeat, three real mobile catalogue lookups, no owner/Store Price/Shopify changes, old UK sold values and past evidence untouched
5. Only after the pilot receipt, scale in 100–500-reference batches with source freshness/expiry and automatic failure-stop. Separate rollout for Yu-Gi-Oh!, Lorcana and One Piece requires first-party exact printing crosswalks, not game-wide source product overlap
6. **No actual production write, deployment, new scheduler or measured post-application coverage improvement has yet occurred from this draft.** No claim that 21,209 or 305,414 Drop Rate records are priced is permitted

Rollback: stop manual batches; keep existing historical observations append-only, disable direct-source permission or revert PR/backend to hide this optional regional context, preserve all owner/physical price data. No Cloudflare migration.
