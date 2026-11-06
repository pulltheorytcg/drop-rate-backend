-- Drop Rate Content Machine foundation.
-- Canonical content/trend state belongs in Postgres; n8n only orchestrates external actions.

create table if not exists tcg.content_signals (
  signal_id uuid primary key default gen_random_uuid(),
  signal_type text not null check (signal_type in ('NEW_RELEASE','PRICE_MOVE','RARE_SALE','TREND','NEW_INVENTORY','GRAIL','LOW_STOCK','COMMUNITY_TOPIC')),
  game text,
  subject text not null,
  source_name text not null,
  source_url text,
  source_published_at timestamptz,
  detected_at timestamptz not null default now(),
  facts jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '[]'::jsonb,
  relevance_score numeric not null default 0 check (relevance_score between 0 and 1),
  confidence_score numeric not null default 0 check (confidence_score between 0 and 1),
  rights_status text not null default 'REFERENCE_ONLY' check (rights_status in ('REFERENCE_ONLY','LICENSED','OWNED','PUBLIC_DOMAIN')),
  dedupe_key text not null unique,
  status text not null default 'NEW' check (status in ('NEW','QUALIFIED','REJECTED','USED','EXPIRED')),
  created_at timestamptz not null default now()
);

create table if not exists tcg.content_jobs (
  content_job_id uuid primary key default gen_random_uuid(),
  signal_id uuid references tcg.content_signals(signal_id),
  content_type text not null check (content_type in ('SHORT_VIDEO','IMAGE_POST','CAROUSEL','STORY','LONG_VIDEO','TEXT_POST','BLOG')),
  objective text not null,
  factual_brief jsonb not null,
  creative_brief jsonb not null default '{}'::jsonb,
  ai_provider text,
  ai_model text,
  prompt_version text,
  generation_metadata jsonb not null default '{}'::jsonb,
  status text not null default 'QUEUED' check (status in ('QUEUED','GENERATING','REVIEW_REQUIRED','APPROVED','PUBLISHING','PUBLISHED','FAILED','REJECTED')),
  risk_level text not null default 'LOW' check (risk_level in ('LOW','MEDIUM','HIGH')),
  scheduled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tcg.content_variants (
  content_variant_id uuid primary key default gen_random_uuid(),
  content_job_id uuid not null references tcg.content_jobs(content_job_id) on delete cascade,
  platform text not null check (platform in ('INSTAGRAM','FACEBOOK','TIKTOK','YOUTUBE','X','SHOPIFY')),
  hook text,
  caption text,
  title text,
  cta text,
  hashtags jsonb not null default '[]'::jsonb,
  media_manifest jsonb not null default '[]'::jsonb,
  factual_claims jsonb not null default '[]'::jsonb,
  source_attribution jsonb not null default '[]'::jsonb,
  status text not null default 'DRAFT' check (status in ('DRAFT','VALIDATED','REJECTED','PUBLISHED')),
  created_at timestamptz not null default now(),
  unique(content_job_id, platform)
);

create table if not exists tcg.content_publications (
  publication_id uuid primary key default gen_random_uuid(),
  content_variant_id uuid not null references tcg.content_variants(content_variant_id),
  platform text not null,
  external_post_id text,
  idempotency_key text not null unique,
  published_at timestamptz,
  status text not null check (status in ('PENDING','PUBLISHED','FAILED','REMOVED')),
  error_code text,
  metrics jsonb not null default '{}'::jsonb,
  metrics_observed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists content_signals_queue_idx on tcg.content_signals(status, relevance_score desc, detected_at desc);
create index if not exists content_jobs_queue_idx on tcg.content_jobs(status, scheduled_at);
create index if not exists content_publications_metrics_idx on tcg.content_publications(status, metrics_observed_at);

alter table tcg.content_signals enable row level security;
alter table tcg.content_jobs enable row level security;
alter table tcg.content_variants enable row level security;
alter table tcg.content_publications enable row level security;
revoke all on tcg.content_signals from anon, authenticated;
revoke all on tcg.content_jobs from anon, authenticated;
revoke all on tcg.content_variants from anon, authenticated;
revoke all on tcg.content_publications from anon, authenticated;
