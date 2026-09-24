-- Track unpaid Shopify order reservations for single-item inventory links.
-- Financial order items and ledger entries remain deferred until orders/paid.

alter table tcg.orders
  drop constraint if exists orders_status_check;

alter table tcg.orders
  add constraint orders_status_check
  check (
    status = any (
      array[
        'PENDING'::text,
        'PAID'::text,
        'PARTIALLY_REFUNDED'::text,
        'REFUNDED'::text,
        'CANCELLED'::text
      ]
    )
  );

alter table tcg.shopify_inventory_links
  add column if not exists reserved_order_reference text,
  add column if not exists reserved_line_reference text,
  add column if not exists reserved_at timestamptz;

alter table tcg.shopify_inventory_links
  drop constraint if exists shopify_inventory_links_reservation_tuple_check;

alter table tcg.shopify_inventory_links
  add constraint shopify_inventory_links_reservation_tuple_check
  check (
    (
      reserved_order_reference is null
      and reserved_line_reference is null
      and reserved_at is null
    )
    or
    (
      nullif(btrim(reserved_order_reference), '') is not null
      and nullif(btrim(reserved_line_reference), '') is not null
      and reserved_at is not null
    )
  );

create index if not exists shopify_inventory_links_reserved_order_idx
  on tcg.shopify_inventory_links(reserved_order_reference)
  where reserved_order_reference is not null;
