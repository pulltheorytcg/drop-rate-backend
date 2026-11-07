-- Read-only deployment preflight for automation_control_runtime_repair.
-- This file has NOT been executed against production by its author.
-- Run only after the Supabase query/request-state problem has been resolved.
-- A migration ledger entry or a successful local fixture is not live proof.
-- Compare the complete current heartbeat definition, owner, ACL and role/RLS
-- state with the reviewed baseline before applying any production migration.
-- Every required conflict key must have a usable nondeferrable unique index
-- and no matching deferrable index that ON CONFLICT could also infer.
-- Missing objects, withheld definitions or truncated metadata require review;
-- they must not be treated as an affirmative deployment-readiness result.
--
-- Scope: system catalogues and exact migration ledger metadata only. No owner,
-- inventory, receipt, alert or other application row contents are selected.
-- Bounds: two exact function signatures; four tables; 16 policies, 16 indexes
-- and 64 explicit column ACLs per table; 32 direct runtime-role memberships;
-- 16 matching migration records. Full function definitions are capped at 64 KiB
-- with an explicit withheld flag and a SHA-256 fingerprint if larger.

with
runtime_role as (
  select r.* from pg_catalog.pg_roles r where r.rolname='tcg_api'
),
checked_roles(role_name) as (
  values ('tcg_api'),('anon'),('authenticated'),('service_role'),('tcg_auditor')
),
expected_functions(label,identity) as (
  values
    ('heartbeat','tcg.record_automation_heartbeat(text,text,text,timestamp with time zone)'),
    ('execution_receipt','tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamp with time zone,uuid,uuid,text,text)')
),
functions as (
  select f.label,f.identity,p.*,n.nspname,
         case when p.oid is not null then pg_catalog.pg_get_functiondef(p.oid) end as definition
  from expected_functions f
  left join pg_catalog.pg_proc p on p.oid=pg_catalog.to_regprocedure(f.identity)
  left join pg_catalog.pg_namespace n on n.oid=p.pronamespace
),
expected_tables(table_name) as (
  values ('owners'),('automation_runs'),('action_required_items'),('automation_heartbeats')
),
tables as (
  select e.table_name,c.*
  from expected_tables e
  left join pg_catalog.pg_namespace n on n.nspname='tcg'
  left join pg_catalog.pg_class c on c.relnamespace=n.oid and c.relname=e.table_name
    and c.relkind in ('r','p')
),
policies as (
  select p.*,row_number() over(partition by p.tablename order by p.policyname) as ordinal
  from pg_catalog.pg_policies p
  where p.schemaname='tcg' and p.tablename in (select table_name from expected_tables)
),
column_acls as (
  select a.attrelid,a.attname,a.attacl,
         row_number() over(partition by a.attrelid order by a.attnum) as ordinal
  from pg_catalog.pg_attribute a
  where a.attrelid in (select oid from tables) and a.attnum>0 and not a.attisdropped
    and a.attacl is not null
),
memberships as (
  select granted.rolname,granted.rolsuper,granted.rolbypassrls,
         am.admin_option,am.inherit_option,am.set_option,
         row_number() over(order by granted.rolname) as ordinal
  from pg_catalog.pg_auth_members am
  join runtime_role runtime on runtime.oid=am.member
  join pg_catalog.pg_roles granted on granted.oid=am.roleid
),
index_shapes as (
  select t.table_name,i.*,ic.relname as index_name,
         pg_catalog.pg_get_indexdef(i.indexrelid) as definition,
         array(select a.attname::text
               from unnest(i.indkey) with ordinality k(attnum,position)
               join pg_catalog.pg_attribute a on a.attrelid=i.indrelid and a.attnum=k.attnum
               where k.position<=i.indnkeyatts order by k.position) as key_columns,
         array(select a.attname::text
               from unnest(i.indkey) with ordinality k(attnum,position)
               join pg_catalog.pg_attribute a on a.attrelid=i.indrelid and a.attnum=k.attnum
               where k.position<=i.indnkeyatts order by a.attname) as sorted_key_columns,
         con.conname as constraint_name,con.contype as constraint_type,
         con.condeferrable,con.condeferred,
         row_number() over(partition by t.table_name order by ic.relname) as ordinal
  from tables t
  join pg_catalog.pg_index i on i.indrelid=t.oid
  join pg_catalog.pg_class ic on ic.oid=i.indexrelid
  left join pg_catalog.pg_constraint con on con.conindid=i.indexrelid
    and con.conrelid=i.indrelid and con.contype in ('p','u','x')
),
required_keys(table_name,sorted_columns) as (
  values
    ('automation_runs',array['job_type','owner_id','run_key']::text[]),
    ('action_required_items',array['dedupe_key','owner_id']::text[])
),
ledger as (
  select m.version,m.name,row_number() over(order by m.version,m.name) as ordinal
  from supabase_migrations.schema_migrations m
  where m.version in ('20260930044501','20260930054500','20260930050000','20261027164716')
     or m.name in ('n8n_runtime_heartbeat','automation_runs_n8n_contract','automation_control_runtime_repair')
)
select jsonb_build_object(
  'captured_at',clock_timestamp(),
  'server_version',current_setting('server_version'),
  'runtime_role',(
    select jsonb_build_object('name',r.rolname,'superuser',r.rolsuper,'bypass_rls',r.rolbypassrls,
      'can_login',r.rolcanlogin,'inherits',r.rolinherit,'can_create_role',r.rolcreaterole,
      'can_create_database',r.rolcreatedb,'replication',r.rolreplication)
    from runtime_role r
  ),
  'runtime_direct_memberships',jsonb_build_object(
    'count',(select count(*) from memberships),
    'truncated',(select count(*)>32 from memberships),
    'items',coalesce((select jsonb_agg(jsonb_build_object('role',m.rolname,
      'superuser',m.rolsuper,'bypass_rls',m.rolbypassrls,'admin_option',m.admin_option,
      'inherit_option',m.inherit_option,'set_option',m.set_option) order by m.rolname)
      from memberships m where m.ordinal<=32),'[]'::jsonb)
  ),
  'functions',(
    select jsonb_agg(jsonb_build_object(
      'label',f.label,'expected_identity',f.identity,'present',f.oid is not null,
      'owner',pg_catalog.pg_get_userbyid(f.proowner),'security_definer',f.prosecdef,
      'configuration',f.proconfig,'volatility',f.provolatile,
      'identity_arguments',case when f.oid is not null then pg_catalog.pg_get_function_identity_arguments(f.oid) end,
      'result_signature',case when f.oid is not null then pg_catalog.pg_get_function_result(f.oid) end,
      'acl',coalesce(f.proacl,pg_catalog.acldefault('f',f.proowner))::text,
      'definition_bytes',octet_length(f.definition),
      'definition_withheld_oversized',coalesce(octet_length(f.definition)>65536,false),
      'definition',case when octet_length(f.definition)<=65536 then f.definition end,
      'body_sha256',case when f.oid is not null then encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') end,
      'execute_by_role',(select jsonb_agg(jsonb_build_object('role',cr.role_name,
        'role_present',r.oid is not null,
        'execute',case when r.oid is not null and f.oid is not null
          then pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE') end) order by cr.role_name)
        from checked_roles cr left join pg_catalog.pg_roles r on r.rolname=cr.role_name)
    ) order by f.label) from functions f
  ),
  'private_schema',(
    select jsonb_build_object('owner',pg_catalog.pg_get_userbyid(n.nspowner),
      'acl',coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))::text,
      'privileges',(select jsonb_agg(jsonb_build_object('role',cr.role_name,
        'role_present',r.oid is not null,
        'usage',case when r.oid is not null then pg_catalog.has_schema_privilege(r.oid,n.oid,'USAGE') end,
        'create',case when r.oid is not null then pg_catalog.has_schema_privilege(r.oid,n.oid,'CREATE') end)
        order by cr.role_name)
        from checked_roles cr left join pg_catalog.pg_roles r on r.rolname=cr.role_name))
    from pg_catalog.pg_namespace n where n.nspname='tcg_private'
  ),
  'tables',(
    select jsonb_agg(jsonb_build_object(
      'table',t.table_name,'present',t.oid is not null,
      'owner',pg_catalog.pg_get_userbyid(t.relowner),'rls',t.relrowsecurity,'force_rls',t.relforcerowsecurity,
      'acl',coalesce(t.relacl,pg_catalog.acldefault('r',t.relowner))::text,
      'runtime_privileges',case when t.oid is not null and r.oid is not null then jsonb_build_object(
        'select',pg_catalog.has_table_privilege(r.oid,t.oid,'SELECT'),
        'insert',pg_catalog.has_table_privilege(r.oid,t.oid,'INSERT'),
        'update',pg_catalog.has_table_privilege(r.oid,t.oid,'UPDATE'),
        'delete',pg_catalog.has_table_privilege(r.oid,t.oid,'DELETE'),
        'truncate',pg_catalog.has_table_privilege(r.oid,t.oid,'TRUNCATE'),
        'any_column_select',pg_catalog.has_any_column_privilege(r.oid,t.oid,'SELECT'),
        'any_column_insert',pg_catalog.has_any_column_privilege(r.oid,t.oid,'INSERT'),
        'any_column_update',pg_catalog.has_any_column_privilege(r.oid,t.oid,'UPDATE')) end,
      'explicit_column_acl_count',(select count(*) from column_acls a where a.attrelid=t.oid),
      'column_acls_truncated',(select count(*)>64 from column_acls a where a.attrelid=t.oid),
      'explicit_column_acls',coalesce((select jsonb_agg(jsonb_build_object('column',a.attname,'acl',a.attacl::text)
        order by a.ordinal) from column_acls a where a.attrelid=t.oid and a.ordinal<=64),'[]'::jsonb),
      'policy_count',(select count(*) from policies p where p.tablename=t.table_name),
      'policies_truncated',(select count(*)>16 from policies p where p.tablename=t.table_name),
      'policies',coalesce((select jsonb_agg(jsonb_build_object('name',p.policyname,'roles',p.roles,
        'command',p.cmd,'permissive',p.permissive,
        'using',case when octet_length(p.qual)<=16384 then p.qual end,
        'with_check',case when octet_length(p.with_check)<=16384 then p.with_check end,
        'expression_withheld_oversized',coalesce(octet_length(p.qual)>16384 or octet_length(p.with_check)>16384,false))
        order by p.policyname) from policies p where p.tablename=t.table_name and p.ordinal<=16),'[]'::jsonb)
    ) order by t.table_name) from tables t left join runtime_role r on true
  ),
  'required_unique_keys',(
    select jsonb_agg(jsonb_build_object('table',k.table_name,'key_columns_sorted',k.sorted_columns,
      'usable_index_count',(select count(*) from index_shapes i where i.table_name=k.table_name
        and i.indisunique and i.indisvalid and i.indisready and i.indislive and i.indimmediate
        and not i.indisexclusion and i.indpred is null and i.indexprs is null
        and i.indnkeyatts=cardinality(k.sorted_columns) and i.sorted_key_columns=k.sorted_columns),
      'deferrable_inference_index_count',(select count(*) from index_shapes i where i.table_name=k.table_name
        and i.indisunique and i.indisvalid and not i.indimmediate
        and i.indpred is null and i.indexprs is null
        and i.indnkeyatts=cardinality(k.sorted_columns) and i.sorted_key_columns=k.sorted_columns))
      order by k.table_name) from required_keys k
  ),
  'heartbeat_named_primary_key_matches',exists(
    select 1 from index_shapes i where i.table_name='automation_heartbeats'
      and i.constraint_name='automation_heartbeats_pkey' and i.constraint_type='p'
      and i.key_columns=array['heartbeat_key']::text[] and i.indnkeyatts=1
      and i.indisunique and i.indisprimary and i.indisvalid and i.indisready and i.indislive
      and i.indimmediate and not i.condeferrable and i.indpred is null and i.indexprs is null
  ),
  'index_shapes',(
    select jsonb_agg(jsonb_build_object('table',t.table_name,
      'count',(select count(*) from index_shapes i where i.table_name=t.table_name),
      'truncated',(select count(*)>16 from index_shapes i where i.table_name=t.table_name),
      'items',coalesce((select jsonb_agg(jsonb_build_object('index',i.index_name,
        'key_columns',i.key_columns,'key_attribute_count',i.indnkeyatts,'total_attribute_count',i.indnatts,
        'unique',i.indisunique,'primary',i.indisprimary,'valid',i.indisvalid,'ready',i.indisready,
        'live',i.indislive,'immediate',i.indimmediate,'exclusion',i.indisexclusion,
        'partial',i.indpred is not null,'expression',i.indexprs is not null,
        'constraint',i.constraint_name,'constraint_type',i.constraint_type,
        'constraint_deferrable',i.condeferrable,'constraint_initially_deferred',i.condeferred,
        'definition',case when octet_length(i.definition)<=16384 then i.definition end,
        'definition_withheld_oversized',octet_length(i.definition)>16384)
        order by i.index_name) from index_shapes i where i.table_name=t.table_name and i.ordinal<=16),'[]'::jsonb))
      order by t.table_name) from tables t
  ),
  'migration_ledger',jsonb_build_object(
    'matching_count',(select count(*) from ledger),'truncated',(select count(*)>16 from ledger),
    'repair_version_present',exists(select 1 from ledger where version='20261027164716'),
    'repair_name_present',exists(select 1 from ledger where name='automation_control_runtime_repair'),
    'items',coalesce((select jsonb_agg(jsonb_build_object('version',l.version,'name',l.name)
      order by l.version,l.name) from ledger l where l.ordinal<=16),'[]'::jsonb)
  )
) as automation_control_runtime_preflight;
