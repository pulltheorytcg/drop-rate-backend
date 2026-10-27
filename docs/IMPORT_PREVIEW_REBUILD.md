# Founder import preview rebuild

## Purpose and scope

An existing preview rejects another `/preview` request containing the same
`SHA256(content encoded as UTF-8)`, even when the founder only needs to correct
column mappings, adapter or default game/language. Rebuild lets the founder
recompute that uncommitted preview without creating a second import batch.

The first release supports the founder route only. Seller Hub automatic intake
can add copies during upload and row review, so it cannot use this operation.
Any batch with `automatic_intake=true`, a recorded `last_auto_apply_version`, a
committed candidate or an inventory copy is rejected, including partially
processed batches whose top-level status is still PREVIEW. COMMITTED and
CANCELLED batches are also rejected. Rebuild never creates a catalogue product
or an inventory item.

## API and UI contract

`POST /api/v1/imports/{batch_id}/rebuild` uses the existing authenticated founder
router. Its body contains all existing `ImportPreviewRequest` fields plus
`version` (the latest batch version). It requires the exact original content.
The stored filename determines CSV versus TSV parsing and remains unchanged;
selecting a renamed local copy does not alter the source filename or delimiter.

```json
{
  "filename": "original.csv",
  "content": "Name,CorrectName,Set,Number,Quantity\n...",
  "adapter": "GENERIC_CSV",
  "default_game": "Pokemon",
  "default_language": "English",
  "column_mapping": {"name": "CorrectName"},
  "version": 3
}
```

The response has the existing compact preview shape with the same `batch_id`,
the incremented `version`, and `rebuilt=true`, `review_edits_reset=true`,
`created_count=0`. Candidates are limited to the first 200 in this response, as
with initial preview. Re-read `GET /api/v1/imports/{batch_id}` for persisted
candidate IDs before offering resolve/skip actions. Old candidate IDs cease to
exist and old versions are stale after a successful rebuild.

The persisted GET response also includes `summary` with authoritative
`candidate_count`, `ready_units`, `review_rows` and `skipped_rows` across every
candidate in the batch. `preview_truncated` compares the full count with the
displayed list, which remains capped at 5,000. Use these totals when reopening a
preview; Collectr synthetic reconciliation rows can occur beyond the displayed
list. Batch/version, totals and displayed rows use one read-only repeatable-read
snapshot. Existing batch and candidate response fields are preserved.

Preview and batch-detail responses expose `rebuild_enabled`, indicating the
deployment feature flag. The founder UI should offer a deliberate **Rebuild
preview** action only for an eligible uncommitted manual preview, with the
original file selected. Explain before submission that column/default changes
are recomputed and existing match/skip review edits are reset. Do not silently
rebuild after a duplicate-file response, and do not show this as a way to replace
already added copies. The founder asset is `inventory-imports.js`; Seller Hub's
`owner-imports.js` has separate automatic-intake semantics.

Responses: 404 when disabled or when the batch does not belong to this founder;
403 for missing current founder authority; 409 for stale version, a busy import,
different original content or a non-rebuildable state; 422 for invalid mappings,
CSV data, unsupported candidate bounds or failed source/candidate validation.

The founder screen now provides exact-header mapping choices for CSV and TSV,
an **Open preview** action on recent manual previews, and an explicit **Rebuild
preview** control when the server flag and batch state permit it. A duplicate
file response reopens its exact existing batch read-only; it never automatically
rebuilds or commits. Rebuild remains disabled until a file is selected. The
original batch/source identity is retained even when the selected local file
has been renamed.

After replacement, the screen reloads the authoritative version, totals and
persisted candidate IDs. An interrupted response also triggers a readback; if
that fails, old review controls are removed until the batch is reopened. Buttons
prevent simultaneous rebuild/review/commit requests, and a late response cannot
repaint a closed or newly opened dialog. Full persisted totals govern commit
eligibility even when review rows fall beyond the displayed candidate limit.

The dedicated founder DOM/API fixture passes 17 scenarios for mapping, explicit
duplicate recovery, feature and state gates, replacement IDs, simultaneous
clicks, interrupted responses, stale dialogs and undisplayed review rows. The
complete existing dashboard DOM suite also passed. These fixtures use synthetic
API responses; they are not evidence of a live founder sign-in or production
rebuild.

## Database boundary

`preview_import` retains its public Python signature. `_parse_preview_source`
and `_build_preview` are shared by initial preview and rebuild, so normalizers,
catalogue matching, Collectr quantity reconciliation and baseline decisions
follow one implementation. Rebuild holds the established owner transaction
advisory lock and a `FOR UPDATE` batch lock while rebuilding. Existing review
operations also hold the batch lock; commit and automatic intake use the same
owner lock. Only one operation can consume a given version.

The runtime role still cannot delete candidates or update batch adapter,
warnings or physical-unit metadata directly. The CLI-generated migration
`20261027143430_founder_import_preview_rebuild.sql` adds one private capability,
`tcg_private.replace_import_preview`. It uses the established current-user and
founder-authority helpers, binds the actor to their exact active founder owner,
pins `search_path=pg_catalog`, has a two-second lock timeout, revokes PUBLIC,
anon and authenticated execution, and grants only tcg_api execution. It does
not broaden table grants or alter RLS policies.

