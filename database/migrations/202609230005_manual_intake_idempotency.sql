begin;

alter table tcg.inventory_items
    add column intake_request_key uuid,
    add constraint inventory_items_intake_request_key_key unique (intake_request_key);

commit;
