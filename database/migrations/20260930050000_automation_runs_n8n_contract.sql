begin;

alter table tcg.automation_runs
  drop constraint if exists automation_runs_job_type_check;

alter table tcg.automation_runs
  add constraint automation_runs_job_type_check
  check (
    job_type='INVENTORY_REVIEW'
    or (
      char_length(job_type) between 6 and 124
      and job_type ~ '^N8N:[a-z0-9][a-z0-9-]{1,119}$'
    )
  );

alter table tcg.automation_runs
  drop constraint if exists automation_runs_initiated_by_check;

alter table tcg.automation_runs
  add constraint automation_runs_initiated_by_check
  check (initiated_by in ('AUTOMATION_SERVICE','N8N'));

alter table tcg.automation_runs
  drop constraint if exists automation_runs_run_key_check;

alter table tcg.automation_runs
  add constraint automation_runs_run_key_check
  check (length(run_key) between 1 and 255);

commit;
