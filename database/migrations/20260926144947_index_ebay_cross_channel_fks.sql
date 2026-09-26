create index ebay_inventory_links_created_by_user_idx
    on tcg.ebay_inventory_links(created_by_user_id);

create index ebay_order_item_links_created_by_user_idx
    on tcg.ebay_order_item_links(created_by_user_id);

create index ebay_order_item_links_inventory_idx
    on tcg.ebay_order_item_links(inventory_id);

create index ebay_order_item_links_internal_order_idx
    on tcg.ebay_order_item_links(order_id);
