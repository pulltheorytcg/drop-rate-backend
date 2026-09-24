-- Normalize explicit language tags already present in imported card titles.
-- This is intentionally fail-closed: only explicit JP/Japanese title markers are
-- promoted to structured language. Untagged cards remain unresolved rather than
-- being guessed as English.

begin;

with jp_inventory as (
  select i.id
  from tcg.inventory_items i
  where i.language is null
    and coalesce(i.source_record->>'Product Name','') ~* '(\(|\[|\s)(jp|jpn|japanese)(\)|\]|\s|$)'
)
update tcg.inventory_items i
set language = 'Japanese'
where i.id in (select id from jp_inventory);

with jp_catalogues as (
  select
    p.id,
    regexp_replace(
      p.name,
      '\s*(\((JP|JPN|JAPANESE)\)|\[(JP|JPN|JAPANESE)\]|[-·|/]\s*(JP|JPN|JAPANESE)|\s+(JP|JPN|JAPANESE))\s*$',
      '',
      'i'
    ) as clean_name
  from tcg.catalogue_products p
  join tcg.inventory_items i on i.catalogue_id = p.id
  where p.language is null
    and i.language = 'Japanese'
  group by p.id, p.name
  having bool_and(
    coalesce(i.source_record->>'Product Name','') ~* '(\(|\[|\s)(jp|jpn|japanese)(\)|\]|\s|$)'
  )
)
update tcg.catalogue_products p
set name = j.clean_name,
    language = 'Japanese'
from jp_catalogues j
where p.id = j.id;

commit;
