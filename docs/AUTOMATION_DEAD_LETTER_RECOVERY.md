# Automation Dead-Letter Recovery

## Purpose

Drop Rate must be able to recover automation failures without:
- editing outbox rows manually;
- erasing failure history;
- replaying already delivered work;
- replaying deliberately superseded historical work;
- trusting n8n to decide what state is safe to retry.

The recovery path is therefore restricted to **DEAD_LETTER** events only.

## Operator visibility

Platform admins can use:

`GET /api/v1/automation/operations/events`

Filters:
- `status`
- `event_type`
- `limit`

The response intentionally excludes the raw event payload.

Visible operational fields include:
- event ID;
- owner ID;
- event type/version;
- aggregate identity;
- idempotency key;
- status;
- attempts/max attempts;
- available/next-attempt timestamps;
- delivered/dead-lettered/superseded timestamps;
- last error code;
- superseded reason.

This is a diagnostic/recovery view, not business-state authority.

## Replay

Platform admins can request:

`POST /api/v1/automation/operations/events/{event_id}/replay`

Body:

```json
{"reason":"Provider recovered after outage"}
```

Rules:
1. event must exist;
2. event must currently be `DEAD_LETTER`;
3. reason is mandatory and bounded;
4. authenticated admin user becomes the audit actor;
5. request ID is carried into the audit event;
6. attempt count is **not reset**;
7. max attempts is only increased enough to permit one additional claim;
8. event returns to `PENDING` and is immediately due;
9. `last_error_code` becomes `MANUAL_REPLAY_REQUESTED`;
10. an `AUTOMATION_EVENT_REPLAY_REQUESTED` audit row is inserted.

Replay cannot be used on:
- `DELIVERED`;
- `SUPERSEDED`;
- `PENDING`;
- `DISPATCHING`.

## Why replay does not create a second event

The existing event keeps its immutable envelope/idempotency key and its attempt history.

Creating a new automation event with a new idempotency key for the same failed business event would weaken traceability and could allow duplicate business actions.

The replay operation therefore re-queues the same DEAD_LETTER envelope without erasing its attempt count.

## Security

- raw `tcg.automation_events` remains unavailable to user roles;
- `tcg_api` receives execute-only access to narrow SECURITY DEFINER functions;
- API endpoint is platform-admin protected;
- actor is derived from authentication;
- n8n cannot call this admin replay endpoint as a generic retry mechanism;
- no inventory, owner, order, Shopify, price, settlement or ledger state is directly mutated.

## Recovery procedure

When an automation event dead-letters:

1. inspect the corresponding Action Required / workflow error;
2. inspect provider/backend health;
3. identify and fix the underlying cause;
4. inspect the dead-letter event metadata through the admin API;
5. verify the underlying business action is still valid and has not already completed another way;
6. replay with an explicit reason;
7. observe dispatcher/n8n processing;
8. verify downstream state through the authoritative FastAPI/Postgres reconciliation path;
9. if it fails again, investigate again rather than repeatedly replaying.

## SUPERSEDED is different

A SUPERSEDED event was deliberately retired because later state made the original action obsolete.

It is not a failed event and must never be replayed.

For example, the 396 historical `inventory.approved` events superseded on 30 September 2026 already had PUBLISHED Shopify links and are permanently terminal historical records.