The function independently verifies the current source hash, row count,
version, PREVIEW/manual state and absence of committed candidates or copies.
Every original row must retain exactly the same raw source record. It permits
replacement of only READY, REVIEW and SKIPPED candidates, binds all new rows to
the same batch and owner, and validates contiguous source rows and quantities.
Only the existing Collectr missing-from-snapshot reconciliation shape can
append synthetic rows. Limits are 5,000 original rows, 10,000 total candidates,
32 MiB serialized candidates and 16 warning strings / 16 KiB warnings.

Deletion, insertion and batch version/adapter/warnings/physical-units updates
occur in one statement within the caller's transaction. The existing candidate
audit trigger records the removed review state and replacement records with the
authenticated actor and request ID. Batch ID, owner, source, source SHA,
source-row count, filename and creation time are preserved. A changed adapter
is current interpretation; the original `source` value remains source evidence.

## Verification and rollout

The default `TCG_IMPORT_PREVIEW_REBUILD_ENABLED=false` makes the new endpoint
unavailable before its migration is installed. Prepare and review the backend,
UI and migration together, run the dedicated PostgreSQL 17 CI job, and apply the
reviewed migration through the governed database migration path. Verify the
private function owner/configuration and narrow grants and run the relevant
Supabase advisors before enabling the API flag. Do not apply production DDL as
part of the local test command.

`create_app()` must assign its validated startup object to
`app.state.settings = settings` after constructing the FastAPI application. The
rebuild helper reads that shared object, and the application regression checks
both the enabled/disabled values and the existing founder route dependency.

The real-PG17 fixture is restricted to a disposable local database:

```sh
PYTHONPATH=backend IMPORT_REBUILD_TEST_DSN=postgresql://postgres:disposable-ci-only@127.0.0.1:5432/import_preview_rebuild_test python tests/import_preview_rebuild_postgres.py
```

It applies the real founder-authority, incremental-intake and rebuild migrations
to the existing focused import schema fixture, exercises production handlers
and the real candidate audit trigger, and verifies narrow grants, foreign-owner
and actor denial, source immutability, review reset, changed Collectr baselines,
shrinking synthetic rows, FK/outer-transaction rollback, two-session rebuild
races, commit/rebuild serialization, no extra copies and direct-capability lock
coordination. The fixture uses synthetic records and does not replay unrelated
production schema history or a real Supabase sign-in flow.

Local verification on 27 October 2026 passed with PostgreSQL 17.6:

- The dedicated real-database rebuild fixture passed all listed boundary,
  rollback and concurrency checks.
- The existing `owner_auto_import_postgres.py` fixture passed against a second
  fresh disposable PG17 database, including partial automatic intake, repeated
  files, quantity deltas, owner isolation and rollback.
- 176 import, owner-import UI contract and settings pytest cases passed,
  including 16 focused rebuild cases and the actual application's enabled/off
  startup settings checks. The native PG17 fixture also verified a 5,002-row
  preview whose two REVIEW rows occur beyond the 5,000-row display cap.

The production migration and feature flag remain unapplied by this work.

## Production release and connector block

PR #760 is merged as `683979fb207016f4d1f562d082e5b0c32d2354d2`.
API deployment `ebea8e5c-07d8-452e-bd8c-8d7e47106b21` succeeded at
15:12:29 UTC on 27 October. The exact release head passed all four CI workflows:
the dedicated PostgreSQL 17 rebuild suite, existing backend/dashboard checks,
shared reference consistency and immediate owner imports (including real
JWT/JWKS fixtures and responsive browser checks).

The reviewed migration was submitted through the governed Supabase migration
tool after refreshing table metadata/advisors and confirming ledger absence.
The connector returned JSON-RPC -32602, `Invalid or expired requestState`, with
reason `invalid_request_state`. A subsequent migration-list read still returned
135 entries and no `founder_import_preview_rebuild` migration. No successful
installation is claimed. `TCG_IMPORT_PREVIEW_REBUILD_ENABLED` is explicitly
false. Resolve the connector request-state error before another installation
attempt, then verify live readiness before enabling the UI action.

The earlier live metadata preflight on 27 October returned no result within 45
seconds from `execute_sql`; that call queried only system catalogues and
migration presence and submitted no DDL or data writes. A separate purpose-built
migration-list read returned 135 ledger entries in 815 ms: the new rebuild
migration is absent; `unified_founder_app_access` (20261002031304),
`owner_incremental_import_intake` (20261011154138) and
`reference_history_r2_archive` (20261026204421) are present. This verifies ledger
presence only, not current function definitions, grants or policies. Live
permission readiness therefore remains unverified until the retained read-only
query in `docs/evidence/import-preview-rebuild-preflight-20261027.sql` succeeds.

Reference security guidance checked for this implementation:
[Supabase database functions](https://supabase.com/docs/guides/database/functions#security-definer-vs-invoker)
and [PostgreSQL 17 CREATE FUNCTION](https://www.postgresql.org/docs/17/sql-createfunction.html).
