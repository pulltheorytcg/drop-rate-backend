begin;

create index fulfilment_cost_components_created_by_user_idx
    on tcg.fulfilment_cost_components(created_by_user_id);

commit;
