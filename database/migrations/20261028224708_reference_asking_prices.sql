-- Additive proposal: assign the migration version using the deployment tool.
-- Asking estimates are separate from sold evidence and physical inventory.
begin;

create table tcg.reference_asking_runs (
 id uuid primary key default gen_random_uuid(),
 actor_user_id uuid not null,
 started_at timestamptz not null default clock_timestamp(),
 budget_day date not null default (clock_timestamp() at time zone 'UTC')::date,
 finished_at timestamptz,
 status text not null default 'RUNNING'
   check(status in ('RUNNING','COMPLETE','INCOMPLETE','FAILED','STOPPED')),
 requests integer not null default 0 check(requests between 0 and 500),
 report jsonb not null default '{}'::jsonb
   check(jsonb_typeof(report)='object' and octet_length(report::text)<=16384),
 check(budget_day=(started_at at time zone 'UTC')::date),
 check((status='RUNNING')=(finished_at is null)),
 check(finished_at is null or finished_at>=started_at)
);
create index reference_asking_runs_budget on tcg.reference_asking_runs(budget_day);

-- Reserve and COMMIT one counter increment before every external request,
-- including requests which fail. Never hold this transaction over network I/O.
create function tcg.guard_reference_asking_run() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
declare used integer;
begin
 if not coalesce(tcg.is_platform_admin(),false)
    or new.actor_user_id is distinct from tcg.current_user_id() then
   raise exception 'ASKING_RUN_ADMIN_REQUIRED' using errcode='42501';
 end if;
 if TG_OP='INSERT' then
   if new.requests<>0 or new.status<>'RUNNING' then
     raise exception 'ASKING_RUN_MUST_START_EMPTY';
   end if;
   return new;
 end if;
 if (new.id,new.actor_user_id,new.started_at,new.budget_day)
      is distinct from (old.id,old.actor_user_id,old.started_at,old.budget_day)
    or old.status<>'RUNNING' then
   raise exception 'ASKING_RUN_IDENTITY_OR_FINAL_STATE_IMMUTABLE';
 end if;
 if new.requests not in (old.requests,old.requests+1) then
   raise exception 'ASKING_REQUEST_COUNTER_MUST_INCREMENT_BY_ONE';
 end if;
 if new.requests=old.requests+1 then
   if new.status<>'RUNNING'
      or new.budget_day<>(clock_timestamp() at time zone 'UTC')::date then
     raise exception 'ASKING_REQUEST_RUN_NOT_CURRENT';
   end if;
   perform pg_advisory_xact_lock(hashtextextended('tcg.reference_asking_daily_budget',0));
   select coalesce(sum(requests),0)::integer into used
     from tcg.reference_asking_runs where budget_day=new.budget_day;
   if used>=500 then
     raise exception 'ASKING_DAILY_REQUEST_BUDGET_EXHAUSTED';
   end if;
 end if;
 return new;
end;$$;
revoke all on function tcg.guard_reference_asking_run() from public,anon,authenticated,tcg_api;
create trigger reference_asking_run_guard before insert or update on tcg.reference_asking_runs
 for each row execute function tcg.guard_reference_asking_run();

create function tcg.reserve_reference_asking_request(p_run_id uuid) returns integer
language plpgsql security invoker set search_path=pg_catalog as $$
declare reserved integer;
begin
 perform pg_advisory_xact_lock(hashtextextended('tcg.reference_asking_daily_budget',0));
 update tcg.reference_asking_runs set requests=requests+1
 where id=p_run_id and status='RUNNING' and actor_user_id=tcg.current_user_id()
 returning requests into reserved;
 if reserved is null then
   raise exception 'ASKING_RUN_NOT_AVAILABLE' using errcode='42501';
 end if;
 return reserved;
end;$$;
revoke all on function tcg.reserve_reference_asking_request(uuid) from public,anon,authenticated;
grant execute on function tcg.reserve_reference_asking_request(uuid) to tcg_api;

