-- The eBay publisher records both request and verified publication against the
-- channel link. Keep the original entity types, append-only grants and owner RLS.
-- One atomic ALTER leaves no interval with a missing integrity constraint.
set local lock_timeout = '5s';

alter table tcg.marketplace_audit_events
  drop constraint marketplace_audit_events_entity_type_check,
  add constraint marketplace_audit_events_entity_type_check
    check (entity_type in ('LISTING','MEMBERSHIP','RESERVATION','EBAY_INVENTORY_LINK'));
