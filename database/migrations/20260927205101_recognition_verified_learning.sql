begin;

-- Recognition Engine v1.3 verified-learning foundation.
-- Only explicit human labels become learning truth. Raw scan pixels remain ephemeral.
-- Learning data is append-only, audited and separated into train/validation/holdout
-- partitions so future model/reranker changes can be evaluated without leakage.

alter table tcg.recognition_runs
    add column source_width integer check (
        source_width is null or source_width between 200 and 20000
    ),
    add column source_height integer check (
        source_height is null or source_height between 200 and 20000
    ),
    add column source_fingerprints jsonb not null default '[]'::jsonb
        check (
            jsonb_typeof(source_fingerprints)='array'
            and jsonb_array_length(source_fingerprints) <= 16
        );

create table tcg.recognition_learning_examples (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references tcg.recognition_runs(id),
    feedback_id uuid not null unique references tcg.recognition_feedback(id),
    owner_id uuid not null references tcg.owners(id),
    system_code text not null references tcg.collectible_systems(code),
    selected_catalogue_id uuid references tcg.catalogue_products(id),
    label_outcome text not null
        check (label_outcome in (
            'CONFIRMED_TOP',
            'CORRECTED_TO_CANDIDATE',
            'REJECTED_ALL'
        )),
    engine_version text not null check (length(engine_version) between 1 and 64),
    vision_model text not null check (length(vision_model) between 1 and 200),
    source_image_sha256 text not null
        check (source_image_sha256 ~ '^[0-9a-f]{64}$'),
    source_width integer check (
        source_width is null or source_width between 200 and 20000
    ),
    source_height integer check (
        source_height is null or source_height between 200 and 20000
    ),
    source_fingerprints jsonb not null default '[]'::jsonb
        check (
            jsonb_typeof(source_fingerprints)='array'
            and jsonb_array_length(source_fingerprints) <= 16
        ),
    observation jsonb not null default '{}'::jsonb,
    provider_evidence jsonb not null default '{}'::jsonb,
    top_score numeric(6,5) check (
        top_score is null or (top_score >= 0 and top_score <= 1)
    ),
    runner_up_score numeric(6,5) check (
        runner_up_score is null or (runner_up_score >= 0 and runner_up_score <= 1)
    ),
    score_margin numeric(6,5) check (
        score_margin is null or (score_margin >= 0 and score_margin <= 1)
    ),
    dataset_split text not null
        check (dataset_split in ('TRAIN','VALIDATION','HOLDOUT')),
    supersedes_example_id uuid references tcg.recognition_learning_examples(id),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    check (
        (label_outcome in ('CONFIRMED_TOP','CORRECTED_TO_CANDIDATE')
         and selected_catalogue_id is not null)
        or
        (label_outcome='REJECTED_ALL' and selected_catalogue_id is null)
    )
);

create index recognition_learning_owner_created_idx
    on tcg.recognition_learning_examples(owner_id, created_at desc);
create index recognition_learning_catalogue_split_idx
    on tcg.recognition_learning_examples(selected_catalogue_id, dataset_split, created_at desc)
    where selected_catalogue_id is not null;
create index recognition_learning_run_created_idx
    on tcg.recognition_learning_examples(run_id, created_at desc);
create index recognition_learning_system_split_idx
    on tcg.recognition_learning_examples(system_code, dataset_split, created_at desc);
create index recognition_learning_supersedes_idx
    on tcg.recognition_learning_examples(supersedes_example_id)
    where supersedes_example_id is not null;
create index recognition_learning_created_by_idx
    on tcg.recognition_learning_examples(created_by_user_id);

create table tcg.recognition_hard_negatives (
    id uuid primary key default gen_random_uuid(),
    learning_example_id uuid not null
        references tcg.recognition_learning_examples(id),
    candidate_key text not null,
    source_kind text not null
        check (source_kind in ('CATALOGUE','PROVIDER')),
    negative_catalogue_id uuid references tcg.catalogue_products(id),
    provider text,
    provider_id text,
    original_rank integer not null check (original_rank >= 1),
    original_score numeric(6,5) not null check (
        original_score >= 0 and original_score <= 1
    ),
    negative_reason text not null
        check (negative_reason in (
            'WRONG_VIABLE_CANDIDATE',
            'REJECTED_ALL'
        )),
    signals jsonb not null default '{}'::jsonb,
    candidate_snapshot jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default clock_timestamp(),
    unique (learning_example_id, candidate_key)
);