create table tcg.reference_asking_history (
 snapshot_id uuid primary key default gen_random_uuid(),
 run_id uuid not null references tcg.reference_asking_runs(id),
 actor_user_id uuid not null,
 provider text not null,
 system_code text not null,
 language text not null,
 provider_id text not null,
 reference_identity jsonb not null,
 estimate_minor bigint not null check(estimate_minor>0),
 estimate_high_minor bigint not null check(estimate_high_minor>=estimate_minor),
 currency text not null default 'GBP' check(currency='GBP'),
 listing_count integer not null check(listing_count>=3),
 seller_count integer not null check(seller_count>=3 and seller_count<=listing_count),
 observed_at timestamptz not null,
 checked_at timestamptz not null,
 expires_at timestamptz not null,
 method_version text not null check(method_version='EBAY_UK_RAW_ASK_V1'),
 evidence jsonb not null,
 recorded_at timestamptz not null default clock_timestamp(),
 recorded_txid bigint not null default txid_current(),
 foreign key(provider,system_code,language,provider_id)
   references tcg.reference_cards(provider,system_code,language,provider_id),
 check(checked_at>=observed_at and expires_at>checked_at
       and expires_at<=observed_at+interval '3 days'),
 constraint reference_asking_history_identity_shape check((
   jsonb_typeof(reference_identity)='object'
   and reference_identity ?& array['name','set_id','card_number','set_name','finish','rarity']
   and reference_identity-array['name','set_id','card_number','set_name','finish','rarity']='{}'::jsonb
   and octet_length(reference_identity::text)<=4096
 ) is true),
 constraint reference_asking_history_evidence_shape check((
   jsonb_typeof(evidence)='object' and octet_length(evidence::text)<=32768
   and evidence->>'source'='EBAY_OFFICIAL_BROWSE'
   and evidence->>'shipping_basis'='ITEM_PLUS_SHIPPING'
   and evidence->>'shipping_context'='CONFIGURED_SHOP_POSTCODE_BENCHMARK'
   and evidence->>'condition'='Near Mint'
   and evidence->>'finish' in ('Normal','Holo','Reverse Holo','Foil','Parallel','Alt Art','Manga')
   and jsonb_typeof(evidence->'confidence')='string'
   and length(btrim(evidence->>'confidence')) between 1 and 32
   and evidence->'physical_valuation_eligible'='false'::jsonb
 ) is true)
);
create index reference_asking_history_timeline on tcg.reference_asking_history
 (provider,system_code,language,provider_id,observed_at desc);
create index reference_asking_history_run on tcg.reference_asking_history(run_id);

create function tcg.guard_reference_asking_history() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
begin
 if TG_OP<>'INSERT' then
   raise exception 'ASKING_HISTORY_IS_APPEND_ONLY' using errcode='42501';
 end if;
 if not coalesce(tcg.is_platform_admin(),false)
    or new.actor_user_id is distinct from tcg.current_user_id()
    or not exists(select 1 from tcg.reference_asking_runs r where r.id=new.run_id
        and r.actor_user_id=new.actor_user_id and r.status='RUNNING' and r.requests>0) then
   raise exception 'ASKING_HISTORY_ACTIVE_ADMIN_RUN_REQUIRED' using errcode='42501';
 end if;
 if not exists(
   select 1 from tcg.reference_cards r join tcg.reference_sets s
     using(provider,system_code,language,set_id)
   where (r.provider,r.system_code,r.language,r.provider_id)=
         (new.provider,new.system_code,new.language,new.provider_id)
     and new.reference_identity=jsonb_build_object('name',r.name,'set_id',r.set_id,
          'card_number',r.card_number,'set_name',s.name,'finish',r.finish,'rarity',r.rarity)
 ) then
   raise exception 'ASKING_REFERENCE_IDENTITY_CHANGED';
 end if;
 if new.observed_at>clock_timestamp() then
   raise exception 'ASKING_OBSERVATION_IS_IN_FUTURE';
 end if;
 new.recorded_at:=clock_timestamp();
 new.recorded_txid:=txid_current();
 return new;
end;$$;
revoke all on function tcg.guard_reference_asking_history() from public,anon,authenticated,tcg_api;
create trigger reference_asking_history_guard before insert or update or delete
 on tcg.reference_asking_history for each row execute function tcg.guard_reference_asking_history();

create table tcg.reference_asking_prices (
 provider text not null,
 system_code text not null,
 language text not null,
 provider_id text not null,
 snapshot_id uuid not null references tcg.reference_asking_history(snapshot_id),
 reference_identity jsonb not null,
 estimate_minor bigint not null check(estimate_minor>0),
 estimate_high_minor bigint not null check(estimate_high_minor>=estimate_minor),
 currency text not null default 'GBP' check(currency='GBP'),
 listing_count integer not null check(listing_count>=3),
 seller_count integer not null check(seller_count>=3 and seller_count<=listing_count),
 observed_at timestamptz not null,
 checked_at timestamptz not null,
 expires_at timestamptz not null,
 method_version text not null check(method_version='EBAY_UK_RAW_ASK_V1'),
 evidence jsonb not null,
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
   references tcg.reference_cards(provider,system_code,language,provider_id),
 check(checked_at>=observed_at and expires_at>checked_at
       and expires_at<=observed_at+interval '3 days')
);
create index reference_asking_prices_expiry on tcg.reference_asking_prices(expires_at);

-- History must be inserted FIRST in the SAME transaction. Every cache field
-- must equal that immutable snapshot; a cache-only price change cannot pass.
create function tcg.guard_reference_asking_price() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
declare prior tcg.reference_asking_history%rowtype;
begin
 if not coalesce(tcg.is_platform_admin(),false) then
   raise exception 'ASKING_PRICE_ADMIN_REQUIRED' using errcode='42501';
 end if;
 select * into prior from tcg.reference_asking_history where snapshot_id=new.snapshot_id;
 if not found or prior.recorded_txid<>txid_current()
    or prior.actor_user_id is distinct from tcg.current_user_id()
    or to_jsonb(new) is distinct from
       (to_jsonb(prior)-array['run_id','actor_user_id','recorded_at','recorded_txid']) then
   raise exception 'ASKING_PRICE_REQUIRES_MATCHING_TRANSACTION_HISTORY';
 end if;
 if TG_OP='UPDATE' and (
     (new.provider,new.system_code,new.language,new.provider_id) is distinct from
       (old.provider,old.system_code,old.language,old.provider_id)
     or new.observed_at<old.observed_at or new.checked_at<old.checked_at) then
   raise exception 'ASKING_PRICE_IDENTITY_OR_FRESHNESS_REGRESSION';
 end if;
 return new;
