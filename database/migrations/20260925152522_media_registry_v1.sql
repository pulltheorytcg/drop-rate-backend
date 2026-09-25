-- Media Registry v1
-- Approved media is a deterministic Shopify publication input. Canonical media
-- belongs to a catalogue card; item-specific media belongs to one physical item.

create table tcg.media_assets (
    id uuid primary key default gen_random_uuid(),
    scope text not null check (scope in ('CATALOGUE','INVENTORY')),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    inventory_id uuid references tcg.inventory_items(id),
    owner_id uuid references tcg.owners(id),
    media_type text not null default 'IMAGE' check (media_type='IMAGE'),
    asset_role text not null check (asset_role in ('FRONT','BACK','OTHER')),
    asset_url text not null check (asset_url ~ '^https://'),
    source_kind text not null check (
        source_kind in ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD','LICENSED_PROVIDER','MIGRATED')
    ),
    source_provider text,
    source_reference text,
    rights_basis text not null check (
        rights_basis in (
            'OWNED_PHOTOGRAPH',
            'LICENSED_PROVIDER',
            'EXPLICIT_PERMISSION',
            'PUBLIC_DOMAIN'
        )
    ),
    rights_reference text not null check (nullif(btrim(rights_reference),'') is not null),
    rights_checked_at timestamptz not null default now(),
    rights_expires_at timestamptz,
    checksum_sha256 text check (
        checksum_sha256 is null or checksum_sha256 ~ '^[0-9a-fA-F]{64}$'
    ),
    alt_text text not null default '',
    approval_status text not null default 'DRAFT'
        check (approval_status in ('DRAFT','APPROVED','REJECTED')),
    approved_at timestamptz,
    approved_by_user_id uuid references auth.users(id),
    is_primary boolean not null default false,
    display_order integer not null default 0 check (display_order >= 0),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    version integer not null default 1 check (version >= 1),
    check (
        (scope='CATALOGUE' and inventory_id is null and owner_id is null)
        or
        (scope='INVENTORY' and inventory_id is not null and owner_id is not null)
    ),
    check (
        rights_basis <> 'LICENSED_PROVIDER'
        or nullif(btrim(source_provider),'') is not null
    ),
    check (
        (approval_status='APPROVED' and approved_at is not null and approved_by_user_id is not null)
        or
        (approval_status<>'APPROVED' and approved_at is null and approved_by_user_id is null)
    ),
    check (rights_expires_at is null or rights_expires_at > rights_checked_at)
);

create unique index media_assets_catalogue_url_role_uq
    on tcg.media_assets(catalogue_id,asset_url,asset_role)
    where scope='CATALOGUE';

create unique index media_assets_inventory_url_role_uq
    on tcg.media_assets(inventory_id,asset_url,asset_role)
    where scope='INVENTORY';

create unique index media_assets_catalogue_primary_role_uq
    on tcg.media_assets(catalogue_id,asset_role)
    where scope='CATALOGUE'
      and is_primary
      and approval_status='APPROVED';

create unique index media_assets_inventory_primary_role_uq
    on tcg.media_assets(inventory_id,asset_role)
    where scope='INVENTORY'
      and is_primary
      and approval_status='APPROVED';

create index media_assets_catalogue_readiness_idx
    on tcg.media_assets(catalogue_id,approval_status,asset_role,display_order);

create index media_assets_inventory_readiness_idx
    on tcg.media_assets(inventory_id,approval_status,asset_role,display_order);

create or replace function tcg.validate_media_asset_target()
returns trigger
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
    inventory_catalogue uuid;
    inventory_owner uuid;
begin
    if new.scope='INVENTORY' then
        select i.catalogue_id,i.owner_id
          into inventory_catalogue,inventory_owner
        from tcg.inventory_items i
        where i.id=new.inventory_id;

        if inventory_catalogue is null then
            raise exception 'Inventory media target does not exist'
                using errcode='23503';
        end if;
        if new.catalogue_id <> inventory_catalogue then
            raise exception 'Inventory media catalogue does not match physical inventory'
                using errcode='23514';
        end if;
        if new.owner_id <> inventory_owner then
            raise exception 'Inventory media owner does not match physical inventory'
                using errcode='23514';
        end if;
    end if;
    return new;
