# Drop Rate independent object storage — staged R2/S3 implementation

## Scope and why

The live PostgreSQL/Supabase database (accounts/authentication, canonical cards,
physical inventory, ownership, valuations, transactions and settlement ledgers)
**remains the sole source of truth**. Neither S3-compatible buckets nor n8n
replace Postgres or make SQL search faster. The separate object store holds
large immutable bytes: first-party scanner photos, rights-cleared media, exports
and verified history snapshots. This reduces pressure from future image and
archive growth. Card search latency needs its own query/index/cache work.

### Provider choice

- **Preferred:** Cloudflare R2 Standard in a separate Drop Rate Cloudflare
  account. S3-compatible from Railway; free monthly allowance; edge delivery
  for separately approved **public** media via a custom domain. Do not expose
  private photos, consignment records or archives on a public bucket.
- **Fallback:** Railway S3-compatible bucket (EU Amsterdam region). Same backend
  client configuration; access remains private through backend or signed URLs.
- For private storage, start with `drop-rate-private` (all objects private).
  Create a separate `drop-rate-public-media` bucket/CDN later **only** for
  artwork for which commercial display rights and cache policy are confirmed.

Avoid creating an extra full PostgreSQL replica or a second independent identity
system as part of this change. A later DB migration is a major architectural
decision requiring downtime/replication, RLS and disaster-recovery planning.

## Implemented backend seam

- `app.object_storage`: optional S3-compatible client; off by default;
  TLS-required endpoint; content-addressed private keys; bounded retries;
  remote `GetObject` byte-by-byte SHA-256 verification; safe idempotent retry;
  refuses to overwrite an existing corrupt object; no delete method.
- `GET /api/v1/object-storage/status?probe=true`: **platform-admin only**;
  `NOT_CONFIGURED`, `CONFIGURED_NOT_VERIFIED`, `REACHABLE` or failure state.
  No tokens or S3 endpoint appear in the response.
- `POST /api/v1/automation/commands/storage/health`: signed n8n read-only
  command; the same bounded HMAC transport as existing automation commands;
  tests only bucket connectivity and returns no credentials.
- `DR93ObjectStorageHealthV1`: version-controlled **inactive** hourly n8n
  storage probe. It fails the execution on an unhealthy result. Do not activate
  before provider configuration, a manual pass/failure test and DR-90 routing.
- `backend/scripts/archive_reference_history_object.py`: read-only,
  repeatable-read SQL export of the full `tcg.reference_market_history` to
  `NDJSON.gz`; authenticated platform-admin scope; R2 upload + download hash
  verification; separately verified manifest. Default **dry run**; `--apply`
  is required. No delete, truncate, pricing, inventory, accounts or settlement
  mutations. The receipt explicitly says `restoration_verified=false` until a
  separate disposable Postgres restore has succeeded.
- Existing **Google Drive** full archive and the existing Drive-specific
  `archive_verified_reference_history` SQL helper are untouched. An R2 backup
  by itself does **not** authorise deleting historical price evidence.

## Railway environment setup (only after bucket is created)

Put these on the **drop-rate-api-live** Railway service and, later, a dedicated
archive worker. Do not put secrets in Git, ChatGPT chat, or n8n workflows.

| Variable | R2 value |
|---|---|
| `TCG_OBJECT_STORE_ENABLED` | `true` once verified |
| `TCG_OBJECT_STORE_ENDPOINT` | `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `TCG_OBJECT_STORE_BUCKET` | `drop-rate-private` (actual created name) |
| `TCG_OBJECT_STORE_REGION` | `auto` |
| `TCG_OBJECT_STORE_ACCESS_KEY_ID` | scoped R2 S3 API credential |
| `TCG_OBJECT_STORE_SECRET_ACCESS_KEY` | scoped R2 S3 secret |
| `TCG_OBJECT_STORE_PREFIX` | `drop-rate` (optional) |

R2 access tokens should be restricted to only the selected bucket and the
minimum necessary object operations. Keep private and public buckets separate;
rotate on compromise. Configure alerts/budgets, retention, versioning or
equivalent recovery controls before relying on this for disaster recovery.

## Validation / rollout gates

1. Run unit tests with configuration absent: backend still starts unchanged.
2. Create R2 bucket manually in the authorised Drop Rate Cloudflare account;
   place scoped credentials in Railway **Variables**, never share secrets here.
3. Run `/api/v1/object-storage/status?probe=true` as a founder admin; confirm
   `REACHABLE` and test a tiny non-sensitive file round trip.
4. Run read-only archive `python backend/scripts/archive_reference_history_object.py`
   in an authenticated job environment; inspect row count and gzip checksum.
5. Run with `--apply` once in a one-shot Railway worker; verify **both** archive
   and manifest upload/download receipts; restore in a disposable Postgres DB
   before calling it a recoverable backup. **No SQL cleanup** in this phase.
6. Ensure history-row count, all three current-price tables, all inventory
   owners and Shopify links are unchanged; verify API readiness.
7. Activate DR-93 only after the signed health-check route passes a manual
   execution and errors reach the existing DR-90 Action Required route.
8. Only then schedule with a single-flight n8n archive workflow: daily trigger → call a
   governed FastAPI archive-job enqueue endpoint (future, idempotent) → poll
   job receipt → check R2 manifest/hash/restore receipt → alert on failure.
   n8n never holds DB superuser or S3 credentials, never issues cleanup SQL,
   and cannot claim success merely because a job was started.
9. ChatGPT/Railway agents may inspect health, logs and receipts and propose
   repairs; destructive archive cleanup, payment and owner-data changes still
   require explicit deterministic backend approval and reviewed restore proof.

### Incomplete / requires account connection

- The R2 bucket and credentials have **not** been provisioned; the user must
  approve the external Cloudflare account and any usage beyond free allowance.
- There is **no** production archive scheduler or n8n activation in this phase.
- Object-to-`tcg.media_assets` owner/rights linking, signed browser uploads,
  public CDN and Shopify image delivery remain separate milestones. Do not
  publish user uploads without the existing media approval rules.
- Snapshots are only one component of backup; Supabase Auth and the entire
  relational DB require an encrypted Postgres backup/restore strategy, tested
  separately and not stored as unencrypted dump files.

## Failure points and test design

| Failure | Fail-closed behaviour |
|---|---|
| Missing/invalid credentials or endpoint | Do not enable; health reports generic failure |
| Provider timeout | No silent fallback to local DB, no overwrite |
| Retry of previously uploaded content | Same SHA-256 object key, verified; no duplicate |
| Existing object corrupt | Reject rather than replace silently |
| Upload interruption or checksum mismatch | No successful receipt and no SQL cleanup |
| R2 quota exceeded | Alert; retain all source data in Supabase |
| Private photo inadvertently shared | No public bucket/CDN for this implementation |
| Price/search still slow | Profile Postgres indexes, queries, API and cache separately |
