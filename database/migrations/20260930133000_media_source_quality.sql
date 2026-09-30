begin;

alter table tcg.media_assets
  add column if not exists source_width_px integer,
  add column if not exists source_height_px integer,
  add column if not exists source_quality_status text not null default 'UNMEASURED';

alter table tcg.media_assets
  drop constraint if exists media_assets_source_width_positive;
alter table tcg.media_assets
  add constraint media_assets_source_width_positive
  check (source_width_px is null or source_width_px > 0);

alter table tcg.media_assets
  drop constraint if exists media_assets_source_height_positive;
alter table tcg.media_assets
  add constraint media_assets_source_height_positive
  check (source_height_px is null or source_height_px > 0);

alter table tcg.media_assets
  drop constraint if exists media_assets_source_quality_status_check;
alter table tcg.media_assets
  add constraint media_assets_source_quality_status_check
  check (source_quality_status in ('UNMEASURED','BELOW_TARGET','TARGET_MET'));

commit;
