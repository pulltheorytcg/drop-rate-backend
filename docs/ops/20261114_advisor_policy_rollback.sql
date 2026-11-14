-- Manual, reviewed rollback only. Never part of forward migration staging.
-- Restores all four exact original policies; leaves additive indexes in place.
begin;
set local lock_timeout = '2s';
set local statement_timeout = '30s';
set local idle_in_transaction_session_timeout = '10s';

-- Serialize the guard and ALTERs against concurrent table/policy DDL. No row writes.
lock table tcg.action_required_items, tcg.import_enrichment_items, tcg.media_assets
    in share row exclusive mode;

do $guard$
declare
    target record;
    actual record;
    old_owner text := $old$(owner_id IN ( SELECT om.owner_id FROM tcg.owner_memberships om WHERE ((om.user_id = (NULLIF(current_setting('tcg.user_id'::text, true), ''::text))::uuid) AND om.active)))$old$;
    new_owner text := $new$(owner_id IN ( SELECT om.owner_id FROM tcg.owner_memberships om WHERE ((om.user_id = ( SELECT (NULLIF(current_setting('tcg.user_id'::text, true), ''::text))::uuid AS "nullif")) AND om.active)))$new$;
    old_qual text;
    new_qual text;
begin
    if not exists (select 1 from pg_roles where rolname='tcg_api'
                   and not rolsuper and not rolbypassrls) then
        raise exception 'Advisor migration requires non-bypass tcg_api role';
    end if;
    for target in select * from (values
        ('action_required_items','own_action_required_access','*'),
        ('import_enrichment_items','own_enrichment_access','*'),
        ('media_assets','own_asset_writes','*'),
        ('media_assets','readable_assets','r')
    ) as x(table_name,policy_name,command)
    loop
        select p.*, c.relrowsecurity, c.relforcerowsecurity,
               regexp_replace(pg_get_expr(p.polqual,p.polrelid),'[[:space:]]','','g') as qual,
               regexp_replace(pg_get_expr(p.polwithcheck,p.polrelid),'[[:space:]]','','g') as check_expr
          into actual from pg_policy p join pg_class c on c.oid=p.polrelid
          where p.polrelid=to_regclass('tcg.'||target.table_name)
            and p.polname=target.policy_name;
        if not found then
            raise exception 'Advisor policy missing: %.%',target.table_name,target.policy_name;
        end if;
        old_qual := old_owner;
        new_qual := new_owner;
        if target.command='r' then
            old_qual := '((scope = ''CANONICAL_CARD''::text) OR '||old_owner||')';
            new_qual := '((scope = ''CANONICAL_CARD''::text) OR '||new_owner||')';
        end if;
        old_qual := regexp_replace(old_qual,'[[:space:]]','','g');
        new_qual := regexp_replace(new_qual,'[[:space:]]','','g');
        if actual.polcmd::text <> target.command or not actual.polpermissive
           or actual.polroles <> array['tcg_api'::regrole::oid]
           or not actual.relrowsecurity or not actual.relforcerowsecurity
           or not (
               (actual.qual is not distinct from old_qual and actual.check_expr is not distinct from
                    case when target.command='r' then null else old_qual end)
               or
               (actual.qual is not distinct from new_qual and actual.check_expr is not distinct from
                    case when target.command='r' then null else new_qual end)
           ) then
            raise exception 'Unexpected advisor policy drift: %.%',target.table_name,target.policy_name;
        end if;
    end loop;
end;
$guard$;

ALTER POLICY own_action_required_access ON tcg.action_required_items
  USING (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  )
  WITH CHECK (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  );

ALTER POLICY own_enrichment_access ON tcg.import_enrichment_items
  USING (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  )
  WITH CHECK (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  );

ALTER POLICY own_asset_writes ON tcg.media_assets
  USING (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  )
  WITH CHECK (
    owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  );

ALTER POLICY readable_assets ON tcg.media_assets
  USING (
    scope = 'CANONICAL_CARD'
    OR owner_id IN (
      SELECT om.owner_id
      FROM tcg.owner_memberships om
      WHERE om.user_id = NULLIF(current_setting('tcg.user_id', true), '')::uuid
        AND om.active
    )
  );

commit;
