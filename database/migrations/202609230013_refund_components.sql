begin;

alter table tcg.refund_events
    add column item_refund_minor bigint,
    add column shipping_refund_minor bigint;

update tcg.refund_events
set item_refund_minor = amount_minor,
    shipping_refund_minor = 0
where item_refund_minor is null or shipping_refund_minor is null;

alter table tcg.refund_events
    alter column item_refund_minor set not null,
    alter column shipping_refund_minor set not null,
    add constraint refund_events_item_refund_nonnegative check (item_refund_minor >= 0),
    add constraint refund_events_shipping_refund_nonnegative check (shipping_refund_minor >= 0),
    add constraint refund_events_component_total_check
        check (amount_minor = item_refund_minor + shipping_refund_minor);

commit;
