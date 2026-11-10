# Tier 1 R2 artwork verification: read-only rollout

**Status:** code-only, not deployed, no R2 requests executed in production.

## What and why

Existing reference-image mirror metadata is not proof of a physical R2 file. For **505** approved or published CARD/SEALED inventory units, Supabase currently has **444** approved canonical mirror-metadata matches, but zero of the eight graded Tier 1 physical items has an inventory-specific R2 mirror DB row. Artwork coverage must be proven from the *actual bytes*, and graded cards may not silently reuse raw-card artwork.

`backend/scripts/tier1_r2_media_bytecheck.py` is a bounded read-only job with a default 100-item page and a deterministic inventory-code continuation cursor. It:
- reads only `tcg.inventory_items`, `catalogue_products`, `shopify_inventory_links`, `media_assets`, and `media_object_mirrors` through a PostgreSQL **read-only transaction**;
- prioritises an approved physical-item photo, falling back to approved canonical artwork only for **ungraded** items;
- requires verified media rights status and language/variant consistency when tagged;
- retrieves R2 bytes using existing `S3ObjectStorage.read_verified_media`: strict content-addressed path, SHA-256 checksum and recorded byte size;
- uses an additional read-only R2 HEAD on verification failure to distinguish missing/inaccessible objects from size and SHA errors;
- decodes actual WebP pixels, requires at least 350 px per dimension, rejects invalid/animated/oversized files;
- deliberately labels passing media as `R2_BYTES_AND_DIMENSIONS_VERIFIED_VISUAL_UNREVIEWED`, **not fully identified**, since byte correctness alone cannot establish the exact artwork or placeholder absence;
- reports only per-game counts, sample inventory codes (max 20) and failure reason; no secrets, object keys, image bytes, owner data or signed URLs in its output.

All image source copies and new media ingestion require a separate rights review. This job neither downloads from providers nor writes to R2 or Supabase. No D1 work.

## Production run prerequisite and command (do not execute yet)

1. Verify a recent completed Supabase backup via the separate **manual GET-only** workflow in PR #1049; review restore plan.
2. Obtain approval for a **read-only** invocation on the existing configured Railway service or an isolated one-shot container (no changed credentials/config, no new paid resource).
3. From the repository root with existing Railway `TCG_DATABASE_URL` and `TCG_OBJECT_STORE_*` environment already present, run:

```bash
PYTHONPATH=backend python -m scripts.tier1_r2_media_bytecheck --limit 100
```

For subsequent bounded pages, pass `--after-inventory-code` using the `next_cursor` returned by the previous page, until `more_available=false`. This issues **at most 100 verified object GET operations and bounded HEAD-on-error operations per page**, with SQL read only. This is an audit, **not** a price or artwork backfill dry run.

### Tested without production mutations

Supabase connector executed the read-only SELECT with a hardcoded 10-row bound successfully; **10 rows returned, 10 had mirror metadata**. This does **not** verify that any corresponding R2 object exists. The script has offline test stubs covering graded slab exclusion, rights, language/variant mismatch, no mirror, decoded pixels, remote bytes failure and summary sanitisation.

## Failure handling / rollback

- Unconfigured R2 or Postgres: fail; no fallback to remote provider images.
- Missing object: count; never overwrite with a lower-resolution image, and never delete it.
- Bad SHA/size or low resolution: report gap; no SQL or R2 update.
- Graded item without its own approved photo+R2 object: fail; cannot use raw-card alternate.
- No production config/DB/table/scheduler changes to roll back. Removing the script PR (or not running it) leaves production unchanged.

**Next step after verification:** generate a *separate*, exact INSERT/UPDATE/SKIP dry run and 20 sample rows for approved Tier 1 repairs; obtain explicit founder approval before any writes.
