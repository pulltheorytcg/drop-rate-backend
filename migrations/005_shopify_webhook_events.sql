-- Shopify webhook delivery ledger.
-- Stores delivery metadata and a payload hash only; raw Shopify payloads are not persisted.

create table if not exists tcg.shopify_webhook_events (
  id uuid primary key default gen_random_uuid(),
  webhook_id text not null unique,
  event_id text,
  topic text not null,
  shop_domain text not null,
  api_version text,
  triggered_at timestamptz,
  resource_id text,
  payload_sha256 text not null check (char_length(payload_sha256) = 64),
  status text not null default 'RECEIVED'
    check (status in ('RECEIVED','PROCESSED','IGNORED','FAILED')),
  received_at timestamptz not null default clock_timestamp(),
  processed_at timestamptz,
  error_code text
);

create index if not exists shopify_webhook_events_event_idx
  on tcg.shopify_webhook_events(event_id)
  where event_id is not null;
create index if not exists shopify_webhook_events_topic_received_idx
  on tcg.shopify_webhook_events(topic, received_at desc);

alter table tcg.shopify_webhook_events enable row level security;
alter table tcg.shopify_webhook_events force row level security;

revoke all on table tcg.shopify_webhook_events from public;
revoke all on table tcg.shopify_webhook_events from anon, authenticated;
grant select, insert on table tcg.shopify_webhook_events to tcg_api;
grant update(status, processed_at, error_code)
  on table tcg.shopify_webhook_events to tcg_api;

drop policy if exists internal_shopify_webhook_read on tcg.shopify_webhook_events;
create policy internal_shopify_webhook_read
  on tcg.shopify_webhook_events for select to tcg_api using (true);

drop policy if exists internal_shopify_webhook_insert on tcg.shopify_webhook_events;
create policy internal_shopify_webhook_insert
  on tcg.shopify_webhook_events for insert to tcg_api with check (true);

drop policy if exists internal_shopify_webhook_update on tcg.shopify_webhook_events;
create policy internal_shopify_webhook_update
  on tcg.shopify_webhook_events for update to tcg_api
  using (true) with check (true);
