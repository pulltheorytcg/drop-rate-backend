begin;

drop policy own_condition_review_reads on tcg.condition_review_events;
drop policy own_condition_review_inserts on tcg.condition_review_events;

create policy own_condition_review_reads on tcg.condition_review_events
    for select to tcg_api
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(
                (select current_setting('tcg.user_id',true)),
                ''
            )::uuid
              and om.active
        )
    );

create policy own_condition_review_inserts on tcg.condition_review_events
    for insert to tcg_api
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(
                (select current_setting('tcg.user_id',true)),
                ''
            )::uuid
              and om.active
        )
    );

commit;
