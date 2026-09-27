begin;

create index if not exists recognition_runs_system_idx
    on tcg.recognition_runs(system_code)
    where system_code is not null;

create index if not exists recognition_candidates_system_idx
    on tcg.recognition_candidates(system_code);

commit;
