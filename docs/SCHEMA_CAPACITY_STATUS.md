# Schema and Capacity Status

_Checked: 23 September 2026_

## Live Supabase project

- Plan: Free
- Region: eu-west-2
- PostgreSQL: 17.6
- Database size: ~14 MB
- `tcg` tables: 22 after market ingestion run history
- Foreign-key relationships: 35 after the Auth membership relationship and ingestion-run owner relationship
- Direct DB max connections: 60
- Connections observed during review: 7 total, 1 active

The database is currently small and lightly loaded. The likely first storage-growth pressure is append-only market evidence rather than inventory/order rows.

## Visualizer integrity fix

`tcg.owner_memberships.user_id` now has a real foreign key to `auth.users(id)` with `ON DELETE CASCADE`.

Intentional identifier fields that should not be foreign keys include polymorphic audit entity IDs and third-party source product/variant IDs.

## Monitoring policy

- monitor database size and connection usage regularly
- review Supabase advisors after DDL changes
- keep market evidence deduplicated by provider record key
- keep raw provider metadata bounded
- plan a paid compute/database tier before production marketplace traffic or high-frequency automated market ingestion
