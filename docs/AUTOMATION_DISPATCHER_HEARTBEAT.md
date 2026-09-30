# Automation Dispatcher Heartbeat

## Purpose

Outbox health answers: **is automation work piling up or dead-lettering?**

Dispatcher heartbeat answers a different question: **is the dispatcher process itself alive?**

Both are required. A dead dispatcher can otherwise look healthy while the queue is empty.

## Write path

The dispatcher writes one current row keyed by `DISPATCHER` through:

`tcg.record_automation_component_heartbeat(...)`

The heartbeat row stores:
- component key;
- current instance/worker ID;
- component version;
- started-at timestamp for the current instance;
- last-seen timestamp.

The dispatcher:
1. records a heartbeat before entering the dispatch loop;
2. refreshes it periodically (default 30 seconds);
3. fails if the database heartbeat write fails rather than pretending it is healthy.

## Monitor

`tcg.check_automation_dispatcher_heartbeat(...)`

Default threshold: 90 seconds.

The checker has two modes:

### Dormant / observe
`TCG_AUTOMATION_DISPATCHER_ALERTS_ENABLED=false`

This is the production default until the dispatcher service is intentionally deployed.

Missing heartbeat is reported in logs but does not fail the combined operations monitor and does not create Action Required.

### Active
`TCG_AUTOMATION_DISPATCHER_ALERTS_ENABLED=true`

Only enable after the dispatcher service is deployed and its first heartbeat is confirmed.

A missing/stale heartbeat:
- makes the checker unhealthy;
- creates/updates founder CRITICAL `AUTOMATION_DISPATCHER_UNHEALTHY`;
- makes the combined operations monitor fail.

A healthy heartbeat resolves the prior open heartbeat exception.

## Deployment order

1. Apply heartbeat migration.
2. Deploy dispatcher service using `Dockerfile.automation`.
3. Verify `DISPATCHER` heartbeat appears and refreshes.
4. Verify signed n8n ingress in inactive/test mode.
5. Enable dispatcher heartbeat alerts.
6. Enable outbox-health alerts.
7. Only then treat event automation as production-active.

Do not enable alerts before the dispatcher exists.
