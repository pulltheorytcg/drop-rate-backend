# Automation Event Backlog Reconciliation

## Purpose

Drop Rate must not start its n8n dispatcher with a queue full of historical events whose underlying business action already completed outside the automation path.

As of 30 September 2026:
- 396 `inventory.approved` events are PENDING;
- all 396 corresponding physical inventory items already have a `PUBLISHED` Shopify inventory link;
- none is still waiting for Shopify publication.

These events must not be marked DELIVERED because n8n never delivered them.
They must not be marked DEAD_LETTER because nothing failed.

The correct terminal state is **SUPERSEDED**.

## Guard

The database function:

`tcg.supersede_published_inventory_approved_events(reason, actor, limit)`

can only select events that are all of:
- status PENDING;
- event type `inventory.approved`;
- aggregate type `INVENTORY_ITEM`;
- aggregate Inventory ID exists;
- that Inventory ID currently has a Shopify link in `PUBLISHED`.

It updates only `tcg.automation_events`.

It does not change:
- inventory;
- ownership;
- Shopify state;
- price;
- order state;
- finance;
- settlements.

Every superseded event receives:
- `status = SUPERSEDED`;
- `superseded_at`;
- explicit `superseded_reason`;
- an `AUTOMATION_EVENT_SUPERSEDED` audit event containing old/new terminal state.

## Production sequence

1. Merge/test migration.
2. Apply migration once.
3. Re-run read-only backlog census.
4. Require exactly the expected historical PENDING/published set.
5. Call the guarded function with an explicit reason.
6. Verify:
   - PENDING historical count = 0;
   - SUPERSEDED count = expected;
   - published Shopify link count unchanged;
   - inventory count/status unchanged;
   - audit event count matches.
7. Only then proceed toward dispatcher activation.

## Future use

SUPERSEDED is not a general “hide this event” button.

Use it only when a later state/action has provably made the original event obsolete and no consumer should execute it anymore.

Normal failed events remain DEAD_LETTER.
Successfully handled events remain DELIVERED.
