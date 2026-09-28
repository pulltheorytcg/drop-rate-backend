begin;

alter table tcg.identity_verification_events
    drop constraint if exists identity_verification_events_verification_method_check;
alter table tcg.identity_verification_events
    add constraint identity_verification_events_verification_method_check
    check (
        verification_method in (
            'PHYSICAL_REVIEW',
            'IMPORT_EXACT',
            'IMPORT_DEFAULT_LANGUAGE',
            'PROVIDER_EXACT',
            'CORRECTION',
            'SYSTEM_INVALIDATION'
        )
    );

create table tcg.import_enrichment_items (
    id uuid primary key default gen_random_uuid(),
    batch_id uuid not null references tcg.import_batches(id),
    owner_id uuid not null references tcg.owners(id),
    inventory_id uuid not null references tcg.inventory_items(id),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    identity_status text not null default 'PENDING'
        check (identity_status in ('PENDING','CONFIRMED','ACTION_REQUIRED')),
    media_status text not null default 'PENDING'
        check (media_status in (
            'PENDING',
            'REFERENCE_READY',
            'PENDING_REVIEW',
            'PHYSICAL_REQUIRED',
            'ACTION_REQUIRED'
        )),
    pricing_status text not null default 'PENDING'
        check (pricing_status in ('PENDING','READY','PROVISIONAL','ACTION_REQUIRED')),
    overall_status text not null default 'PENDING'
        check (overall_status in ('PENDING','COMPLETE','ACTION_REQUIRED')),
    attempts integer not null default 0 check (attempts >= 0),
    last_error text,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata)='object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    version integer not null default 1 check (version >= 1),
    unique(batch_id,inventory_id)
);

create index import_enrichment_items_batch_status_idx
    on tcg.import_enrichment_items(batch_id,overall_status,updated_at,id);
create index import_enrichment_items_owner_status_idx
    on tcg.import_enrichment_items(owner_id,overall_status,updated_at desc);
create index import_enrichment_items_catalogue_idx
    on tcg.import_enrichment_items(catalogue_id,media_status);

alter table tcg.import_enrichment_items enable row level security;
alter table tcg.import_enrichment_items force row level security;
revoke all on table tcg.import_enrichment_items from anon,authenticated;

create policy admin_access on tcg.import_enrichment_items
    for all to postgres using (true) with check (true);

create policy own_enrichment_access on tcg.import_enrichment_items
    for all to tcg_api
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    );

grant select,insert,update on tcg.import_enrichment_items to tcg_api;
revoke delete on tcg.import_enrichment_items from tcg_api;


create table tcg.action_required_items (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    category text not null check (
        category in (
            'IDENTITY',
            'MEDIA',
            'PRICING',
            'IMPORT',
            'SHOPIFY',
            'CHANNEL',
            'SETTLEMENT',
            'OWNERSHIP',
            'DUPLICATE',
            'CUSTOMER_DISPUTE'
        )
    ),
    code text not null check (nullif(btrim(code),'') is not null),
    severity text not null default 'MEDIUM'
        check (severity in ('LOW','MEDIUM','HIGH','CRITICAL')),
    entity_type text not null check (
        entity_type in (
            'IMPORT_BATCH',
            'INVENTORY_ITEM',
            'CATALOGUE_CARD',
            'ORDER',
            'SETTLEMENT',
            'OWNER'
        )
    ),
    entity_id uuid not null,
    dedupe_key text not null check (nullif(btrim(dedupe_key),'') is not null),
    title text not null check (nullif(btrim(title),'') is not null),
    detail text not null default '',
    recommended_action text not null default '',
    status text not null default 'OPEN'
        check (status in ('OPEN','RESOLVED','DISMISSED')),
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata)='object'),
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    resolved_at timestamptz,
    resolved_by_user_id uuid references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    version integer not null default 1 check (version >= 1),
    unique(owner_id,dedupe_key),
    check (
        (status='OPEN' and resolved_at is null and resolved_by_user_id is null)
        or
        (status in ('RESOLVED','DISMISSED') and resolved_at is not null)
    )
);

create index action_required_items_owner_status_idx
    on tcg.action_required_items(owner_id,status,severity,last_seen_at desc);
create index action_required_items_entity_idx
    on tcg.action_required_items(entity_type,entity_id,status);
create index action_required_items_code_idx
    on tcg.action_required_items(owner_id,code,status);

alter table tcg.action_required_items enable row level security;
alter table tcg.action_required_items force row level security;
revoke all on table tcg.action_required_items from anon,authenticated;

create policy admin_access on tcg.action_required_items
    for all to postgres using (true) with check (true);

create policy own_action_required_access on tcg.action_required_items
    for all to tcg_api
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    );

grant select,insert,update on tcg.action_required_items to tcg_api;
revoke delete on tcg.action_required_items from tcg_api;


create or replace function tcg.audit_import_enrichment_change()
returns trigger
language plpgsql
security definer
set search_path=pg_catalog
as $function$
begin
    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
        nullif(current_setting('tcg.request_id',true),''),
        tg_op,
        tg_table_name,
        case when tg_op='DELETE' then old.id else new.id end,
        case when tg_op='INSERT' then null else to_jsonb(old) end,
        case when tg_op='DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$function$;

revoke all on function tcg.audit_import_enrichment_change() from public;

create trigger import_enrichment_items_audit
    after insert or update or delete on tcg.import_enrichment_items
    for each row execute function tcg.audit_import_enrichment_change();

create trigger action_required_items_audit
    after insert or update or delete on tcg.action_required_items
    for each row execute function tcg.audit_import_enrichment_change();

commit;
