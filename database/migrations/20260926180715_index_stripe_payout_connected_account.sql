create index if not exists stripe_payout_executions_connected_account_idx
  on tcg.stripe_payout_executions(connected_account_id);
