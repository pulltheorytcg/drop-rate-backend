# Drop Rate — Supabase Capacity Plan

_Last reviewed: 23 September 2026_

## Current live state

- Supabase organisation plan: Free
- Compute class: Nano (Free)
- PostgreSQL: 17
- `tcg` tables: 21
- `tcg` foreign keys: 34 after the Auth membership FK fix
- Database size at review: ~14 MB
- Direct connection ceiling: 60
- Connections observed at review: 7 total / 1 active

## Current assessment

The core inventory/commerce schema is small and has substantial headroom. The first expected database-growth pressure is `tcg.market_observations`, because pricing evidence is append-only by design and will accumulate continuously as provider ingestion is enabled.

## Scaling policy

1. Keep market observations immutable.
2. Deduplicate by provider source record key before insert.
3. Keep provider raw metadata bounded; do not mirror entire third-party payloads unnecessarily.
4. Monitor database size, market-observation row count, query latency, connection count, and index size.
5. Alert internally at 50%, 70%, and 85% of the current database quota.
6. Upgrade from Free/Nano before public launch or before high-frequency automated market-data ingestion becomes business-critical.
7. Prefer query/index optimization before increasing compute, but do not run production commerce on a resource-constrained tier once sustained load appears.

## Visualizer integrity

`tcg.owner_memberships.user_id` is now formally constrained to `auth.users(id)` with `ON DELETE CASCADE`, allowing schema tooling to show the real Auth-to-owner membership relationship and enforcing referential integrity.

Intentional non-FK identifier columns include polymorphic audit identifiers and third-party provider identifiers such as source product/variant IDs.
