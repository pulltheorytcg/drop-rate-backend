# Automation control database repair — 27 October 2026

## Observed failure and reproduced causes

The live API deployment `ebea8e5c-07d8-452e-bd8c-8d7e47106b21` logged a
`POST /api/v1/automation/control/heartbeat` response of 500 at
`2026-10-27T16:00:34.150865449Z`, followed by a
`POST /api/v1/automation/control/receipt` response of 503 at
`16:00:34.411668529Z`. The storage-health command returned 200 in the same
window. Existing middleware did not log the underlying database exception.
No request bodies, headers, credentials or application records were collected
for this diagnosis.

Native PostgreSQL 17.6, using synthetic records, reproduced three defects in
the committed implementation:

1. The existing heartbeat function returns a column named `heartbeat_key` and
   uses `ON CONFLICT(heartbeat_key)` inside PL/pgSQL. PostgreSQL raises
   `AmbiguousColumnError`, SQLSTATE `42702`.
2. The receipt handler selects founders on a bare `tcg_api` connection. The
   committed owner policy exposes no owners without an authenticated user
   context, so this path returns its explicit 503 even when founders exist.
3. The old failure-alert write uses `entity_type='N8N_WORKFLOW'`. The committed
   schema and the captured live table metadata allow `OWNER` and other existing
   entities, but exclude `N8N_WORKFLOW`; the old write raises SQLSTATE `23514`.

The live migration ledger identifies the installed heartbeat migration as
`20260930044501` / `n8n_runtime_heartbeat`. Its reviewed repository source is
`database/migrations/20260930054500_n8n_runtime_heartbeat.sql`. These are
different identifiers; the ledger is not proof of the live function body.

## Repair contract

The Supabase CLI generated
`20261027164716_automation_control_runtime_repair.sql`. It preserves the
existing heartbeat signature and result fields. Within that function body,
the only change is the explicit conflict target
`ON CONFLICT ON CONSTRAINT automation_heartbeats_pkey`. The migration verifies
that this named primary key is the expected single-column key before replacing
the function.

The new private function is:

```sql
tcg_private.record_automation_execution_receipt(
  p_workflow_key text,
  p_workflow_version text,
  p_execution_id text,
  p_status text,
  p_idempotency_key text,
  p_occurred_at timestamptz,
  p_owner_id uuid,
  p_event_id uuid,
  p_error_code text,
  p_error_message text
)
returns table (
  owner_receipts_inserted integer,
  duplicate_owner_receipts integer,
  action_required_ids uuid[]
)
```

FastAPI verifies the exact existing HMAC request bytes and validates the bounded
payload before calling this function once. Both control payloads now require
timezone-aware timestamps. The database validates the typed arguments again.

For a global receipt, the function resolves the current active founder owners.
An explicit owner must exist and be active, preserving the existing scoped
receipt contract. Selected owner rows are held with `FOR SHARE` until the
atomic receipt/alert write finishes, preventing concurrent deactivation during
that write. No application user is impersonated and no `tcg.user_id` is set.

Each owner's durable receipt remains uniquely identified by
`(owner_id, job_type, run_key)`, with `job_type='N8N:' || workflow_key` and
`initiated_by='N8N'`. An existing receipt is never rewritten. A retry with that
same identity reports a duplicate and leaves both the first stored outcome and
any existing alert unchanged. A new failed receipt upserts one fixed
`AUTOMATION` / `N8N_WORKFLOW_FAILED` / `HIGH` alert per recipient and workflow.
It uses the existing `OWNER` entity and the recipient's actual owner ID;
workflow identity remains in the dedupe key and metadata. An existing alert
keeps its ID. Successful receipts do not create or resolve failure alerts.

The function is owned by `postgres`, uses `search_path=pg_catalog` and a bounded
lock timeout, and grants execution only to `tcg_api`. The migration adds no
table privileges and changes no table RLS policy or check constraint. It checks
that runtime privileges remain restricted, RLS remains enabled, and the two
receipt/alert conflict keys have valid, ready, immediate unique indexes.
Index names, column order and included columns may differ. Partial, expression,
missing or deferrable matching arbiters fail closed; a second matching
deferrable arbiter also blocks installation even when an immediate one exists.

Installing the migration invokes neither function and replaces no application
rows. Receipt storage and all recipient alerts form one database operation:
an alert failure for a later recipient rolls back earlier recipients' receipts,
alerts and audit writes.

Database failures are logged only as a fixed operation name and a validated
SQLSTATE. Database messages, details, traces and submitted content are omitted.
SQLSTATE `22023` maps to a sanitized 422. Other database failures, including an
uninstalled capability, map to a sanitized 503 and are never acknowledged as
successful. There is no fallback to the old owner-selection path.

## Verification and deployment boundary

`tests/automation_control_postgres.py` runs against a fresh, explicitly named
loopback-only PostgreSQL 17 database with a real restricted `tcg_api` login and
synthetic records. It uses the committed owner policy, action-required schema
and audit trigger, and heartbeat functions. The early `automation_runs` base
migration exists only in the historical ledger; the fixture mirrors its
captured columns/checks and uses an explicit owner-scoped fixture policy. That
fixture is not a substitute for reading the live policy and privileges.

The native suite retains all three old failures and checks the repaired signed
HTTP handlers, heartbeat monotonicity, current-founder fanout, explicit active
owners, inactive/missing owners, no-founder failures, private grants, unchanged
table/column ACLs and RLS, replay identity, eight concurrent first writes, and
multi-founder rollback including audit rows. It also exercises migration guards
and differently named/reordered unique indexes with included columns. The
dedicated `Automation control database contracts` workflow runs this suite on
`postgres:17.6` alongside the focused HMAC/API tests.

Local PostgreSQL 17.6 and the focused API tests have passed. Hosted CI and live
database readiness are separate release gates. At preparation time, Supabase
raw SQL and migration calls remained blocked by `invalid_request_state`.
Neither was retried as part of this repair.

Before a production installation, execute and review the bounded, read-only
[catalogue preflight](evidence/automation-control-runtime-preflight-20261027.sql)
after that connector issue is resolved. Verify the complete current heartbeat
definition and signature, function owner/configuration/ACL, runtime role and
memberships, relevant table RLS/policies/grants, and required unique-index
shapes. The migration ledger and local fixture alone cannot establish those
live facts. The preflight reads system catalogues and the exact migration
ledger entries, without application row contents.

Apply only the reviewed migration through the governed path, then re-run the
same catalogue checks. If an apply call has an uncertain outcome, reconcile
the migration ledger and function state before retrying. Deploying the API
first fails cleanly with 503 until the capability exists; it does not broaden
permissions or manufacture a receipt.

DR92 was independently paused on 27 October while this repair was prepared.
DR94 media publication remains off. Restoring the heartbeat schedule and
accepting natural heartbeat/receipt results are separate operations owned by
the release operator; this repair does not change n8n publication state or
manufacture a production failure.
