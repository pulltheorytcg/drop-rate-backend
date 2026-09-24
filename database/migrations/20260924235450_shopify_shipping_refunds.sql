-- Record refunded shipping separately from item refunds so finance summaries
-- and settlement calculations do not leave refunded shipping as retained revenue.

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
        'REFUND'::text,
        'SHIPPING_REFUND'::text,
        'ADJUSTMENT'::text,
        'PAYOUT'::text
      ]
    )
  );
