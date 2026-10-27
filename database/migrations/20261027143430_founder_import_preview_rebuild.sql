-- Replace only an untouched founder preview. Keep the runtime role's existing
-- table grants, source identity, inventory and canonical catalogue unchanged.
begin;

do $$
begin
 if exists(select 1 from pg_roles where rolname='tcg_api' and (rolsuper or rolbypassrls))
    or has_table_privilege('tcg_api','tcg.import_candidates','DELETE')
    or has_table_privilege('tcg_api','tcg.import_batches','UPDATE') then
  raise exception 'Import runtime permissions must remain restricted';
 end if;
 if not exists(select 1 from pg_class where oid='tcg.import_batches'::regclass
               and relrowsecurity and relforcerowsecurity)
    or not exists(select 1 from pg_class where oid='tcg.import_candidates'::regclass and relrowsecurity) then
  raise exception 'Existing import RLS must remain enabled';
 end if;
end $$;

create schema if not exists tcg_private authorization postgres;
revoke all on schema tcg_private from public,anon,authenticated;
grant usage on schema tcg_private to tcg_api;

-- SECURITY DEFINER is limited to this replacement because tcg_api intentionally
-- cannot DELETE candidates or UPDATE adapter/warnings/physical_units. No public
-- API roles can invoke it. Both actor membership and exact source rows are
-- checked independently of the trusted Python normalizer before any write.
create or replace function tcg_private.replace_import_preview(
 p_actor_id uuid,p_owner_id uuid,p_batch_id uuid,p_expected_version integer,
 p_source_sha256 text,p_adapter text,p_source_rows integer,p_physical_units integer,
 p_warnings jsonb,p_candidates jsonb
) returns jsonb language plpgsql security definer
set search_path=pg_catalog set lock_timeout='2s'
as $$
declare
 batch tcg.import_batches%rowtype;
 candidate jsonb;
 candidate_count integer;
 source_count integer;
 distinct_count integer;
 first_row integer;
 last_row integer;
 source_units bigint;
 replaced_count integer;
 new_version integer;
