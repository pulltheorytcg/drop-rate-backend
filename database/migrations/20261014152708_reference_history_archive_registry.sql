begin;

-- A small audit receipt for immutable evidence moved to verified external storage.
-- Creating this registry does not remove history or grant API access.
create table tcg.reference_history_archives (
 archive_id text primary key,
 cutoff_at timestamptz not null,
 row_count bigint not null check(row_count > 0),
 content_root_sha256 text not null check(content_root_sha256 ~ '^[0-9a-f]{64}$'),
 drive_file_id text not null,
 drive_file_url text not null check(drive_file_url like 'https://drive.google.com/%'),
 archive_file_sha256 text not null check(archive_file_sha256 ~ '^[0-9a-f]{64}$'),
 restore_verified_at timestamptz not null,
 archived_at timestamptz not null default clock_timestamp(),
 relation_bytes_before bigint not null check(relation_bytes_before >= 0)
);
alter table tcg.reference_history_archives enable row level security;
alter table tcg.reference_history_archives force row level security;
create policy reference_history_archive_admin on tcg.reference_history_archives
 for all to postgres using(true) with check(true);
revoke all on tcg.reference_history_archives from public,anon,authenticated,tcg_api;
comment on table tcg.reference_history_archives is
 'Verified external price-history archives. Original rows remain recoverable from private Drive files. No inventory or current-price authority.';

-- Admin-only and SECURITY INVOKER: the caller still needs all underlying rights.
-- The caller must independently verify the durable backup and restore before use.
-- An exclusive lock plus a hash of every original field rejects stale archives.
create function tcg.archive_verified_reference_history(
 p_archive_id text,p_cutoff_at timestamptz,p_row_count bigint,
 p_content_root_sha256 text,p_drive_file_id text,p_drive_file_url text,
 p_archive_file_sha256 text,p_restore_verified_at timestamptz
) returns bigint language plpgsql security invoker
set search_path=pg_catalog set timezone='UTC' as $$
declare
 actual_count bigint;
 actual_root text;
 latest_at timestamptz;
 history_bytes bigint;
begin
 if p_row_count is null or p_row_count<=0
    or p_content_root_sha256 is null or p_content_root_sha256 !~ '^[0-9a-f]{64}$'
    or p_archive_file_sha256 is null or p_archive_file_sha256 !~ '^[0-9a-f]{64}$'
    or p_drive_file_id is null or p_drive_file_id=''
    or p_drive_file_url is null or p_drive_file_url not like 'https://drive.google.com/%'
    or p_restore_verified_at is null or p_cutoff_at is null then
  raise exception 'A complete verified archive receipt is required';
 end if;
 lock table tcg.reference_market_history in access exclusive mode;
 select count(*),max(h.recorded_at),
  encode(sha256(convert_to(string_agg(
   encode(sha256(convert_to(row_to_json(h)::text,'UTF8')),'hex'),'' order by h.id
  ),'UTF8')),'hex')
 into actual_count,latest_at,actual_root from tcg.reference_market_history h;
 if actual_count<>p_row_count or actual_root is distinct from p_content_root_sha256
    or latest_at>p_cutoff_at then
  raise exception 'History changed or archive does not match; no rows were removed';
 end if;
 history_bytes := pg_total_relation_size('tcg.reference_market_history');
 insert into tcg.reference_history_archives(
  archive_id,cutoff_at,row_count,content_root_sha256,drive_file_id,drive_file_url,
  archive_file_sha256,restore_verified_at,relation_bytes_before
 ) values(
  p_archive_id,p_cutoff_at,p_row_count,p_content_root_sha256,p_drive_file_id,p_drive_file_url,
  p_archive_file_sha256,p_restore_verified_at,history_bytes
 );
 -- No CASCADE and no change to the table, indexes, RLS or current-price caches.
 truncate table tcg.reference_market_history;
 return history_bytes-pg_total_relation_size('tcg.reference_market_history');
end;$$;
revoke all on function tcg.archive_verified_reference_history(text,timestamptz,bigint,text,text,text,text,timestamptz)
 from public,anon,authenticated,tcg_api;

commit;
