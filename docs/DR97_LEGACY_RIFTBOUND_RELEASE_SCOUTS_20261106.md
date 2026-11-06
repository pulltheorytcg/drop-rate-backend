# DR-97 — Automatic new-release checks for Pokémon, One Piece, Naruto, Dragon Ball and Riftbound

**6 November 2026.** This is a governed extension to the six already-active DR-96 R2-first metadata scouts. **Artwork is not automatically licensed or republished by a metadata check.**

## 1. What is built and why

Eight independent n8n workflows cover five games while using existing Drop Rate catalogue provider adapters. n8n signs and schedules each request. FastAPI verifies HMAC identity, selects a literal trusted source, checks the same advisory lock and daily due rule as `catalogue_maintenance.daily_pass`, checks actual PostgreSQL capacity, then calls only the matching pre-existing `sync_source` adapter. No new provider scraping, uncontrolled AI decisions or parallel database writers.

| Game | Source | Schedule Europe/London | Workflow |
|---|---|---|---|
| Pokémon | TCGdex | Daily 04:20 | DR97PokemonSourceScoutV1 |
| One Piece | Official | Daily 05:20 | DR97OnePieceOfficialSourceScoutV1 |
| One Piece | Punk | Daily 06:00 | DR97OnePiecePunkSourceScoutV1 |
| Dragon Ball (including Masters) | Masters | Daily 06:40 | DR97DragonBallMastersSourceScoutV1 |
| Dragon Ball (including Fusion World) | Fusion World | Daily 07:20 | DR97DragonBallFusionSourceScoutV1 |
| Naruto | Kayou | Daily 08:00 | DR97NarutoKayouSourceScoutV1 |
| Naruto | Bandai | Daily 08:40 | DR97NarutoBandaiSourceScoutV1 |
| Riftbound | Official Riot access readiness | Daily 09:20 | DR97RiftboundRiotSourceScoutV1 |

Each definition ships `active:false`, retains DR90 error routing, and has its own repeatable stable workflow ID.

## 2. What connects to what

`n8n DR97 → signed POST /api/v1/automation/commands/catalogue/check-legacy-release-source → FastAPI run_legacy_release_scout → existing daily-maintenance lock 847220092 → Supabase capacity preflight → due(provider,day,revision) → original ReferenceFeeds source adapter → existing validated reference-set/card persistence`.

The existing daily maintenance worker still runs; n8n does not bypass it. A concurrent run returns `ALREADY_RUNNING` without any new HTTP call or database mutation. A completed source check that is not due returns `CURRENT`. After a verified due import, the API reports record counts and newly discovered set IDs sampled from the existing audited run receipt. n8n never sets canonical owners, market values or sale listings.

**Current production limitation:** Supabase was 430,484,627 bytes at last verification, above the 400 MB bulk-refresh safety line. The backend reports `DEFERRED_CAPACITY` and performs no provider/network/SQL bulk writes until the database is relieved or these legacy adapters are safely ported to Cloudflare R2/D1. Installing/publishing a daily schedule is **not** the same as the backlog being completed.

**Riftbound:** Riot Developer Portal's [Riftbound Digital Tools Policy](https://developer.riotgames.com/docs/riftbound) requires written permission or a valid app-specific API key, with permitted assets coming from the Riot API itself. A site export or third-party API does not grant Drop Rate image rights. The Riftbound workflow is a deliberately non-networking, metadata-only readiness check returning `DEFERRED_RIOT_APPROVAL` until separately reviewed API access and a proper source adapter are installed. No unapproved Riot artwork is cached, mirrored or published.

## 3. Failure points and tests

- Incorrect signature, timestamp, action, source or arbitrary URL: reject before any provider call.
- Supabase capacity above threshold, read-only mode or inaccessible capacity check: no bulk writes and no false success.
- Concurrent DR97 and existing maintenance: same advisory lock, explicit `ALREADY_RUNNING`.
- Recent completed source: no duplicate import.
- Source error/partial provider response: `SOURCE_INCOMPLETE` becomes a retryable 502, DR90 error routing.
- New sets: deterministic source identity, audited set/card writes only through existing `ReferenceFeeds`; return a bounded report. Never claim images or Shopify.
- Riftbound: no database writes, no unofficial public site scrape and no claim that API access exists.
- n8n release: verify eight exact version-controlled source definitions, pinned n8n version 2.32.6, DR90 published, offline SQLite, transaction-safe backup + manifest SHA, publish only those eight, verify each persisted version; source drift and conflicting flags stop deployment.

Tests: `PYTHONPATH=backend pytest -q tests/test_dr97_release_scout.py tests/test_catalogue_maintenance.py tests/test_n8n_workflow_registry.py`. Pinned n8n Docker workflow runs a disconnected publication simulation via `tests/n8n_legacy_release_publish_smoke.cjs`.

## 4. Activation and rollback

On merge, the n8n provisioner imports missing DR97 definitions **inactive** and never overwrites persistent workflows. Once the signed Railway API endpoint is live and healthy, an explicit activation flag `DROP_RATE_N8N_LEGACY_RELEASE_PUBLISH_ON_BOOT=true` runs `automation/n8n/ops/guarded-legacy-release-publish.cjs` during an n8n deployment. It verifies the eight stored definitions, backups and readback, then publishes them. The pre-existing DR90–96 workflows remain untouched.

Set that flag false to prevent future boot-triggered activation; **this does not automatically unpublish workflows already running**. A separate individually verified `n8n unpublish:workflow --id=DR97...` is required to pause them. Every workflow must be observed in live n8n activation logs and a signed execution before being described as autonomously importing source data.

## 5. Remaining artwork/publication milestones

Card discovery is not image publication. Complete and deploy the separate Cloudflare artwork D1/R2 Worker, connect independently permitted per-print media sources, verify the exact game/set/number/language/foil/variant and R2 SHA-256, and switch only a reviewed production image pointer. Physical PSA/BGS/ACE/CGC slabs require real photos of the *exact* item. AI cannot silently decide the match. Neither DR96 nor DR97 has a Shopify write path.
