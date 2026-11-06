# DR-96 — Per-game automated new-release scouts (6 November 2026)

**State:** Source-controlled and imported INACTIVE by default; verify production n8n published state independently. Six provider-specific watchers. Catalogue factual data only; **not** automatic commercial third-party artwork licensing or publication.

## 1. What is built and why

The existing Drop Rate metadata worker downloads, normalizes and publishes an exact-source R2 catalogue generation, with PostgreSQL retaining only a small transactionally protected publication pointer. It runs every 48 hours and internally limits certain providers to 7-day refreshes. This is not ideal for checking new published sets promptly. The new **DR-96 per-source n8n workflows** run independently at staggered times and POST one signed, source-bound request to FastAPI. The backend alone decides whether to download a new snapshot, verifies provider permission, uses the existing cross-deployment advisory lock, uploads immutable R2 parts with byte and SHA-256 readback, reconstructs a cold index, and performs atomic generation compare-and-swap.

This is a continuous *scheduled* process, not a tight request loop or scraping. Each source has its own trigger, logs and DR-90 error path. Failed source checks never silently replace a good generation and do not affect other games.

## 2. Schedules, source scope and constraints

| TCG/product source | Workflow | Time (Europe/London) | Real behaviour |
|---|---|---|---|
| Yu-Gi-Oh! — YGOPRODeck | `DR96YugiohReleaseScoutV1` | Daily 02:20 | Signed daily check; backend preserves existing 48h freshness/caching policy and source's 2-day cache. Unchanged revisions skip R2 bytes |
| Disney Lorcana — Lorcast | `DR96LorcanaReleaseScoutV1` | Daily 03:20 | Backend may refresh after 24h; sequential documented API requests (250ms delay), no partial snapshots |
| Magic: The Gathering — MTGJSON | `DR96MagicReleaseScoutV1` | Daily 15:20 | Backend may refresh after 24h, after MTGJSON's typical daily release window. All printings are metadata facts, not Wizards artwork |
| Sports — Bowman checklist | `DR96SportsBowmanReleaseScoutV1` | Tuesday 10:20 | Existing reviewed selected-checklist feed only; backend 7-day refresh |
| Sports — Heritage checklist | `DR96SportsHeritageReleaseScoutV1` | Tuesday 11:20 | Existing reviewed 100-item partial feed only; backend 7-day refresh |
| Figures — curated approved references | `DR96FiguresReleaseScoutV1` | Wednesday 11:20 | Existing curated four-item reviewed source only. Not automatic discovery of all new Funko products |

The authoritative allowlist is `backend/app/r2_first_import.py` `APPROVED_METADATA_SOURCES` plus the Railway env `TCG_R2_FIRST_IMPORT_SOURCES`. The FastAPI command's strict Literal enumeration cannot be overridden with an arbitrary URL. Added/removed game adapters must have documented permitted source access, bounded download and source-specific tests before being enabled.

The existing application reference card feeds (Pokémon/Tcgdex, One Piece official/Punk, Dragon Ball official, Naruto) are managed by a **different** maintenance loop. Their SQL-dependent bulk updates remain subject to the 400 MB Supabase capacity guard and have **not** been switched to Cloudflare-first. Do not create a competing n8n source fetcher for these before the R2/D1 migration/adapter parity is verified.

Riftbound stays blocked pending Riot app-specific API access/approval. Yu-Gi-Oh! alternate prints, graded slabs, foil/parallel finishes, sports variants and sealed products require exact verified image matching, and separate reproduction rights, before an image is eligible. Metadata schedule success must never imply artwork or Shopify listing published.

## 3. Connections and failure points

`DR96 n8n schedule → HMAC signed FastAPI /api/v1/automation/commands/catalogue/refresh-release-source → allowlist + authorised maintenance actor → global advisory lock → source fetch & normalization → R2 immutable readback → SQL CAS pointer → app cache`

