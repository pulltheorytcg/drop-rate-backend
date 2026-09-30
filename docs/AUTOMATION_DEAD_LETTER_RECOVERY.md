# Automation Dead-Letter Recovery

## Purpose

Normal Drop Rate automation failures retry automatically through the outbox retry policy.

Dead-letter recovery exists only for events that exhausted that retry budget and still require processing after the underlying problem is fixed.

It is an exception-control path, not a routine retry mechanism.

## Visibility

Founder HQ admins can read:

`GET /api/v1/automation/recovery/dead-letters`

The response intentionally excludes event payload contents and exposes only operational identity/state needed to investigate:
- event ID;
- owner ID;
- event type/schema version;
- aggregate type/ID;
- idempotency key;
- attempts/max attempts;
- last error code;
- creation/update/dead-letter timestamps.

## Replay

Founder HQ admins can call:

`POST /api/v1/automation/recovery/dead-letters/{event_id}/replay`

with a required human-readable reason.

The database function independently verifies:
- actor user ID has an active PLATFORM_ADMIN membership;
- its owner is an active FOUNDER;
- target event exists;
- target status is exactly DEAD_LETTER.

Replay changes only orchestration delivery state:
- DEAD_LETTER → PENDING;
- next attempt → now;
- lease/dead-letter state cleared;
- last error marker becomes `MANUAL_REPLAY_REQUESTED`.

It preserves:
- event ID;
- event type/schema;
- owner;
- aggregate;
- idempotency key;
- payload;
- existing `attempt_count` history.

The retry ceiling is increased only enough to permit one additional claim. Replay does not reset the historical attempt counter.

DELIVERED and SUPERSEDED history cannot be replayed through this function.

## Audit

Every successful replay request writes `AUTOMATION_EVENT_REPLAY_REQUESTED` to `tcg.audit_events` with:
- actor user;
- originating request ID;
- old terminal/error state;
- new PENDING state;
- preserved attempt history;
- explicit replay reason.

## Future intelligence

The long-term automation system may diagnose dead letters, group recurring causes and propose the correct remediation automatically.

It must not silently replay terminal events merely because AI believes a failure is transient. The deterministic retry policy handles routine transient failures before dead-lettering.

Any future autonomous dead-letter replay class needs a separate allowlist/policy proving the failure class is safe and idempotent.
