-- Enforce Drop Rate's commercial minimum Store Price at the database boundary.
-- Historical Market Value may remain below £1.00; only the sellable Store Price
-- is constrained.

alter table tcg.inventory_items
    drop constraint if exists inventory_items_store_price_floor_check;

alter table tcg.inventory_items
    add constraint inventory_items_store_price_floor_check
    check (store_price_minor is null or store_price_minor >= 100);
