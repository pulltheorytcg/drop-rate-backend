begin;

create index financial_ledger_order_item_idx
    on tcg.financial_ledger_entries(order_item_id)
    where order_item_id is not null;

create index financial_ledger_payout_request_idx
    on tcg.financial_ledger_entries(payout_request_id)
    where payout_request_id is not null;

commit;