end;$$;
revoke all on function tcg.guard_reference_asking_price() from public,anon,authenticated,tcg_api;
create trigger reference_asking_price_guard before insert or update on tcg.reference_asking_prices
 for each row execute function tcg.guard_reference_asking_price();

-- The private audit table deliberately denies direct INSERT to tcg_api.
-- This narrow trigger is the only elevated operation; actor/admin checks are
-- explicit, search_path is fixed, and no role can call the trigger directly.
create function tcg.audit_reference_asking_price() returns trigger
language plpgsql security definer set search_path=pg_catalog as $$
begin
 if tcg.current_user_id() is null or not coalesce(tcg.is_platform_admin(),false) then
   raise exception 'ASKING_PRICE_AUDIT_ADMIN_REQUIRED' using errcode='42501';
 end if;
 insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,old_values,new_values)
 values(tcg.current_user_id()::text,current_setting('tcg.request_id',true),
   'REFERENCE_ASKING_PRICE_CACHED','reference_asking_prices',new.snapshot_id,
   case when TG_OP='UPDATE' then jsonb_build_object('snapshot_id',old.snapshot_id,
       'estimate_minor',old.estimate_minor,'estimate_high_minor',old.estimate_high_minor,
       'observed_at',old.observed_at) else null end,
   jsonb_build_object('snapshot_id',new.snapshot_id,'provider',new.provider,
       'system_code',new.system_code,'language',new.language,'provider_id',new.provider_id,
       'estimate_minor',new.estimate_minor,'estimate_high_minor',new.estimate_high_minor,
       'observed_at',new.observed_at,'method_version',new.method_version));
 return new;
end;$$;
revoke all on function tcg.audit_reference_asking_price() from public,anon,authenticated,tcg_api;
create trigger reference_asking_price_audit after insert or update on tcg.reference_asking_prices
 for each row execute function tcg.audit_reference_asking_price();

alter table tcg.reference_asking_runs enable row level security;
alter table tcg.reference_asking_runs force row level security;
alter table tcg.reference_asking_history enable row level security;
alter table tcg.reference_asking_history force row level security;
alter table tcg.reference_asking_prices enable row level security;
alter table tcg.reference_asking_prices force row level security;

create policy reference_asking_runs_postgres on tcg.reference_asking_runs
 for all to postgres using(true) with check(true);
create policy reference_asking_history_postgres on tcg.reference_asking_history
 for all to postgres using(true) with check(true);
create policy reference_asking_prices_postgres on tcg.reference_asking_prices
 for all to postgres using(true) with check(true);

create policy reference_asking_runs_read on tcg.reference_asking_runs
 for select to tcg_api using((select tcg.is_platform_admin()));
create policy reference_asking_runs_insert on tcg.reference_asking_runs
 for insert to tcg_api with check((select tcg.is_platform_admin())
   and actor_user_id=(select tcg.current_user_id()));
create policy reference_asking_runs_update on tcg.reference_asking_runs
 for update to tcg_api using((select tcg.is_platform_admin())
   and actor_user_id=(select tcg.current_user_id()))
 with check((select tcg.is_platform_admin()) and actor_user_id=(select tcg.current_user_id()));
create policy reference_asking_history_read on tcg.reference_asking_history
 for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_asking_history_insert on tcg.reference_asking_history
 for insert to tcg_api with check((select tcg.is_platform_admin())
   and actor_user_id=(select tcg.current_user_id()));
create policy reference_asking_prices_read on tcg.reference_asking_prices
 for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_asking_prices_insert on tcg.reference_asking_prices
 for insert to tcg_api with check((select tcg.is_platform_admin()));
create policy reference_asking_prices_update on tcg.reference_asking_prices
 for update to tcg_api using((select tcg.is_platform_admin()))
 with check((select tcg.is_platform_admin()));

revoke all on tcg.reference_asking_runs,tcg.reference_asking_history,tcg.reference_asking_prices
 from public,anon,authenticated,service_role,tcg_api;
grant select,insert,update on tcg.reference_asking_runs,tcg.reference_asking_prices to tcg_api;
grant select,insert on tcg.reference_asking_history to tcg_api;

comment on table tcg.reference_asking_prices is
 'Explicitly labelled raw near-mint GBP asking estimates; never sold values, inventory prices, Store Prices or settlement authority.';
comment on table tcg.reference_asking_history is
 'Append-only asking evidence and attribution. Cache changes require identical history in the same transaction.';
comment on table tcg.reference_asking_runs is
 'Durable UTC-day request reservations, including failed attempts; global hard cap 500. Commit each reservation before HTTP.';
commit;
