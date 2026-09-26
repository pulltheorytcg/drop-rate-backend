-- Harden legacy migration metadata.
-- This table is infrastructure-only and must not be exposed to application roles.

alter table tcg.schema_migrations enable row level security;
alter table tcg.schema_migrations force row level security;

revoke all on table tcg.schema_migrations from public;
revoke all on table tcg.schema_migrations from anon;
revoke all on table tcg.schema_migrations from authenticated;
revoke all on table tcg.schema_migrations from service_role;
revoke all on table tcg.schema_migrations from tcg_api;
revoke all on table tcg.schema_migrations from tcg_auditor;

-- Intentionally no application-facing RLS policies.
-- The postgres owner remains the migration authority.
