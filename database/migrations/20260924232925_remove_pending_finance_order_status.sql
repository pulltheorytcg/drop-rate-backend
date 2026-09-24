-- Unpaid Shopify checkouts are inventory reservations, not finance orders.
-- Keep tcg.orders limited to financial sale lifecycle states.

do $guard$
begin
  if exists (
    select 1 from tcg.orders where status='PENDING'
  ) then
    raise exception 'Cannot remove PENDING order status while PENDING rows exist';
  end if;
end
$guard$;

alter table tcg.orders
  drop constraint if exists orders_status_check;

alter table tcg.orders
  add constraint orders_status_check
  check (
    status = any (
      array[
        'PAID'::text,
        'PARTIALLY_REFUNDED'::text,
        'REFUNDED'::text,
        'CANCELLED'::text
      ]
    )
  );