create index recognition_hard_negatives_catalogue_idx
    on tcg.recognition_hard_negatives(negative_catalogue_id, created_at desc)
    where negative_catalogue_id is not null;
create index recognition_hard_negatives_provider_idx
    on tcg.recognition_hard_negatives(provider, provider_id)
    where provider_id is not null;

create table tcg.recognition_model_versions (
    id uuid primary key default gen_random_uuid(),
    engine_version text not null check (length(engine_version) between 1 and 64),
    vision_model text not null check (length(vision_model) between 1 and 200),
    status text not null
        check (status in ('CANDIDATE','PRODUCTION','RETIRED')),
    metrics jsonb not null default '{}'::jsonb,
    source_commit text,
    created_by_user_id uuid not null references auth.users(id),
    promoted_at timestamptz,
    created_at timestamptz not null default clock_timestamp(),
    unique (engine_version, vision_model),
    check (
        (status='PRODUCTION' and promoted_at is not null)
        or status <> 'PRODUCTION'
    )
);

create index recognition_model_versions_status_idx
    on tcg.recognition_model_versions(status, created_at desc);
create index recognition_model_versions_created_by_idx
    on tcg.recognition_model_versions(created_by_user_id);

alter table tcg.recognition_learning_examples enable row level security;
alter table tcg.recognition_learning_examples force row level security;
alter table tcg.recognition_hard_negatives enable row level security;
alter table tcg.recognition_hard_negatives force row level security;
alter table tcg.recognition_model_versions enable row level security;
alter table tcg.recognition_model_versions force row level security;

create policy admin_access on tcg.recognition_learning_examples
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_learning_examples
    for select to tcg_api
    using (
        tcg.is_platform_admin()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );
create policy api_insert on tcg.recognition_learning_examples
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and created_by_user_id=tcg.current_user_id()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );

create policy admin_access on tcg.recognition_hard_negatives
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_hard_negatives
    for select to tcg_api
    using (
        tcg.is_platform_admin()
        and exists (
            select 1
            from tcg.recognition_learning_examples e
            join tcg.owner_memberships m on m.owner_id=e.owner_id
            where e.id=recognition_hard_negatives.learning_example_id
              and m.user_id=tcg.current_user_id()
              and m.active
        )
    );
create policy api_insert on tcg.recognition_hard_negatives
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and exists (
            select 1
            from tcg.recognition_learning_examples e
            join tcg.owner_memberships m on m.owner_id=e.owner_id
            where e.id=recognition_hard_negatives.learning_example_id
              and m.user_id=tcg.current_user_id()
              and m.active
        )
    );

create policy admin_access on tcg.recognition_model_versions
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_model_versions
    for select to tcg_api
    using (tcg.is_platform_admin());
create policy api_insert on tcg.recognition_model_versions
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and created_by_user_id=tcg.current_user_id()
    );

revoke all on
    tcg.recognition_learning_examples,
    tcg.recognition_hard_negatives,
    tcg.recognition_model_versions
from public,anon,authenticated;

grant select,insert on
    tcg.recognition_learning_examples,
    tcg.recognition_hard_negatives,
    tcg.recognition_model_versions
to tcg_api;

revoke update,delete on
    tcg.recognition_learning_examples,
    tcg.recognition_hard_negatives,
    tcg.recognition_model_versions
from tcg_api;

create trigger recognition_learning_examples_immutable
    before update or delete on tcg.recognition_learning_examples
    for each row execute function tcg.prevent_recognition_candidate_mutation();

create trigger recognition_hard_negatives_immutable
    before update or delete on tcg.recognition_hard_negatives
    for each row execute function tcg.prevent_recognition_candidate_mutation();

create trigger recognition_learning_examples_audit
    after insert or update or delete on tcg.recognition_learning_examples
    for each row execute function tcg.audit_recognition_change();

create trigger recognition_hard_negatives_audit
    after insert or update or delete on tcg.recognition_hard_negatives
    for each row execute function tcg.audit_recognition_change();

create trigger recognition_model_versions_audit
    after insert or update or delete on tcg.recognition_model_versions
    for each row execute function tcg.audit_recognition_change();

commit;