end;
$function$;

revoke all on function tcg.validate_media_asset_target() from public;
grant execute on function tcg.validate_media_asset_target() to tcg_api;

create or replace function tcg.audit_media_asset_change()
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

revoke all on function tcg.audit_media_asset_change() from public;

create or replace function tcg.protect_media_asset_provenance()
returns trigger
language plpgsql
set search_path=pg_catalog
as $function$
begin
    if new.scope is distinct from old.scope
       or new.catalogue_id is distinct from old.catalogue_id
       or new.inventory_id is distinct from old.inventory_id
       or new.owner_id is distinct from old.owner_id
       or new.media_type is distinct from old.media_type
       or new.asset_role is distinct from old.asset_role
       or new.asset_url is distinct from old.asset_url
       or new.source_kind is distinct from old.source_kind
       or new.source_provider is distinct from old.source_provider
       or new.source_reference is distinct from old.source_reference
       or new.rights_basis is distinct from old.rights_basis
       or new.rights_reference is distinct from old.rights_reference
       or new.rights_checked_at is distinct from old.rights_checked_at
       or new.rights_expires_at is distinct from old.rights_expires_at
       or new.checksum_sha256 is distinct from old.checksum_sha256
       or new.created_by_user_id is distinct from old.created_by_user_id
       or new.created_at is distinct from old.created_at then
        raise exception 'Media provenance is immutable; create a new media asset instead'
            using errcode='55000';
    end if;
    return new;
end;
$function$;

revoke all on function tcg.protect_media_asset_provenance() from public;
grant execute on function tcg.protect_media_asset_provenance() to tcg_api;

create trigger media_assets_validate_target
    before insert or update on tcg.media_assets
    for each row execute function tcg.validate_media_asset_target();

create trigger media_assets_protect_provenance
    before update on tcg.media_assets
    for each row execute function tcg.protect_media_asset_provenance();

create trigger media_assets_audit
    after insert or update or delete on tcg.media_assets
    for each row execute function tcg.audit_media_asset_change();

alter table tcg.media_assets enable row level security;
alter table tcg.media_assets force row level security;

revoke all on table tcg.media_assets from public, anon, authenticated;

create policy admin_access on tcg.media_assets
    for all to postgres using (true) with check (true);

create policy media_read on tcg.media_assets
    for select to tcg_api
    using (
        (
            scope='CATALOGUE'
            and exists (
                select 1
                from tcg.owner_memberships m
                where m.user_id=tcg.current_user_id()
                  and m.active
                  and m.role='FOUNDER'
            )
        )
        or
        (
            scope='INVENTORY'
            and owner_id in (select id from tcg.owners)
        )
    );

create policy media_insert on tcg.media_assets
    for insert to tcg_api
    with check (
        created_by_user_id=tcg.current_user_id()
        and (
            (
                scope='CATALOGUE'
                and exists (
                    select 1
                    from tcg.owner_memberships m
                    where m.user_id=tcg.current_user_id()
                      and m.active
                      and m.role='FOUNDER'
                )
            )
            or
            (
                scope='INVENTORY'
                and owner_id in (select id from tcg.owners)
            )
        )
    );

create policy media_update on tcg.media_assets
    for update to tcg_api
    using (
        (
            scope='CATALOGUE'
            and exists (
                select 1
                from tcg.owner_memberships m
                where m.user_id=tcg.current_user_id()
                  and m.active
                  and m.role='FOUNDER'
            )
        )
        or
        (
            scope='INVENTORY'
            and owner_id in (select id from tcg.owners)
        )
    )
    with check (
        (
            scope='CATALOGUE'
            and exists (
                select 1
                from tcg.owner_memberships m
                where m.user_id=tcg.current_user_id()
                  and m.active
                  and m.role='FOUNDER'
            )
        )
        or
        (
            scope='INVENTORY'
            and owner_id in (select id from tcg.owners)
        )
    );

grant select,insert,update on tcg.media_assets to tcg_api;
revoke delete on tcg.media_assets from tcg_api;
