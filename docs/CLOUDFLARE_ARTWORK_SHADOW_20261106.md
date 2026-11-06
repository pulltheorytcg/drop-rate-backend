# Drop Rate — Cloudflare-first artwork staging (6 November 2026)

**Approved architecture direction:** R2 holds immutable media bytes, a dedicated **isolated artwork D1 shadow** holds exact card-to-image receipts, and Railway FastAPI owns deterministic commercial publication eligibility. n8n schedules orchestration only. **This stage does NOT publish images or replace the live Supabase operational ledger.**

## 1. What is built and why

The existing live Supabase database has reached ~430 MB and the legacy reference-image cache worker pauses above 400 MB for safety. Cloudflare already holds 66,218 verified reference-art images and 401 canonical provider-image objects (~5.79 GB combined, 66,619 files verified by real R2 readback). Those bytes do not prove identity, printing, licensing or individual graded slab ownership. Additional *artwork-related* rows can be staged in Cloudflare, without consuming more Supabase database storage.

The new Cloudflare Worker at `cloudflare/artwork-shadow/worker.mjs` accepts a single HMAC-authenticated, exact-reference staging receipt at `POST /v1/internal/artwork/shadow`. It never fetches unknown external URLs, lists buckets, serves public images, or accepts arbitrary object paths. It computes Drop Rate's existing stable reference hash from `[provider,system_code,language,provider_id]`; checks exact image bytes, object size, content type, WebP signature and SHA-256 in the existing R2 private-media prefix; then inserts the complete image/source/printing identity into an isolated D1 shadow.

The D1 schema at `database/cloudflare_d1/0003_artwork_shadow.sql` supports **only** `STAGED_PRIVATE` rows, keyed by exact reference key and source catalogue generation. It is not a public art index and cannot be used as a Shopify image pointer. Replays are idempotent; conflicting image, rights-review reference, set or printing details produce HTTP 409, never a silent overwrite. No founder-owned physical card image is invented or substituted for generic raw reference artwork.

## 2. Connections and rollout

`n8n DR-95 (signed scheduling) → Railway FastAPI (provider/rights/print validation) → Cloudflare Worker (HMAC + R2 bytes) → private D1 artwork shadow`. The live app **still** reads the previously verified media path until a separate, versioned rights-approved public resolver and signed-in mobile/desktop test are implemented. This is a parallel component: it doesn't depend on a full Auth, inventory, price or financial D1 migration.

The GitHub workflow `.github/workflows/d1-artwork-shadow-provision.yml` validates SQL and Worker security in PR CI and, after merge to main, attempts to create **one empty, private** named artwork D1 shadow only if reserved Free-tier database slots are available. Cloudflare account identity is fixed; the existing D1 pilot token is injected as an Actions secret. It verifies exact table/index readback and reports no imported rows or cutover. It does not deploy the Worker: the Cloudflare Workers script still needs a scoped deployment credential and private bindings `ARTWORK_R2`, `ARTWORK_D1`, and `ARTWORK_COMMAND_SECRET`. No credential values are stored in GitHub source. Production media pointers remain off.

Existing production n8n **DR-94 is already active** and currently handles approved canonical image mirrors. The existing reference worker remains the legacy cache owner and currently defers due to database capacity. DR-95 is a new **inactive** control-plane workflow by default; it delegates to these workers so it never double-uploads the same images. No existing workflow is overwritten, and no n8n schedule is silently activated simply by merging.

## 3. Source and exact-image requirements before public release

- New Yu-Gi-Oh!, Lorcana, MTG, sports, figures and Riftbound references still require permitted exact-print/variant artwork source data. A card name or provider card-level picture is insufficient for promo/foil/alternate treatments. No arbitrary hotlink or inference of provider redistribution rights.
- Publishing authority must check a trusted source manifest's actual exact-print row, unrevoked rights evidence and image consent against the proposed R2 receipt, preferably with a signed immutable decision bound to the content and source generation.
- Raw catalogue thumbnails and photos of the **physical, graded** items must remain separate. A PSA/BGS/CGC slab listing needs the actual slab/holder photo attached to the exact inventory ID and owner.
- Any future public D1 pointer should be switched **only after** R2 byte readback, catalogue source-version parity, metadata/rights proof, correct side/variant, and a real signed-in device grid test pass. Revert by changing that pointer; never delete original source evidence.

## 4. Failure and verification

- **Wrong source key** → HTTP 409; **invalid signature/clock** → HTTP 401; **bad image URL/path/body** → HTTP 422; **missing/corrupt R2 bytes** → HTTP 409; **Cloudflare outage** → HTTP 503; **different image or set on replay** → HTTP 409; **same image and identity** → verified idempotent response.
- Local tests: `python -m pytest -q tests/test_cloudflare_artwork_shadow.py tests/test_d1_artwork_shadow_provision.py` (runs Node 22 built-in Worker contract tests and SQLite integrity tests). Backend and n8n regressions run in main CI.
- No new R2 images have been created from the expanded game data by this shadow implementation. No success claim is appropriate before a live Worker deployment and real source images pass rights and exact-print gates.

**Links:** [Cloudflare Workers R2 API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/), [Cloudflare D1 quotas](https://developers.cloudflare.com/d1/platform/pricing/), GitHub artwork issue #966, DR-95 PR #968, full exit decision `docs/CLOUDFLARE_R2_D1_MIGRATION_DECISION_20261106.md`.