begin
 if p_actor_id is null or p_actor_id is distinct from tcg.current_user_id()
    or not coalesce(tcg.is_platform_admin(),false)
    or not exists(
      select 1 from tcg.owner_memberships m join tcg.owners o on o.id=m.owner_id
      where m.user_id=p_actor_id and m.owner_id=p_owner_id and m.active
        and m.role='PLATFORM_ADMIN' and o.active and o.owner_type='FOUNDER'
    ) then
  raise exception 'Authenticated founder owner required' using errcode='42501';
 end if;
 if p_batch_id is null or p_expected_version is null or p_expected_version < 1
    or p_source_sha256 is null or p_source_sha256 !~ '^[0-9a-f]{64}$'
    or p_adapter is null or p_adapter not in ('COLLECTR','EBAY_PURCHASES','HOLODEX','GENERIC_CSV')
    or p_source_rows is null or p_source_rows not between 1 and 5000
    or p_physical_units is null or p_physical_units not between 1 and 5000000
    or p_candidates is null or jsonb_typeof(p_candidates)<>'array'
    or p_warnings is null or jsonb_typeof(p_warnings)<>'array' then
  raise exception 'Invalid preview replacement' using errcode='22023';
 end if;
 candidate_count := jsonb_array_length(p_candidates);
 if candidate_count not between p_source_rows and 10000
    or octet_length(p_candidates::text)>33554432
    or jsonb_array_length(p_warnings)>16 or octet_length(p_warnings::text)>16384
    or exists(select 1 from jsonb_array_elements(p_warnings) w where jsonb_typeof(w)<>'string') then
  raise exception 'Preview replacement exceeds supported bounds' using errcode='22023';
 end if;

 -- Same lock order used by normal commit and automatic owner intake. Review
 -- updates take the batch row lock and therefore cannot race this replacement.
 perform pg_advisory_xact_lock(hashtextextended('tcg.collection.import:'||p_owner_id::text,0));
 select * into batch from tcg.import_batches
 where id=p_batch_id and owner_id=p_owner_id for update;
 if not found then
  raise exception 'Import batch not found' using errcode='P0002';
 end if;
 if batch.version<>p_expected_version or batch.status<>'PREVIEW'
    or batch.committed_at is not null or batch.automatic_intake
    or batch.last_auto_apply_version is not null
    or batch.source_sha256 is distinct from p_source_sha256
    or batch.source_rows is distinct from p_source_rows
    or batch.filename is null or lower(batch.filename) !~ '[.](csv|tsv)$' then
  raise exception 'Import changed or is not an uncommitted manual preview' using errcode='55000';
 end if;
 perform id from tcg.import_candidates where batch_id=p_batch_id for update;
 if exists(select 1 from tcg.import_candidates where batch_id=p_batch_id
           and (status='COMMITTED' or owner_id is distinct from p_owner_id))
    or exists(select 1 from tcg.inventory_items where import_batch_id=p_batch_id) then
  raise exception 'Preview already has physical copies or invalid ownership' using errcode='55000';
 end if;

 for candidate in select value from jsonb_array_elements(p_candidates) loop
  if jsonb_typeof(candidate)<>'object'
     or not candidate ?& array['source_row','quantity','raw_record','normalized_record','catalogue_id','status','issues']
     or candidate-array['source_row','quantity','raw_record','normalized_record','catalogue_id','status','issues']<>'{}'::jsonb
     or jsonb_typeof(candidate->'source_row')<>'number'
     or (candidate->>'source_row') !~ '^[0-9]{1,5}$'
     or (candidate->>'source_row')::integer not between 2 and 10001
     or jsonb_typeof(candidate->'quantity')<>'number'
     or (candidate->>'quantity') !~ '^[0-9]{1,4}$'
     or (candidate->>'quantity')::integer not between 1 and 1000
     or jsonb_typeof(candidate->'raw_record')<>'object'
     or jsonb_typeof(candidate->'normalized_record')<>'object'
     or jsonb_typeof(candidate->'catalogue_id') not in ('null','string')
     or coalesce(candidate->>'status','') not in ('READY','REVIEW','SKIPPED')
     or jsonb_typeof(candidate->'issues')<>'array' then
   raise exception 'Invalid preview candidate' using errcode='22023';
  end if;
  if exists(select 1 from jsonb_array_elements(candidate->'issues') issue where jsonb_typeof(issue)<>'string') then
   raise exception 'Invalid preview candidate issues' using errcode='22023';
  end if;
  if (candidate->>'source_row')::integer<=p_source_rows+1 then
   if coalesce(candidate->'normalized_record'->>'quantity','') !~ '^[0-9]{1,4}$'
      or (candidate->'normalized_record'->>'quantity')::integer not between 1 and 1000 then
    raise exception 'Invalid normalized source quantity' using errcode='22023';
   end if;
  elsif p_adapter<>'COLLECTR'
        or candidate->>'status'<>'REVIEW'
        or candidate->'normalized_record'->>'reconciliation' is distinct from 'SNAPSHOT_DELTA'
        or candidate->'normalized_record'->>'snapshot_quantity' is distinct from '0'
        or candidate->'issues'<> '["collectr_identity_missing_from_snapshot"]'::jsonb then
   raise exception 'Only Collectr missing-source reconciliation rows may be appended' using errcode='22023';
  end if;
 end loop;

 select count(*) filter(where c.source_row<=p_source_rows+1),count(distinct c.source_row),
        min(c.source_row),max(c.source_row),
        sum((c.normalized_record->>'quantity')::integer) filter(where c.source_row<=p_source_rows+1)
 into source_count,distinct_count,first_row,last_row,source_units
 from jsonb_to_recordset(p_candidates) c(source_row integer,normalized_record jsonb);
 if source_count<>p_source_rows or distinct_count<>candidate_count
    or first_row<>2 or last_row<>candidate_count+1 or source_units<>p_physical_units then
  raise exception 'Preview source rows or totals do not match' using errcode='22023';
 end if;
 -- Column/default corrections change interpretation, never the stored source
 -- evidence. Synthetic Collectr rows can change with the current baseline.
 if exists(
   select 1 from jsonb_to_recordset(p_candidates) c(source_row integer,raw_record jsonb)
   left join tcg.import_candidates old on old.batch_id=p_batch_id and old.source_row=c.source_row
   where c.source_row<=p_source_rows+1 and
     (old.id is null or old.owner_id<>p_owner_id or old.raw_record is distinct from c.raw_record)
 ) then
  raise exception 'Original source evidence cannot change' using errcode='22023';
 end if;

 delete from tcg.import_candidates where batch_id=p_batch_id and owner_id=p_owner_id;
 get diagnostics replaced_count=row_count;
 insert into tcg.import_candidates(batch_id,owner_id,source_row,quantity,raw_record,
                                   normalized_record,catalogue_id,status,issues)
 select p_batch_id,p_owner_id,c.source_row,c.quantity,c.raw_record,c.normalized_record,
        c.catalogue_id,c.status,c.issues
 from jsonb_to_recordset(p_candidates) c(source_row integer,quantity integer,raw_record jsonb,
       normalized_record jsonb,catalogue_id uuid,status text,issues jsonb);
 update tcg.import_batches set adapter=p_adapter,warnings=p_warnings,
        physical_units=p_physical_units,version=version+1
 where id=p_batch_id and owner_id=p_owner_id and version=p_expected_version
 returning version into new_version;
 return jsonb_build_object('batch_id',p_batch_id,'version',new_version,'status','PREVIEW',
        'replaced_candidates',replaced_count,'candidate_count',candidate_count,'created_count',0);
end $$;

alter function tcg_private.replace_import_preview(uuid,uuid,uuid,integer,text,text,integer,integer,jsonb,jsonb)
 owner to postgres;
revoke all on function tcg_private.replace_import_preview(uuid,uuid,uuid,integer,text,text,integer,integer,jsonb,jsonb)
 from public,anon,authenticated,tcg_api;
grant execute on function tcg_private.replace_import_preview(uuid,uuid,uuid,integer,text,text,integer,integer,jsonb,jsonb)
 to tcg_api;
comment on function tcg_private.replace_import_preview(uuid,uuid,uuid,integer,text,text,integer,integer,jsonb,jsonb) is
 'Founder-owned PREVIEW replacement only: exact source/version, no automatic intake or added copies. Does not grant general table write privileges.';

commit;
