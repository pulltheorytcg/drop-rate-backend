begin;

alter table tcg.inventory_items
    drop constraint inventory_items_status_check;

alter table tcg.inventory_items
    add constraint inventory_items_status_check
    check (status in ('DRAFT', 'INSPECTION', 'APPROVED', 'WITHDRAWN'));

commit;