- HMAC/timestamp and closed-schema validation block unauthenticated jobs and arbitrary provider URLs.
- On duplicate delivery/overlap, a single advisory session lock returns `ALREADY_RUNNING`; no second fetch.
- If a provider is not explicitly enabled in the backend/Railway allowlist, the command returns `DISABLED`, which the n8n receipt checker treats as a failure.
- Existing cooldowns, byte/time/page/rate bounds, source-specific permitted-use checks and full-snapshot validation remain authoritative; n8n cannot override them.
- Provider HTTP 429/403/redirect or invalid schema is a failed run; it cannot publish a partial R2 manifest.
- If downloaded source revision is the same as the previously verified version, the importer records `CURRENT` and **skips R2 rebuild/re-upload**, leaving generation pointer unchanged.
- A newly published provider generation is `metadata_only=true`; *it is not a new card artwork receipt*. HMAC responses explicitly carry `artwork_published=false`, `shopify_updated=false`, and `ownership_or_price_changed=false`.
- Source facts that have a release date later than today remain withheld by the existing catalogue resolver until released.
- Production migration is still ongoing: the small active metadata publication pointers remain PostgreSQL until their independent D1 migration passes; card/image bytes are in R2.

## 4. Verification, deployment and rollback

**CI** `PYTHONPATH=backend pytest -q tests/test_dr96_release_scout.py tests/test_r2_first_import.py tests/test_n8n_workflow_registry.py` and full backend/n8n-image suite. Tests include six unique source workflows, malformed signatures/source fields, permission denial, real no-op revision, source upload failure, provider lock contention, safe lock release and no artwork/Shopify/owner/price authority.

**Activation prerequisites:** The API command must be in a successful Railway healthchecked release; trusted n8n credentials and DR-90 must already be verified; the six workflows must be newly imported inactive with exact source-reviewed hashes, and an offline SQLite backup must be checked before publishing a trigger. Enable one source at a time, prove a signed live execution's true result and source cooldown, then publish the rest. n8n's existing persisted definitions are never silently overwritten on redeploy. Rollback unpublishes each DR-96 workflow; the existing background `run_loop` and last verified R2 generation remain intact.

**Additional artwork release step:** `#966` and Cloudflare artwork staging `#968` must independently resolve rights-approved per-print art, exact D1 source/print mapping, actual R2 Worker deployment, storefront signed-in mobile/desktop display and physical slab photo provenance. DR-96 does not itself create, upload, rehost, display or commercial-license any third-party card image.


## 5. Guarded live n8n activation

A normal main-branch deploy imports six workflows inactive and never overwrites persisted IDs. The separately reviewed activation uses the Railway flag `DROP_RATE_N8N_RELEASE_SCOUT_PUBLISH_ON_BOOT=true` only after the signed FastAPI endpoint has passed deployment.

The offline operator `automation/n8n/ops/guarded-release-scout-publish.cjs` performs:

1. Reject unsupported/conflicting workflow mutation flags.
2. Verify six exact source hashes, provider names, signing/verifier nodes, already-published DR-90 error handler.
3. Verify pinned n8n 2.32.6 and offline persistent SQLite draft/history state.
4. Take/verify a WAL-aware SQLite backup (SHA-256 manifest, private directory permissions).
5. Recheck persistent definitions, publish only six DR-96 IDs one at a time, verify each published version hash.
6. A repeat deployment returns ALREADY_PUBLISHED; unexpected drift blocks rollout rather than changing another workflow.

Pinned n8n-image CI runs a **network-isolated SQLite publication smoke** that checks all six definitions, hash drift, duplicate activation, operator conflicts, backup and exact published state. Real provider ingestion requires later signed live receipt and current R2 generation readback.

Rollback: set the flag false to stop future boot-driven publishing; that **does not unpublish already active n8n schedules**. Fully pausing the watches uses a separately checked, narrowly scoped n8n `unpublish:workflow --id=<specific DR96 ID>` operation with backup. Do not unpublish DR90 or DR94.
