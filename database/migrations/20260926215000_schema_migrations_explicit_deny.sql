-- Make the infrastructure-only intent explicit for the application role.
-- Privileges remain revoked; this deny-all RLS policy documents the boundary and
-- satisfies security linting without granting any access.

drop policy if exists schema_migrations_deny_application
on tcg.schema_migrations;

create policy schema_migrations_deny_application
on tcg.schema_migrations
for all
to tcg_api
using (false)
with check (false);
