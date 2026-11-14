-- Twelve reviewed single-column foreign-key indexes, no data or FK changes.
-- Ordinary builds are intentionally bounded and transactional for these small
-- tables (largest observed heap 2.7 MB). An unexpected large table aborts rather
-- than silently holding writes; use a separately reviewed concurrent build then.
-- Same-name incompatible/invalid indexes are errors, not IF NOT EXISTS success.
begin;
set local lock_timeout = '2s';
set local statement_timeout = '30s';
set local idle_in_transaction_session_timeout = '10s';

do $indexes$
declare
    target record;
    table_oid oid;
    column_number smallint;
    existing_oid oid;
begin
    for target in select * from (values
        ('action_required_items','resolved_by_user_id','action_required_items_resolved_by_user_idx'),
        ('import_enrichment_items','inventory_id','import_enrichment_items_inventory_idx'),
        ('media_assets','approved_by_user_id','media_assets_approved_by_user_fk_idx'),
        ('media_assets','created_by_user_id','media_assets_created_by_user_fk_idx'),
        ('owner_invites','created_by_owner_id','owner_invites_created_by_owner_fk_idx'),
        ('owner_invites','redeemed_owner_id','owner_invites_redeemed_owner_fk_idx'),
        ('reference_asking_prices','snapshot_id','reference_asking_prices_snapshot_fk_idx'),
        ('reference_sealed_products','system_code','reference_sealed_products_system_code_fk_idx'),
        ('reference_sets','system_code','reference_sets_system_code_fk_idx'),
        ('shopify_postage_actual_costs','owner_id','shopify_postage_actual_costs_owner_fk_idx'),
        ('shopify_shipping_profiles','created_by_user_id','shopify_shipping_profiles_created_by_user_fk_idx'),
        ('shopify_variant_pool_aliases','owner_id','shopify_variant_pool_aliases_owner_fk_idx')
    ) as x(table_name,column_name,index_name)
    loop
        table_oid := to_regclass('tcg.'||target.table_name);
        if table_oid is null then
            raise exception 'Advisor index table missing: %',target.table_name;
        end if;
        -- This lock also prevents a competing index/table DDL change between
        -- the catalog checks and CREATE. Locks are held only until this commit.
        execute format('lock table tcg.%I in share row exclusive mode',target.table_name);
        if pg_relation_size(table_oid) > 67108864 then
            raise exception 'Advisor index requires separate large-table review: %',target.table_name;
        end if;
        select attnum into column_number from pg_attribute
          where attrelid=table_oid and attname=target.column_name and not attisdropped;
        if column_number is null or not exists (
            select 1 from pg_constraint where conrelid=table_oid and contype='f'
                and conkey=array[column_number]
        ) then
            raise exception 'Advisor expected single-column FK missing: %.%',target.table_name,target.column_name;
        end if;
        existing_oid := to_regclass('tcg.'||target.index_name);
        if existing_oid is not null then
            if not exists (
                select 1 from pg_index i join pg_class c on c.oid=i.indexrelid
                  join pg_am am on am.oid=c.relam
                where i.indexrelid=existing_oid and i.indrelid=table_oid
                  and i.indisvalid and i.indisready and i.indislive
                  and not i.indisunique and i.indnkeyatts=1 and i.indnatts=1
                  and i.indkey[0]=column_number and i.indpred is null
                  and i.indexprs is null and am.amname='btree'
                  and i.indcollation[0]=(select attcollation from pg_attribute where attrelid=table_oid and attnum=column_number)
                  and exists (select 1 from pg_opclass op where op.oid=i.indclass[0] and op.opcdefault)
            ) then
                raise exception 'Advisor index name conflicts with different/invalid definition: %',target.index_name;
            end if;
        elsif not exists (
            -- An existing complete leading-column B-tree already serves the FK.
            -- Do not create duplicate storage merely to match the proposed name.
            select 1 from pg_index i join pg_class c on c.oid=i.indexrelid
              join pg_am am on am.oid=c.relam
            where i.indrelid=table_oid and i.indisvalid and i.indisready and i.indislive
              and i.indkey[0]=column_number and i.indpred is null
              and i.indexprs is null and am.amname='btree'
                  and i.indcollation[0]=(select attcollation from pg_attribute where attrelid=table_oid and attnum=column_number)
                  and exists (select 1 from pg_opclass op where op.oid=i.indclass[0] and op.opcdefault)
        ) then
            execute format('create index %I on tcg.%I (%I)',
                target.index_name,target.table_name,target.column_name);
        end if;
    end loop;
end;
$indexes$;
commit;
