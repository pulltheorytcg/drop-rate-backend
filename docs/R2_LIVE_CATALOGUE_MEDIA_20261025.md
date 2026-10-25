# Drop Rate — live catalogue artwork from private R2 (25 October 2026)

## Architecture and scope

The 69,545-reference-card Postgres/Supabase catalogue remains the **live search,
identity, account, inventory, ownership and current-market-value database**.
R2 is not a SQL database and is not substituted for Postgres on every search:
that would make search slower, break ownership/account controls and create
inconsistent prices. R2 holds **large immutable image bytes, market-source
snapshots and historical evidence**; fast indexed rows point to its objects.

For this stage, only existing `tcg.media_assets` records with all of the
following may be mirrored: canonical product/card, front image, human approved,
rights verified, storefront distribution permitted, active and not revoked.
The mirror worker additionally accepts only approved TCGdex/Bandai/Punk Records
source/provider combinations on exact official hosts. Buyer photos, seller
scans, personal collections, eBay listing images and CardTrader marketplace
images are excluded. Rights approval itself is never inferred from R2.

```
Signed-in app → FastAPI → Supabase live catalogue/price/rights SQL
                              └── verified mirror object key
            ↘ R2 temporary GET URL for approved media → browser image
                                            ↘ original image fallback
Signed n8n command → FastAPI rights check → provider image → vetted WebP
                  → private R2 upload + GET SHA-256 verification
                  → Supabase mirror mapping (conditional on unchanged rights)
```

## Components added

- `database/migrations/20261025170228_r2_verified_media_delivery.sql`:
  additive `tcg.media_object_mirrors` metadata (not binary files) with a source
  URL, content-addressed R2 object key, SHA-256, size and verification time.
  RLS blocks `anon` and `authenticated`; only the private backend `tcg_api` role
  can read or write eligible mirrors. No delete grant. Existing media audit
  trigger logs inserts and source updates.
- `app.object_storage`: private WebP upload with read-back SHA-256 and bounded
  60-minute S3v4 GET URLs. Only content-addressed `private-media` keys may be
  signed. No bucket listing/object delete from the browser.
- `app.r2_media`: source-domain allowlist, decoding/EXIF removal, 960×1344
  maximum WebP conversion, 4 MB inbound source cap, 10 MB object cap, batch of
  at most five items, and a rights/source recheck immediately before the DB
  link is committed. Missing or expired links fall back to the provider source.
- `GET /api/v1/catalogue-browser/products`: includes `r2_image_url` **only**
  when `TCG_R2_MEDIA_DELIVERY_ENABLED=true`, storage is configured, the joined
  mirror matches the current source URL, and existing SQL rights/approval
  filters pass. Raw `r2_object_key` is always removed from JSON.
- `POST /api/v1/automation/commands/storage/mirror-approved-media`: existing
  HMAC-signed n8n command transport; at most five images. n8n never receives R2
  credentials or direct database write authority.
- `backend/scripts/mirror_approved_media_object.py`: Railway read-only dry run
  by default; explicit `--apply --limit 1` for a monitored pilot.
- `DR-94 Verified Catalogue Artwork to Private R2`: **inactive** hourly
  workflow export; single small signed batch. Activate only after all live
  rollout gates pass and DR-90 alerts are verified.

## Production rollout and safety gates

1. Verify current R2 bucket permissions and read-back probe; existing private
   archive must remain private. Never make `drop-rate-private` public.
2. Apply the additive SQL migration in Supabase before deploying backend code.
3. Run targeted unit/integration tests, DB security advisors and JavaScript
   syntax checks; review the URL signing/approval bypass tests.
4. Deploy to Railway; wait for terminal `SUCCESS` and check health/errors.
   `TCG_R2_MEDIA_DELIVERY_ENABLED` should initially stay **false**.
5. In a bounded Railway operator run, do a dry run and then
   `--apply --limit 1`. Inspect `mirrored=1`, R2 SHA-256 read-back and the
   eligible DB mirror record. Repeating the same record must not upload twice.
6. Enable `TCG_R2_MEDIA_DELIVERY_ENABLED=true` only after a signed-in card
   linked to an eligible canonical asset loads via R2 and falls back correctly
   when R2 is deliberately unavailable. CSP allows only the configured private
   R2 origin, not wildcard providers. Check real handset performance.
7. Expand batches gradually and verify per-source/provider coverage and errors.
   Import DR-94 inactive, test a signed execution and DR-90 failure handling,
   then activate its hourly trigger. On the n8n Railway service, set
   `DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT=true` **only after** those
   checks pass. The startup provisioner uses n8n 2.x `publish:workflow` on
   `DR94R2ApprovedMediaMirrorV1` before starting the scheduler; it cannot
   publish unrelated workflows. Leave this flag unset during validation.
   Nonsuccess receives an alert; no purge.

## Explicit limitations and next work

- Existing approved mirrors cover hundreds of canonical products, **not all
  69,545 references**. The reference card artwork table contains external URLs;
  these cannot be blindly republished without validating source licence,
  provider/printing/language identity and terms of use.
- This is **image delivery**, not a relational database migration. No current
  market values, user accounts, inventory or transactions move to R2.
- A distinct `drop-rate-public-media` bucket and custom CDN domain could
  improve caching later, but requires rights and privacy approval. Temporary
  private R2 links already deliver bytes directly without proxying Railway.
- Archive market evidence independently as immutable compressed R2 manifests.
  Copy verified weekly archive files to the correct Drop Rate Google Drive,
  restore-test before retention rules, and keep currently displayed historical
  price summaries indexed in Supabase. Neither this feature nor a backup
  authorises DB cleanup.
- If R2 is unavailable, source media still displays; if source media also
  fails, show the existing unavailable-artwork state. Prices must remain live
  from Supabase and must never be fabricated from missing source evidence.

## Failure tests

Tests cover wrong source host/provider, private/founder image exclusion,
unauthorised object-key presigning, overly long signatures, corrupt existing
object bytes, idempotent object reuse, disabled feature fallback, rights/source
recheck after network I/O, SQL query price continuity and mirror matching,
no public database table grants, signed small n8n command, and JavaScript
fallback. Test both success and intentional R2 failure against Railway before
marking the live rollout complete.
