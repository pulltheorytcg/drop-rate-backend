-- Governed CRO/SEO experiment registry.
-- Postgres owns experiment truth; FastAPI owns policy/statistical decisions.

create table if not exists public.experiments (
  id uuid primary key default gen_random_uuid(),
  experiment_type text not null check (experiment_type in ('CRO','SEO','MERCHANDISING','CONTENT')),
  hypothesis text not null,
  target_surface text not null,
  target_population jsonb not null default '{}'::jsonb,
  primary_metric text not null,
  guardrail_metrics jsonb not null default '[]'::jsonb,
  traffic_allocation jsonb not null default '{}'::jsonb,
  minimum_sample_size integer not null check (minimum_sample_size >= 1),
  minimum_observation_hours integer not null check (minimum_observation_hours >= 1),
  minimum_practical_effect numeric not null default 0 check (minimum_practical_effect >= 0),
  decision_threshold numeric not null default 0.95 check (decision_threshold > 0 and decision_threshold < 1),
  statistical_method text not null default 'two_proportion_z_test_v1',
  status text not null default 'DRAFT' check (status in ('DRAFT','PREFLIGHT_FAILED','READY','RUNNING','PAUSED','STOPPED','INCONCLUSIVE','WON','ROLLED_OUT','ROLLED_BACK')),
  authority_level smallint not null default 1 check (authority_level between 0 and 3),
  approval_status text not null default 'PENDING' check (approval_status in ('PENDING','APPROVED','REJECTED')),
  ai_provenance jsonb not null default '{}'::jsonb,
  winning_variant_id uuid,
  decision_evidence jsonb not null default '{}'::jsonb,
  rollback_snapshot jsonb not null default '{}'::jsonb,
  started_at timestamptz,
  ended_at timestamptz,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.experiment_variants (
  id uuid primary key default gen_random_uuid(),
  experiment_id uuid not null references public.experiments(id) on delete cascade,
  key text not null,
  is_control boolean not null default false,
  definition jsonb not null,
  allocation numeric not null check (allocation >= 0 and allocation <= 1),
  rollback_definition jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (experiment_id, key)
);

alter table public.experiments
  add constraint experiments_winning_variant_fk
  foreign key (winning_variant_id) references public.experiment_variants(id);

create unique index if not exists experiment_one_control
  on public.experiment_variants(experiment_id) where is_control;

create table if not exists public.experiment_observations (
  id bigint generated always as identity primary key,
  experiment_id uuid not null references public.experiments(id) on delete cascade,
  variant_id uuid not null references public.experiment_variants(id) on delete cascade,
  observed_at timestamptz not null,
  eligible_sessions bigint not null default 0 check (eligible_sessions >= 0),
  conversions bigint not null default 0 check (conversions >= 0),
  revenue_pence bigint not null default 0,
  metrics jsonb not null default '{}'::jsonb,
  source text not null,
  source_event_id text,
  created_at timestamptz not null default now(),
  unique (source, source_event_id)
);

create table if not exists public.experiment_decisions (
  id bigint generated always as identity primary key,
  experiment_id uuid not null references public.experiments(id) on delete cascade,
  decision text not null check (decision in ('CONTINUE','PAUSE','STOP_GUARDRAIL','INCONCLUSIVE','WINNER','ROLLBACK')),
  winning_variant_id uuid references public.experiment_variants(id),
  method text not null,
  method_version text not null,
  evidence jsonb not null,
  actor_type text not null check (actor_type in ('SYSTEM','HUMAN')),
  actor_id uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists experiments_status_surface_idx on public.experiments(status, target_surface);
create index if not exists experiment_observations_lookup_idx on public.experiment_observations(experiment_id, variant_id, observed_at desc);
create index if not exists experiment_decisions_lookup_idx on public.experiment_decisions(experiment_id, created_at desc);

alter table public.experiments enable row level security;
alter table public.experiment_variants enable row level security;
alter table public.experiment_observations enable row level security;
alter table public.experiment_decisions enable row level security;

-- Service role / backend only initially. No direct storefront or authenticated-user mutation.
revoke all on public.experiments from anon, authenticated;
revoke all on public.experiment_variants from anon, authenticated;
revoke all on public.experiment_observations from anon, authenticated;
revoke all on public.experiment_decisions from anon, authenticated;
