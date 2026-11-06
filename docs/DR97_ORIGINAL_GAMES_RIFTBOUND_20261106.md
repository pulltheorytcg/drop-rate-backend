# DR-97 — Pokémon, One Piece, Dragon Ball, Naruto and Riftbound release monitors

**State 6 November 2026:** Five source-controlled n8n definitions, imported inactive until production API/CI and guarded activation pass.

## What and why

Drop Rate now has six R2-first release metadata scouts DR-96 (Yu-Gi-Oh!, Lorcana, Magic, sports and figures). The original four card games are **not** part of those R2-first metadata partitions; they already use the catalogue maintenance subsystem and its reviewed sources. DR-97 adds independent daily release-check schedules, but calls the existing Python catalogue importer, never duplicates source adapters, prices, inventory, Shopify listing or image publishing. Riftbound is a special permission-readiness monitor.

## Schedule and integration

| Game | n8n stable ID | Daily UK check | Existing backend sources |
|---|---|---|---|
| Pokémon | `DR97PokemonReleaseWatchV1` | 09:25 | `tcgdex` |
| One Piece | `DR97OnePieceReleaseWatchV1` | 10:25 | `punk`, `one_piece_official` |
| Dragon Ball (including existing Fusion World catalogue) | `DR97DragonBallReleaseWatchV1` | 11:25 | `dragon_ball_masters`, `dragon_ball_fusion` |
| Naruto | `DR97NarutoReleaseWatchV1` | 12:25 | `naruto_kayou`, `naruto_bandai` |
| Riftbound | `DR97RiftboundReleaseWatchV1` | 13:25 | No source access approved; **`AWAITING_RIOT_APP_APPROVAL`** only |

The signed route `POST /api/v1/automation/commands/catalogue/check-legacy-game-releases` checks an exact game enum and maintenance actor. For the original four it acquires the **same PostgreSQL advisory lock `847220092`** used by `catalogue_maintenance.daily_pass`, then checks admin access, database capacity and previously completed daily source receipts before invoking `sync_source` for the due game's reviewed providers. The result is `CURRENT`, `COMPLETE`, `ALREADY_RUNNING`, `DEFERRED_CAPACITY`, or `INCOMPLETE` (the n8n workflow routes an incomplete source to DR-90). n8n never chooses source URLs or source licences.

**Live operational blocker:** the existing production PostgreSQL/Supabase database was approximately **430 MB**, above the **400 MB safety limit**. Until the master operational schema/legacy catalogue migration removes this constraint, these workflows will report `DEFERRED_CAPACITY` with zero provider downloads or SQL bulk writes. They still run and show exactly why card coverage cannot progress. Do not bypass the limit by increasing a setting or deleting source evidence; migrate legacy reference data to verified R2/D1 with index/parity and rollback first. DR-97 does **not** accomplish that migration.

## Riftbound

Riot's official [Riftbound developer policy](https://developer.riotgames.com/docs/riftbound) and [API policy](https://developer.riotgames.com/policies/riftbound) require a written licence or approved app-specific Riot API key for app use. Digital assets must be delivered by Riot's API; unapproved third-party card-art/image sources must not be used. Therefore DR-97's Riftbound watch is **a configuration/permission status heartbeat**, not a source discovery spider, catalogue import or artwork publisher. It returns `AWAITING_RIOT_APP_APPROVAL` without external requests, and is upgradeable to an API-backed catalogue adapter only after legitimate approval and credentials and tests.

## Strict image and finance boundary

Release checks do not imply a correct print, variant, language, original owner photograph, grade, condition, market value or approved image reuse. n8n receipt check explicitly requires `artwork_published=false`, `shopify_updated=false`, and `ownership_or_price_changed=false`. Artwork mapping is a separate staged Cloudflare R2/D1 workstream. For graded physical inventory, only a reviewed photograph of the actual slab may satisfy listing image rules.

## Deployment, testing and rollback

- Unit tests: `PYTHONPATH=backend pytest -q tests/test_dr97_legacy_release_watch.py tests/test_n8n_workflow_registry.py`. Negative coverage includes wrong game and extra payloads, duplicate lock, 400 MB capacity deferral, already-fresh source, incomplete import, Riftbound zero-provider access, no false image/Shopify/price claims.
- n8n pinned CI: source hash/contract test, real n8n CLI import inactive, isolated SQLite backup and publication tests, adversarial source-drift/refusal, existing DR-90 and DR-96 regression suites.
- Normal merge installs these five **inactive** definitions; no activation until Railway API and n8n deployments succeed. Separate n8n service-only flag `DROP_RATE_N8N_LEGACY_SCOUT_PUBLISH_ON_BOOT=true` invokes `automation/n8n/ops/guarded-legacy-scout-publish.cjs` after an offline backup, exact source/DR90 hash and n8n 2.32.6 checks. The six previously running DR-96 schedules are untouched.
- Rollback: unpublish only the five DR-97 IDs with n8n's reviewed exact-ID CLI and backup. Clearing the on-boot flag does not itself unpublish persisted schedules. Existing daily maintenance, DR90 and DR94 remain unaffected.

Do not report “all card artwork complete” without real source image rights, bytes, exact print-to-image mapping and device verification.
