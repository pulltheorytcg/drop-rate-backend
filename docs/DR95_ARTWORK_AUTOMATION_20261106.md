# DR-95: unattended eligible-card artwork orchestration

**Implementation date:** 6 November 2026. **State:** source-controlled, imported inactive by default. **No new-game artwork or Shopify photos are published by this change.**

## What is being built, why and how it connects

Drop Rate's artwork automation should require no founder approval on each **verified, permitted, exact-print image**. n8n owns scheduling, call retries and errors; FastAPI makes deterministic eligibility decisions; Supabase/Postgres remains the item/media owner of truth; Cloudflare R2 stores immutable, independently hash-verified image bytes; the app only selects database-eligible images.

This builds on existing live mechanisms rather than creating a second image database or allowing n8n to choose image URLs:

1. **DR-94** `DR94R2ApprovedMediaMirrorV1` is **already activated** on production n8n (Railway log readback 6 November 22:24 UTC). It calls `POST /api/v1/automation/commands/storage/mirror-approved-media` for up to three canonical/provider assets per hour. Eligibility: same exact catalogue/source, approval `APPROVED`, rights `VERIFIED`, tier `STOREFRONT_ALLOWED`, source active and unrevoked, provider/HTTPS host allowlisted, image decoded/sanitised, checksum-verified in private R2, revalidated in SQL after remote I/O. DR-95 normally requests **zero canonical** assets to avoid competing with DR-94.
2. The **existing R2 reference-image API worker** is also running in production, with its own database advisory lock, provider-specific identity/host checks, source-version readback, retry backoff and up to 20 cached images per pass. This is a *reference-only* cache and never grants Shopify/listing image permission. DR-95 automatically delegates to it when both `TCG_R2_REFERENCE_CACHE_WORKER_ENABLED` and `TCG_R2_REFERENCE_CACHE_APPLY_ENABLED` are enabled, so two workers don't compete. If that worker is not enabled but the backend reference-cache apply policy is enabled, the new signed command may run the small reference batch directly.
3. **DR-95** `DR95EligibleArtworkSyncV1`, scheduled hourly in its source template, signs one command with the existing HMAC secret and POSTs `/api/v1/automation/commands/storage/refresh-eligible-artwork`. The new FastAPI command performs a read-only PostgreSQL capacity check **before provider or R2 work**, then delegates as above or mirrors small permitted batches. It rejects arbitrary provider URLs, source IDs, oversized batches or naive timestamps. Its n8n receipt verifier fails on HTTP errors, malformed responses, unsupported publication scopes or unverified mirror results. DR90 handles errors.
4. The new workflow is **additively imported inactive** on n8n startup and never overwrites existing DR94, the reference worker or other persisted workflows. Actual n8n publication requires a separate stored-definition/rollback/DR90 check; a merge and automatic Railway deploy do *not* equal activation.

## Live evidence and why all cards cannot yet be displayed

- Supabase at 6 Nov 22:00 UTC: database **430,484,627 bytes**. Existing reference-image worker logs repeatedly show `BULK_REFRESH_DEFERRED_CAPACITY` because the explicit 400 MB refresh-safety threshold is crossed. This new command preserves that guard and returns `DEFERRED_CAPACITY` with zero uploads.
- **66,218** legacy `reference_image_mirrors` entries verified, **4** still in retry; **401** approved canonical media mirrors. Verified source/R2 bytes do not prove publisher rights for all possible commercial uses.
- New R2-first metadata-only partitions: Yu-Gi-Oh! **45,418**, Disney Lorcana **3,505**, MTGJSON **153,662** stored / **151,613** released, plus partial sports and figure sources. **They have no eligible per-print image feed automatically attached.** The existing data imports intentionally discard image URLs and do not grant art licences. DR-95's receipt explicitly states `new_game_metadata_promoted=false`. No generic art/guessing, no JPEG magically promoted by a cron.
- Slab/graded items require a matching **photograph of the actual physical slab** by the current owner, with inventory-specific first-party rights. Reference art never becomes a slab photo. Sealed products and comics/manga require their own exact-edition/cover policy.

## Release gates for future truly automatic all-game artwork

1. Independently establish permitted commercial image use for each provider/game; do not infer rights from free metadata API access. Original in-house photographed images with the owner's permission are the preferred independent path for unique inventory/slabs.
2. Extend the **backend**, not n8n, with a verified exact-print image record linked to published R2-first `stable_key(provider,system,language,provider_id)`, optionally print/image/treatment ID, source version, explicit licence/source scope, SHA-256, side and source-asset version. Refuse 1-to-many alternate art ambiguity, inconsistent edition/foil, mismatched language or untrusted hosts.
3. Queue only exact eligible source records, rate-limit permitted API reads; verify original bytes/type/decode and R2 immutable readback; store idempotent database mirror/link audit; roll back a bad generation with a pointer change. No deletion/overwrite of source history.
4. The storefront resolver may expose only a current, rights-approved, correct printing image. An inventory-listed graded slab still uses only its own reviewed slab photograph.
5. Test duplicate n8n delivery, owner isolation, source changes during an upload, bad bytes, HTTP redirects, corrupt R2 objects, expiry/revocation, restart, capacity block, n8n error routing, signed-in mobile/desktop display and permission revoke. Review at least a 25-per-source exact image grid and check actual live links before enabling auto-publication for that source. **No per-card founder approval is required after a source policy and matching system pass these release gates.**

## Rollback & operational safety

- **DR95 new workflow**: leave imported inactive or unpublish it without touching DR94. The backend endpoint is inert absent a verified HMAC request.
- **Canonical media**: DR94 and its existing rights-gated FastAPI command remain unchanged; existing images remain in the app.
- **Reference-only images**: existing API worker retains source/version hashes and pause thresholds. DR95 cannot override it.
- **New game sources**: absence of permissions or exact image mapping remains a named Action Required gap; not a permission to pick a substitute card image.
- **Finance/market values**: DR95 has zero access to ownership, prices, settlements or Shopify publication.

## Verification

`PYTHONPATH=backend pytest -q tests/test_dr95_artwork_sync.py tests/test_r2_media.py tests/test_r2_reference_worker.py tests/test_n8n_workflow_registry.py`

DR-95 JSON is validated in CI and the pinned n8n container build. The source template's `active:false` is intentional. An actual **active** recurrence may only be claimed after persistent n8n published-state readback and a real signed execution receipt, not a successful GitHub merge or Docker build.

See issue #966, DR-95's code path, and the separate expanded-artwork exact-ID pilot (PR #967).
