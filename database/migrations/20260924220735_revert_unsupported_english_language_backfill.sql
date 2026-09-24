-- Revert the unsupported 24 Sep 2026 NULL -> English bulk language backfill.
-- Keep explicit JP/Japanese evidence untouched and preserve any English card that has
-- subsequently gained a current physical CONFIRMED identity event.
--
-- This is a data-correction migration. It is intentionally fail-closed: unsupported
-- English values return to NULL so the inventory remains DRAFT/REVIEW until a human
-- confirms language.

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
  and not (
      coalesce(i.source_record->>'Language', '') ~* '^(en|eng|english)$'
      or coalesce(i.source_record->>'Product Name', '') ~*
         '(\\(|\\[|\\s)(en|eng|english)(\\)|\\]|\\s|$)'
  )
  and not (
      i.identity_confirmed
      and lie.event_type = 'CONFIRMED'
      and coalesce(lie.physical_snapshot->>'language', '') ~* '^(en|eng|english)

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
