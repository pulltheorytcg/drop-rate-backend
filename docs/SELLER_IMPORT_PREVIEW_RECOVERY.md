# Zero-copy Seller Hub import recovery

Related issue: #599. Implementation staged; not a production acceptance receipt.

The existing seller upload can add some physical copies before review is complete.
Recovery therefore applies only to a PREVIEW with no committed candidates and no
inventory rows. It supports both untouched manual previews and incremental
uploads that admitted zero copies. Any partially admitted, COMMITTED or CANCELLED
batch remains blocked. No existing inventory is rewritten or removed.

`POST /api/v1/owner/imports/{batch_id}/rebuild` accepts the existing rebuild request
(original file content, explicit mappings/defaults, current version). It resolves
one active owner from verified authentication, preserves original filename/hash,
uses the existing normalizer and Collectr baseline, and returns a revised preview
with zero created copies. Source language is still authoritative over defaults.
The existing add action is a separate, explicit inventory operation. Old review
IDs and versions are invalidated; original candidate decisions remain in audit.

`TCG_OWNER_IMPORT_PREVIEW_REBUILD_ENABLED` defaults false, independently of founder
rebuild. Apply `20261107220000_owner_import_preview_rebuild.sql` only after review
and approval, then enable the flag only in an approved release. The new private
capability checks actor, exact unambiguous active membership, owner, file, version,
raw source rows and absence of copies independently of the HTTP handler. It holds
the same owner advisory/batch locks as intake, retains RLS and existing grants,
revokes public/anon/authenticated execution, and creates no global owner access.
The founder-only capability and endpoint remain restricted and unchanged in scope.

The existing import form, mapping fields, history and add button are reused.
For an eligible batch the existing submit action becomes Rebuild preview and
requires confirmation that review decisions reset. No layout/style/component
redesign. Re-select the exact original file if reopening a prior import. Failed or
interrupted rebuild reads back the authoritative batch; if readback fails, stale
review controls are removed. Merely rebuilding never adds copies or publishes.

Validation:
- 86 affected unit tests and 22 mocked DOM scenarios pass locally.
- Disposable PGlite executes actual production handlers and SQL: zero-copy
  incremental recovery, wrong/revoked/ambiguous owner, disabled flag, wrong hash,
  invalid mapping rollback, immutable raw source/audit, stale rebuild/commit,
  explicit Draft admission, replay, partially admitted rejection and Collectr
  corrected baseline / +1 / decrease handling.
- CI additionally runs native PostgreSQL 17 with restricted sessions, including
  rebuild/rebuild and rebuild/commit concurrency. Record actual CI result before
  claiming this passed. Existing founder rebuild tests continue to run.
- No live seller login, migration, physical iPhone, provider or publishing proof
  is implied by synthetic tests. Full #599 live acceptance remains open.

Rollback: disable the new flag, then revert code if needed. Rebuilt previews retain
original source identity and existing schema and can continue ordinary review.
Do not restore old candidate IDs, reset fingerprints, or delete audit/stock. The
unused private capability may be revoked in an explicitly reviewed follow-up;
no destructive rollback is required.
