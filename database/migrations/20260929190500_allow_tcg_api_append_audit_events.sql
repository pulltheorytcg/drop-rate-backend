begin;

-- The API role may append explicit operational audit events, but it must not
-- gain read or mutation access to immutable audit history.
grant insert on table tcg.audit_events to tcg_api;
grant usage on sequence tcg.audit_events_id_seq to tcg_api;

revoke select, update, delete on table tcg.audit_events from tcg_api;
revoke select, update on sequence tcg.audit_events_id_seq from tcg_api;

drop policy if exists audit_api_insert on tcg.audit_events;
create policy audit_api_insert
on tcg.audit_events
for insert
to tcg_api
with check (
  tcg.is_platform_admin()
  and tcg.current_user_id() is not null
  and actor = tcg.current_user_id()::text
);

commit;
