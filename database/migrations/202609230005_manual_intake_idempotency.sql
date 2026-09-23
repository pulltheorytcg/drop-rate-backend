begin;

alter table tcg.inventory_items
    add column intake_request_key uuid;

create unique index inventory_intake_request_key_uidx
    on tcg.inventory_items(intake_request_key)
    where intake_request_key is not null;

commit;
