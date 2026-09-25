-- Make fulfilment material allocation explicit and separately auditable.
-- Packaging is shared once per order; protective materials are charged per item.

alter table tcg.fulfilment_cost_components
  add column allocation_basis text not null default 'PER_ITEM';

update tcg.fulfilment_cost_components
set allocation_basis = case
  when component_key = 'PACKAGING' then 'PER_ORDER'
  else 'PER_ITEM'
end;

alter table tcg.fulfilment_cost_components
  add constraint fulfilment_cost_components_allocation_basis_check
  check (allocation_basis in ('PER_ORDER', 'PER_ITEM'));

alter table tcg.financial_ledger_entries
  drop constraint if exists financial_ledger_entries_entry_type_check;

alter table tcg.financial_ledger_entries
  add constraint financial_ledger_entries_entry_type_check
  check (
    entry_type = any (
      array[
        'SALE_REVENUE'::text,
        'SHIPPING_REVENUE'::text,
        'PLATFORM_FEE'::text,
        'PAYMENT_FEE'::text,
        'SHIPPING_COST'::text,
        'FULFILMENT_MATERIAL_COST'::text,
        'REFUND'::text,
        'SHIPPING_REFUND'::text,
        'ADJUSTMENT'::text,
        'PAYOUT'::text
      ]
    )
  );
