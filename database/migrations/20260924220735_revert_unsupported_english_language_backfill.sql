-- Revert the unsupported 24 Sep 2026 NULL -> English bulk language backfill.
-- Explicit JP/Japanese evidence is untouched. English is preserved only when the
-- inventory is currently identity-confirmed and its latest physical confirmation
-- event explicitly records English.
--
-- This is a fail-closed data correction: unsupported English values return to NULL
-- so affected inventory remains DRAFT/REVIEW until a human confirms language.

select set_config('tcg.user_id', 'system:migration', true);
select set_config(
    'tcg.request_id',
    'migration:20260924220735_revert_unsupported_english_language_backfill',
    true
);

create temporary table tmp_unsupported_english_inventory
on commit drop
as
with latest_identity_event as (
    select distinct on (inventory_id)
        inventory_id,
        event_type,
        physical_snapshot
    from tcg.identity_verification_events
    order by inventory_id, created_at desc, id desc
)
select
    i.id,
    i.catalogue_id
from tcg.inventory_items i
left join latest_identity_event lie on lie.inventory_id = i.id
where i.language = 'English'
  and i.status in ('DRAFT', 'INSPECTION')
  and exists (
      select 1
      from tcg.audit_events ae
      where ae.entity_type = 'inventory_items'
        and ae.entity_id = i.id
        and ae.action = 'UPDATE'
        and ae.old_values->>'language' is null
        and ae.new_values->>'language' = 'English'
        and ae.request_id is null
        and ae.occurred_at >= timestamptz '2026-09-24 19:43:35+00'
        and ae.occurred_at < timestamptz '2026-09-24 19:43:36+00'
  )
  and lower(btrim(coalesce(i.source_record->>'Language', '')))
      not in ('en', 'eng', 'english')
  and not (
      i.identity_confirmed
      and lie.event_type = 'CONFIRMED'
      and lower(btrim(coalesce(lie.physical_snapshot->>'language', '')))
          in ('en', 'eng', 'english')
  );

update tcg.inventory_items i
set language = null,
    version = i.version + 1,
    updated_at = clock_timestamp()
where i.id in (select id from tmp_unsupported_english_inventory)
  and i.language = 'English';

update tcg.catalogue_products p
set language = null
where p.language = 'English'
  and p.id in (
      select distinct catalogue_id
      from tmp_unsupported_english_inventory
  )
  and not exists (
      select 1
      from tcg.inventory_items i
      where i.catalogue_id = p.id
        and i.language = 'English'
  );
