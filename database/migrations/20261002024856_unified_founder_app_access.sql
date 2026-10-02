-- Explicit founder roster. Platform roles alone must not grant Founder HQ access.
create table tcg.founder_app_accounts (
  user_id uuid primary key references auth.users(id),
  owner_id uuid not null unique references tcg.owners(id),
  founder_slot smallint not null unique check (founder_slot between 1 and 3),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table tcg.founder_app_accounts enable row level security;
revoke all on tcg.founder_app_accounts from public, anon, authenticated, tcg_api;

-- Preserve already-authorized founder accounts; new founders require an audited
-- operator enrollment. No signup, invitation, JWT metadata or API can write here.
insert into tcg.founder_app_accounts(user_id,owner_id,founder_slot)
select m.user_id,o.id,o.founder_slot
from tcg.owner_memberships m
join tcg.owners o on o.id=m.owner_id
join auth.users u on u.id=m.user_id
where m.active and m.role='PLATFORM_ADMIN' and o.active
  and o.owner_type='FOUNDER' and o.founder_slot between 1 and 3
  and u.email_confirmed_at is not null;

create or replace function tcg.is_platform_admin()
returns boolean language sql stable security definer
set search_path=pg_catalog
as $function$
  select exists (
    select 1 from tcg.founder_app_accounts f
    join tcg.owner_memberships m on m.user_id=f.user_id and m.owner_id=f.owner_id
    join tcg.owners o on o.id=f.owner_id and o.founder_slot=f.founder_slot
    where f.user_id=tcg.current_user_id() and f.active and m.active
      and m.role='PLATFORM_ADMIN' and o.active and o.owner_type='FOUNDER'
      and (select count(*) from tcg.owner_memberships other
           where other.user_id=f.user_id and other.active)=1
  )
$function$;
revoke all on function tcg.is_platform_admin() from public,anon,authenticated;
grant execute on function tcg.is_platform_admin() to tcg_api;

create function tcg.audit_founder_app_account()
returns trigger language plpgsql security definer set search_path=pg_catalog
as $function$
begin
  insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,old_values,new_values)
  values(coalesce(nullif(current_setting('tcg.user_id',true),''),'system:founder-roster'),
    nullif(current_setting('tcg.request_id',true),''),'FOUNDER_APP_ACCESS_'||TG_OP,
    'OWNER',coalesce(NEW.owner_id,OLD.owner_id),
    case when TG_OP<>'INSERT' then to_jsonb(OLD) end,
    case when TG_OP<>'DELETE' then to_jsonb(NEW) end);
  return coalesce(NEW,OLD);
end
$function$;
revoke all on function tcg.audit_founder_app_account() from public,anon,authenticated,tcg_api;
create trigger audit_founder_app_account after insert or update or delete
on tcg.founder_app_accounts for each row execute function tcg.audit_founder_app_account();

insert into tcg.audit_events(actor,action,entity_type,entity_id,new_values)
select 'system:founder-roster-migration','FOUNDER_APP_ACCESS_BOOTSTRAPPED','OWNER',owner_id,
  jsonb_build_object('user_id',user_id,'founder_slot',founder_slot)
from tcg.founder_app_accounts;
