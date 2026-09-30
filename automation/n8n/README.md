# Drop Rate n8n provisioning

This directory makes production n8n workflows version-controlled and reproducible without exposing the n8n editor publicly.

## Rules

- Base image is pinned in `Dockerfile.n8n`.
- Workflow JSON contains no credentials or secrets.
- Startup provisioning is additive: it imports a workflow only when its stable workflow ID is absent.
- Startup must never delete/recreate the n8n SQLite database.
- Existing persistent workflows are not silently overwritten.
- Workflow publishing is a separate deliberate step after import/validation.
- Secrets remain Railway environment variables / n8n credentials, never Git.

## Why additive first

Blind re-imports can overwrite a workflow while an older execution is running or erase a manual emergency correction. V1 therefore bootstraps missing workflows only. A later deployment tool can perform explicit, version-aware updates with backup/rollback.

## Production migration gates

Before switching the existing n8n service from the stock image:

1. Build the derived image in CI.
2. Validate every workflow JSON.
3. Confirm n8n owner/project initialization supports CLI import.
4. Confirm the persistent volume is mounted at application start.
5. Take/verify a recoverable n8n database backup.
6. Deploy with the same encryption key and user-folder settings.
7. Verify health, workflow list and webhook registration.
8. Redeploy once more and prove the workflow/database persist.
9. Only then point the automation dispatcher at DR-00.

No public n8n domain is required for this provisioning model.

The startup provisioner deliberately refuses to start if the DR-00 runtime requirements above are missing. This is safer than starting an apparently healthy n8n service whose signed ingress can never authenticate events.


## DR-00 signed ingress

`DR00IngressV1` is the first version-controlled ingress workflow. It is intentionally imported **inactive**.

Runtime requirements before activation:

- `DROP_RATE_AUTOMATION_WEBHOOK_SECRET` must match the dispatcher secret and be at least 32 characters.
- Set `NODE_FUNCTION_ALLOW_BUILTIN=crypto` so the Code node can use Node's HMAC implementation.
- Set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` because n8n 2.x blocks `$env` access by default and DR-00 reads only `DROP_RATE_AUTOMATION_WEBHOOK_SECRET` from `$env`.
- Treat that env-access setting as a security boundary: only trusted, version-controlled Code workflows may run on this n8n instance, and the service environment should contain only secrets it genuinely requires.
- Requests older/newer than five minutes are rejected.
- The Webhook node preserves the raw request body; HMAC is verified over those exact bytes with a timing-safe comparison before the event can be acknowledged.
- Invalid signatures/envelopes receive HTTP 401; valid envelopes receive HTTP 202.

**Important:** do not activate DR-00 merely because it imports successfully. A 202 causes the dispatcher to ACK the outbox event. Activation therefore waits until the event router/handler is connected and an end-to-end test proves that accepted events are durably handled rather than swallowed.


## Launch operating system

The founder-approved pre-launch strategy is documented in:

- `docs/N8N_LAUNCH_OPERATING_SYSTEM.md`
- `automation/n8n/workflow-registry.json`

The strategy is **build broad / activate narrow**.

All 42 workflow families may be designed and implemented before launch, but a workflow may not become ACTIVE until its registry activation requirements are satisfied.

The control plane is the first implementation wave:
- global error workflow;
- Action Required bridge;
- execution receipts;
- dead-letter/replay visibility;
- backlog/heartbeat monitoring;
- workflow health.

The registry is source-controlled and tested. n8n UI state is never the authoritative workflow catalogue.

## DR-90 global error workflow

`DR90GlobalErrorV1` is the first control-plane workflow.

It is imported **inactive** until the backend receipt endpoint and matching runtime secrets are deployed and a synthetic failure is proven end-to-end.

Flow:

`n8n Error Trigger → normalize execution → HMAC-sign receipt → FastAPI /api/v1/automation/control/receipt → automation_runs + Action Required`

Rules:
- the workflow itself must not use itself as its own Error Workflow;
- failed execution IDs are idempotent;
- duplicate receipt delivery is a no-op;
- system-level failures fan out only to active founder Action Required queues;
- n8n cannot choose Action Required severity/category/code;
- no inventory/ownership/price/settlement mutation occurs;
- `DROP_RATE_AUTOMATION_COMMAND_SECRET` must match FastAPI `TCG_AUTOMATION_COMMAND_SECRET`;
- `DROP_RATE_API_AUTOMATION_CONTROL_URL` points to the governed FastAPI receipt endpoint.

Before activation:
1. deploy backend receipt endpoint;
2. configure matching command secret;
3. configure private/internal FastAPI control URL;
4. import DR-90;
5. trigger one synthetic failure;
6. prove exactly one automation_run per founder and one deduped Action Required per founder;
7. replay the same receipt and prove no duplicate state;
8. only then set DR-90 as the error workflow for other workflows.
