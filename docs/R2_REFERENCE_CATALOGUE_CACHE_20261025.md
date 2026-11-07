# Drop Rate — exact-reference catalogue cache (25 October 2026)

## 30 October authorised migration worker

The user has requested bulk migration of the catalogue's existing images into
R2 with connected in-app delivery. The existing API now hosts a restartable
worker enabled only by both `TCG_R2_REFERENCE_CACHE_WORKER_ENABLED=true` and
`TCG_R2_REFERENCE_CACHE_APPLY_ENABLED=true`. It uses the existing 20-image,
four-download implementation, a database advisory lock across deployments,
two-second pauses between successful batches, 60-second pauses on broad source
failures and five minutes when caught up. Every image retains its durable exact
printing link, verified hash and retry history.

Before every worker batch, the existing database capacity guard checks the
Postgres receipt store. At 400,000,000 bytes or in read-only mode, the worker
releases its lock and pauses for five minutes before checking again. A failed
capacity probe prevents downloads/uploads and retries after 60 seconds.
Successful batch logs include the measured database size; deferred logs include
the guard's reason. The existing 20-image/four-download pace is unchanged.

Set `TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED=true` after the first verified
batch; the browser already tries its signed R2 image first and retains the
original source fallback. Stop the worker flag to pause safely. There is no new
Railway service or n8n workflow. Source-host scope is unchanged in this release.
Earlier rollout restrictions below describe the original disabled release.

## What the implementation actually changes

The searchable catalogue, portfolio ownership, live card market values, and
inventories remain in PostgreSQL/Supabase. Railway remains the application
server. Cloudflare R2 stores optimized, immutable WebP **bytes**, not a
replacement database. `tcg.reference_image_mirrors` holds small, indexed
references from each exact provider/system/language/printing to its R2 key.
This is not a transfer of existing price or catalogue tables into R2.

The new catalogue read joins a mirror **after** search pagination and only if
the original `reference_cards.image_url` and all four identity fields still
match. A verified R2 object can be sent as a one-hour, signed image link by
setting `TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED=true`. The app preserves the
normal original URL/reference-image fallback, so R2 is not a new point of
failure. The raw bucket key is removed from API JSON.

This table is separate from rights-approved `tcg.media_object_mirrors` and
cannot make an image eligible for Shopify or seller product publication.

## Writing cache entries (deliberately off initially)

The existing automation HMAC mechanism now recognises:

`POST /api/v1/automation/commands/storage/mirror-reference-media`

```json
{
  "schema_version": 1,
  "action": "MIRROR_EXACT_REFERENCE_MEDIA",
  "execution_id": "operator-run-id",
  "occurred_at": "2026-10-25T22:00:00Z",
  "limit": 10,
  "apply": false
}
```

An authenticated `apply:false` call reads a bounded set of potential source
rows and **does not upload**. Actual caching additionally requires
`apply:true` and an independently configured
`TCG_R2_REFERENCE_CACHE_APPLY_ENABLED=true`, which defaults to false.

Each writer batch is at most 20 images, with no more than four simultaneous
image requests, a strict provider/system/URL host allowlist, 4 MB input cap,
12-second per-source timeout, decoded/stripped WebP optimization and 10 MB
output cap. The R2 client verifies SHA-256 against the actual uploaded object.
The database then rechecks the source URL and exact printing to avoid a stale
race. Failed inputs are recorded with backoff; existing verified mirrors are
not invalidated by a transient retry.

**Critically:** the allowlist is a technical SSRF/identity boundary, **not**
a licence. Before enabling bulk rehosting of reference artwork, Drop Rate must
document the reproduction/caching rights of each provider or get permission
from the relevant rightsholder. Bandai's official site terms restrict copying
and redistribution, so matching a Bandai host is insufficient. Existing
source image URLs can still be displayed through the app's current reference
artwork path while licence questions are resolved.

## Operational readiness

1. Install `database/migrations/20261025232125_r2_reference_image_cache.sql`
   **before** deploying the code that joins the new table. No live table is
   deleted or altered; all RLS policies use private `tcg_api` only.
2. Run `PYTHONPATH=backend python -m pytest -q tests/test_r2_reference_images.py`
   and the non-network catalogue tests. Inspect browser results and SQL plans
   for both alphabetical and price-value sorting.
3. Deploy the API with both new flags unset, run a signed dry-run and compare
   the candidate count to the source database. Inspect Railway health and the
   Supabase security/performance advisors.
4. Once each source's permission is documented, set the apply gate and run
   **one** `apply:true` item. Confirm WebP object, read-back SHA, exact join,
   source fallback and no inventory/price changes. Slowly increase batches.
5. Separately enable **delivery** after testing with a signed-in user.
   There is intentionally no live bulk schedule for this reference-only
   worker until the reproduction/use gates have been satisfied.

## Initial scope, scale and known gaps

As checked against production on 25 October 2026, there are 69,545 card
reference rows. Roughly 51,475 existing source image URLs are on the three
recognized Pokémon/Dragon Ball/One Piece provider hosts, but their presence
**does not** establish reproduction permission. The Naruto/CardTrader URLs
are outside this cache. This migration does not collect 10,364 missing
artworks, import the larger comic/manga database, or raise the roughly 60.4%
known positive-price coverage to 90%; those are upstream source/ingestion
workstreams, not disk capacity issues.

The comic/manga catalogue's 48 current products remain unaffected. A complete
GCD ingest needs a confirmed input/source account or import file, with a
deduplication and cover-rights review. Pricing archives can reside in R2,
with weekly verified exports to the *Drop Rate* Google Drive; archive exports
should not remove the currently indexed live price data.

## Backout

- Set `TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED=false` to use existing images.
- Set `TCG_R2_REFERENCE_CACHE_APPLY_ENABLED=false` to stop new writes.
- Do **not** delete existing R2 objects or DB records as part of a rollback;
  they are immutable and auditable until a separate retention decision.
- Do not change the existing approved-media mirror flags by accident.

