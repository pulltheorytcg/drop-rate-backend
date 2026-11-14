# Supabase advisor repair — 14 November 2026

The four owner policies repeatedly evaluate a statement-constant actor setting.
The twelve supplied foreign keys have no complete leading-column index in the
live database. These changes improve their query plans without changing who can
read or write data. There are no application, UI, pricing, ownership or financial
record changes.

## Scope and independently verified preflight

Project `ozrxenrdladkooixutmm` (`pull-theory-dev`), PostgreSQL 17.6. Read-only SQL
editor inspection at 2026-11-14 14:13 UTC verified:

- `own_action_required_access`, `own_enrichment_access`, `own_asset_writes` are
  permissive ALL policies for `tcg_api`; `readable_assets` is SELECT for the same
  role. Exact original expressions match the supplied SQL. All three tables have
  enabled and forced RLS; `tcg_api` is neither superuser nor BYPASSRLS.
- All twelve requested single-column FKs exist, with no same-name or suitable
  non-partial leading-column index. The largest heap is `reference_sealed_products`
  at 2,703,360 bytes (3,893 estimated rows); `reference_sets` has 1,473 estimated
  rows, `media_assets` 507, enrichment 181 and action-required 96. Estimates are
  not claimed as exact row counts.
- The three tables have 12 policies and 30 table grants in total. The eight
  untargeted policies, including existing founder photo and shared product-image
  access, must remain byte-for-byte unchanged. The existing canonical-card read
  branch is preserved; canonical writes still require active owner membership.
- The excluded marketing FK is confirmed as `(job_id, revision, created_by)`.
  Its existing `(job_id, revision, stage)` unique index is not full FK coverage.
  No thirteenth index is added to this requested twelve-index release.

## Files and failure handling

`database/migrations/20261114120000_advisor_owner_rls_initplans.sql` alters only
the four specified expressions. Before changing them it checks the exact original
or exact already-optimised expressions, roles, commands, permissiveness, forced RLS
and non-bypass application role. Unknown drift fails closed. `ALTER POLICY`
preserves the other policy properties and all grants. Each subquery reads the
transaction actor once per statement; the existing backend sets the actor in a
separate transaction-local statement before executing application queries.

`database/migrations/20261114121000_advisor_foreign_key_indexes.sql` checks each
FK and builds a non-unique B-tree only if coverage is missing. A matching name
with a different or invalid definition is an error. Equivalent existing full
leading-column B-trees prevent duplicate storage. Tables above 64 MiB require a
separately reviewed concurrent build instead of this small-table transaction.

Both transactions bound lock acquisition to 2 seconds, statements to 30 seconds
and idle transactions to 10 seconds. Ordinary index creation can briefly block
writes. A timeout aborts and rolls back that migration; do not automatically retry
or raise the limits. The entire index DO block has one 30-second statement limit.
There is no destructive cleanup and no RLS/trigger/constraint disablement.

## Migration history reconciliation

The existing canonical CardTrader job migration filename starts `20261114100000`,
but production recorded `20261114101405`. A read-only query confirmed one statement,
849 bytes, MD5 `a1edd2313e3342293cc5addcca32e154`, exactly matching the canonical
file. The existing history-aware staging manifest now maps that timestamp. This
does not edit remote history or replay the CardTrader migration. It prevents
unrelated already-applied DDL from appearing pending during this release.

The first preview run `43604146804` failed before any database connection: the
GitHub runner's default Python 3.14 could not build the pinned backend dependency
(PyO3 supported at most 3.13). The migration workflow now explicitly selects the
same Python 3.12 runtime used by backend CI. Dependency pins and database
credentials are unchanged; a successful replacement preview remains mandatory.

## Release and evidence gates

1. Run migration-layout/staging tests and the disposable PostgreSQL regression
   workflow on the exact PR head. Validate before/after effective access, prepared
   statements across actor changes, inactive/missing/invalid actor context, grants,
   unrelated policies, foreign keys, rollback, idempotency and lock contention.
2. Review and merge the tested branch. Run the existing **Supabase migration gate**
   in `dry-run` mode. The pending list must contain only the two advisor migrations.
   Stop on any unexpected history or pending SQL; do not repair history blindly.
3. Run the same workflow in `apply` mode. No separate manual SQL-editor DDL or
   new migration runner is needed. The requested `apply_migration` connector is
   unavailable in this session; this is the repository's canonical apply path.
4. Independently inspect live policy expressions, RLS, role flags and all grants;
   validate twelve ready/valid indexes and FK coverage, unchanged constraints,
   recorded migration history, healthy Railway release and HTTP readiness. Unit
   tests are not production proof. Save the actual release receipt separately.

## Rollback

`20261114_advisor_policy_rollback.sql` in this directory restores all four exact
original policy expressions, with the same drift guards and lock bounds. Execute
only as a reviewed rollback; it is deliberately outside forward migration staging.
Additive indexes can remain safely during policy rollback. Do not automatically
drop indexes: first verify the preflight showed each exact name absent and that
its current definition still matches this release. A code rollback does not by
itself revert already-applied database DDL. No rollback changes user data or grants.

## References

- [Supabase RLS performance guidance](https://supabase.com/docs/guides/database/postgres/row-level-security#call-functions-with-select): statement-level subqueries apply only to values independent of the current row.
- [PostgreSQL CREATE INDEX](https://www.postgresql.org/docs/17/sql-createindex.html): ordinary builds block writes; `IF NOT EXISTS` alone does not verify an existing index definition.

Status at preparation: source preflight complete; no production migration applied.
