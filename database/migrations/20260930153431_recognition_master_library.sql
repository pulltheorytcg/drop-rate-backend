begin;

insert into tcg.collectible_systems(code,display_name,franchise,system_kind,publisher,lifecycle_status,official_url)
values
 ('YUGIOH','Yu-Gi-Oh! Trading Card Game','Yu-Gi-Oh!','TCG','Konami','ACTIVE','https://www.yugioh-card.com/'),
 ('NARUTO_KAYOU','Naruto Kayou','Naruto','TCG','Kayou','ACTIVE',null),
 ('NARUTO_BANDAI_LEGACY','Naruto Collectible Card Game (legacy)','Naruto','TCG','Bandai','INACTIVE',null)
on conflict (code) do nothing;

-- Provider reference facts are deliberately separate from owned inventory and
-- verified canonical printings. A feed import cannot approve cards or media.
create table tcg.reference_sets (
 provider text not null,
 system_code text not null references tcg.collectible_systems(code),
 language text not null,
 set_id text not null,
 name text not null,
 release_date date,
 declared_card_count integer check (declared_card_count >= 0),
 source_url text not null check (source_url like 'https://%'),
 refreshed_at timestamptz not null default now(),
 primary key(provider,system_code,language,set_id)
);

create table tcg.reference_cards (
 provider text not null,
 system_code text not null references tcg.collectible_systems(code),
 language text not null,
 provider_id text not null,
 set_id text not null,
 name text not null,
 card_number text not null,
 number_key text not null,
 finish text,
 rarity text,
 image_url text,
 source_url text not null check (source_url like 'https://%'),
 evidence jsonb not null default '{}'::jsonb,
 refreshed_at timestamptz not null default now(),
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,set_id)
   references tcg.reference_sets(provider,system_code,language,set_id)
);
create index reference_cards_number_idx on tcg.reference_cards(system_code,language,number_key);
create index reference_cards_set_idx on tcg.reference_cards(provider,system_code,language,set_id);
create index reference_cards_name_idx on tcg.reference_cards(system_code,language,lower(name));
create index reference_cards_local_number_idx on tcg.reference_cards(system_code,language,(split_part(number_key,':/:',1)));

create table tcg.reference_sync_runs (
 id uuid primary key default gen_random_uuid(),
 source text not null,
 started_at timestamptz not null default now(),
 finished_at timestamptz,
 status text not null check(status in ('RUNNING','COMPLETE','INCOMPLETE','FAILED')),
 sets_loaded integer not null default 0 check(sets_loaded>=0),
 cards_loaded integer not null default 0 check(cards_loaded>=0),
 report jsonb not null default '{}'::jsonb
);
alter table tcg.reference_sync_runs enable row level security;
alter table tcg.reference_sync_runs force row level security;
create policy reference_sync_runs_admin on tcg.reference_sync_runs for all to postgres using(true) with check(true);
create policy reference_sync_runs_read on tcg.reference_sync_runs for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_sync_runs_insert on tcg.reference_sync_runs for insert to tcg_api with check((select tcg.is_platform_admin()));
create policy reference_sync_runs_update on tcg.reference_sync_runs for update to tcg_api using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
revoke all on tcg.reference_sync_runs from public,anon,authenticated;
grant select,insert,update on tcg.reference_sync_runs to tcg_api;

alter table tcg.reference_sets enable row level security;
alter table tcg.reference_sets force row level security;
alter table tcg.reference_cards enable row level security;
alter table tcg.reference_cards force row level security;
create policy reference_sets_admin on tcg.reference_sets for all to postgres using(true) with check(true);
create policy reference_cards_admin on tcg.reference_cards for all to postgres using(true) with check(true);
create policy reference_sets_read on tcg.reference_sets for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_cards_read on tcg.reference_cards for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_sets_insert on tcg.reference_sets for insert to tcg_api with check((select tcg.is_platform_admin()));
create policy reference_cards_insert on tcg.reference_cards for insert to tcg_api with check((select tcg.is_platform_admin()));
create policy reference_sets_update on tcg.reference_sets for update to tcg_api using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
create policy reference_cards_update on tcg.reference_cards for update to tcg_api using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
revoke all on tcg.reference_sets,tcg.reference_cards from public,anon,authenticated;
grant select,insert,update on tcg.reference_sets,tcg.reference_cards to tcg_api;
revoke delete on tcg.reference_sets,tcg.reference_cards from tcg_api;

commit;

