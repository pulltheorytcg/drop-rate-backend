# Marketing terminal attention repair

## Problem and scope

The installed preparation runtime records FAILED, UNKNOWN and NEEDS_REVIEW as terminal database results, but previously created no Action Required entry. HTTP 200 means the result was saved, not that the model succeeded. The design terminal step can return a failure without the parent attempting another handoff. A saved failure must therefore not depend solely on n8n throwing an exception.

Inspection also found a separate limitation in the shared DR90 route: the global receipt is accountless, while current owner and Action Required RLS need an authenticated user context. This repair does not broaden RLS or silently change that shared commerce/automation route. It addresses recorded marketing results under their existing authenticated transaction.

## Implementation

`marketing_run_attention.record_marketing_attention` verifies the current platform admin again, matches that actor to the persisted run, derives their owner from the database and inserts an OWNER-level AUTOMATION entry. Job, run, revision and stage identifiers are in metadata. No raw source text, model output, provider error, token, signature or credential is put in the alert.

`PostgresStore.finish` records the attention entry only when it actually finalises a RUNNING row. Both operations occur in one existing user_connection transaction. An insertion exception propagates and rolls back both. A late result only returns the stored terminal row.

`PostgresStore.claim` collects rows it transitions from stale RUNNING to UNKNOWN and records their attention in that same transaction before continuing. It does not repeat the model request. A later exception in that transaction still rolls all changes back.

FAILED and UNKNOWN receive HIGH severity; NEEDS_REVIEW receives MEDIUM. PREPARED and AWAITING_MEDIA are not failures. The dedupe key is derived from the existing persisted run ID; it is not a new per-retry key or a replacement automation event identity. INSERT ON CONFLICT DO NOTHING cannot reopen resolved/dismissed alerts.

## Tests and limits

Focused unit tests cover all attention and non-attention states, derived owner identity, wrong/revoked actors, safe metadata, duplicate insertion, malformed records and error propagation. The existing disposable PostgreSQL smoke now includes a minimal owner-scoped Action Required fixture and tests actual PostgresStore finalisation, stale recovery, isolation, no false-success alerts, replay, late results, resolved-alert preservation and rollback after an injected insertion failure. The fixture is local-only; it does not alter production schema or use production credentials.

The fixture does not claim live audit-trigger or alert delivery verification. Full existing backend and n8n tests must pass before release. Production job execution remains disabled until its separate activation gates are met.

This is database attention visibility, not proof of an email, push or Slack notification. It does not repair failures before a valid run is claimed, loss of the database itself, every n8n transport failure, or an indefinitely idle abandoned worker. The existing abandoned-run check occurs on a later claim; there is no new watchdog or schedule. Public publishing remains unimplemented and hard-blocked, and approved media has not yet been recovered.

## Release and rollback

No new service, migration, provider, credential, workflow activation, public post or paid plan is needed for this repair. Code, tests, this document and BUILD_STATUS belong to the same PR. The old build log is preserved byte-for-byte under its root-level history filename so standing history and links remain accessible.

Deploy only after current-head checks pass. Read the PR's final deployment evidence for actual release status; source existence alone is not deployment. Rollback is the previous application build with flags off; retain all database and n8n history.
