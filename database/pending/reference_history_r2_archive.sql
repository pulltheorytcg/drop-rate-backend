begin;

create schema if not exists tcg_private authorization postgres;
revoke all on schema tcg_private from public,anon,authenticated;
grant usage on schema tcg_private to tcg_api;

create table tcg.reference_history_r2_archives (
 archive_id text primary key,
 row_count bigint not null check(row_count between 1 and 100000),
 content_root_sha256 text not null check(content_root_sha256 ~ '^[0-9a-f]{64}$'),
 storage_endpoint text not null,
 storage_bucket text not null,
 archive_object_key text not null,
 manifest_object_key text not null,
 archive_file_sha256 text not null check(archive_file_sha256 ~ '^[0-9a-f]{64}$'),
 manifest_file_sha256 text not null check(manifest_file_sha256 ~ '^[0-9a-f]{64}$'),
 restore_verified_at timestamptz not null,
 archived_at timestamptz not null default clock_timestamp(),
 archived_by uuid not null,
 request_id text,
 relation_bytes_before bigint not null,
 relation_bytes_after bigint not null,
 earliest_recorded_at timestamptz not null,
 latest_recorded_at timestamptz not null
);
alter table tcg.reference_history_r2_archives enable row level security;
alter table tcg.reference_history_r2_archives force row level security;
create policy reference_history_r2_postgres on tcg.reference_history_r2_archives
 for all to postgres using(true) with check(true);
revoke all on tcg.reference_history_r2_archives from public,anon,authenticated,tcg_api;
comment on table tcg.reference_history_r2_archives is
 'Private R2 history archive receipts after byte and typed restore verification. Current prices and inventory remain authoritative in PostgreSQL.';

-- A narrowly scoped capability, not general DELETE/TRUNCATE access for tcg_api.
-- SECURITY DEFINER is necessary solely to encapsulate the existing postgres-only
-- history cleanup privilege. Kept in a non-API schema; every call authenticates
-- the existing backend actor AND verifies current platform-admin membership.
-- Upload/download/typed restore verification must happen in the trusted worker.
-- SQL independently checks all live original fields under a short final lock.
create function tcg_private.archive_verified_reference_history_r2(
 p_archive_id text,p_row_count bigint,p_content_root_sha256 text,
 p_archive_object_key text,p_manifest_object_key text,
 p_archive_file_sha256 text,p_manifest_file_sha256 text,
 p_storage_endpoint text,p_storage_bucket text,p_restore_verified_at timestamptz
) returns jsonb language plpgsql security definer
set search_path=pg_catalog set timezone='UTC' set lock_timeout='2s'
as $$
declare
 actual_count bigint;
 actual_root text;
 bytes_before bigint;
 bytes_after bigint;
 earliest_at timestamptz;
 latest_at timestamptz;
 prior tcg.reference_history_r2_archives%rowtype;
begin
 if tcg.current_user_id() is null or not coalesce(tcg.is_platform_admin(),false) then
  raise exception 'Platform administrator required' using errcode='42501';
 end if;
 -- A stale transaction snapshot could miss committed inserts before TRUNCATE.
 if current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'Archive cleanup requires a fresh read committed transaction';
 end if;
 if p_archive_id is null or length(p_archive_id) not between 1 and 160
    or p_row_count is null or p_row_count not between 1 and 100000
    or p_content_root_sha256 is null or p_content_root_sha256 !~ '^[0-9a-f]{64}$'
    or p_archive_file_sha256 is null or p_archive_file_sha256 !~ '^[0-9a-f]{64}$'
    or p_manifest_file_sha256 is null or p_manifest_file_sha256 !~ '^[0-9a-f]{64}$'
    or p_archive_object_key is null
    or p_archive_object_key !~ ('^[A-Za-z0-9_-]+/reference-history/' || p_archive_file_sha256 || '[.]ndjson[.]gz$')
    or p_manifest_object_key is null
    or p_manifest_object_key !~ ('^[A-Za-z0-9_-]+/reference-history/' || p_manifest_file_sha256 || '([.]manifest)?[.]json$')
    or split_part(p_archive_object_key,'/',1) <> split_part(p_manifest_object_key,'/',1)
    or p_storage_endpoint is null
    or p_storage_endpoint !~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$'
    or p_storage_bucket is null or p_storage_bucket !~ '^[A-Za-z0-9._-]{1,255}$'
    or p_restore_verified_at is null
    or p_restore_verified_at > clock_timestamp()+interval '1 minute'
    or p_restore_verified_at < clock_timestamp()-interval '1 day' then
  raise exception 'A complete, recent verified private R2 archive receipt is required';
 end if;

 -- Serialize retry/commit across processes without blocking live inserts yet.
 perform pg_advisory_xact_lock(847220096);
 select * into prior from tcg.reference_history_r2_archives where archive_id=p_archive_id;
 if found then
  if (prior.row_count,prior.content_root_sha256,prior.archive_object_key,
      prior.manifest_object_key,prior.archive_file_sha256,prior.manifest_file_sha256,
      prior.storage_endpoint,prior.storage_bucket)
     is distinct from
     (p_row_count,p_content_root_sha256,p_archive_object_key,p_manifest_object_key,
      p_archive_file_sha256,p_manifest_file_sha256,p_storage_endpoint,p_storage_bucket) then
   raise exception 'Archive receipt identity cannot be reused for different content';
  end if;
  return jsonb_build_object('status','ALREADY_ARCHIVED','rows_archived',prior.row_count,
                            'bytes_reclaimed',0,'archive_id',p_archive_id);
 end if;
 lock table tcg.reference_market_history in access exclusive mode;
 select count(*),min(h.recorded_at),max(h.recorded_at),
  encode(sha256(convert_to(string_agg(
   encode(sha256(convert_to(row_to_json(h)::text,'UTF8')),'hex'),'' order by h.id
  ),'UTF8')),'hex')
 into actual_count,earliest_at,latest_at,actual_root
 from tcg.reference_market_history h;
 if actual_count <> p_row_count or actual_root is distinct from p_content_root_sha256 then
  raise exception 'History changed or restored archive differs; no rows were removed';
 end if;
 bytes_before := pg_total_relation_size('tcg.reference_market_history');
 truncate table tcg.reference_market_history;
 bytes_after := pg_total_relation_size('tcg.reference_market_history');
 insert into tcg.reference_history_r2_archives (
   archive_id,row_count,content_root_sha256,storage_endpoint,storage_bucket,
   archive_object_key,manifest_object_key,archive_file_sha256,manifest_file_sha256,
   restore_verified_at,archived_by,request_id,relation_bytes_before,relation_bytes_after,
   earliest_recorded_at,latest_recorded_at
 ) values (
   p_archive_id,p_row_count,p_content_root_sha256,p_storage_endpoint,p_storage_bucket,
   p_archive_object_key,p_manifest_object_key,p_archive_file_sha256,p_manifest_file_sha256,
   p_restore_verified_at,tcg.current_user_id(),current_setting('tcg.request_id',true),
   bytes_before,bytes_after,earliest_at,latest_at
 );
 return jsonb_build_object('status','ARCHIVED','rows_archived',actual_count,
                           'bytes_reclaimed',bytes_before-bytes_after,'archive_id',p_archive_id);
end;$$;
revoke all on function tcg_private.archive_verified_reference_history_r2(text,bigint,text,text,text,text,text,text,text,timestamptz)
 from public,anon,authenticated;
grant execute on function tcg_private.archive_verified_reference_history_r2(text,bigint,text,text,text,text,text,text,text,timestamptz)
 to tcg_api;
commit;
