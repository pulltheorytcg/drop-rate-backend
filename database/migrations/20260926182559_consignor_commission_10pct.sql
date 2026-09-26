alter table tcg.owners
  add column if not exists commission_bps integer;

update tcg.owners
set commission_bps = case
  when owner_type = 'CONSIGNOR' then 1000
  else 0
end
where commission_bps is null;

create or replace function tcg.apply_owner_commission_default()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
begin
  if new.commission_bps is null then
    new.commission_bps := case
      when new.owner_type = 'CONSIGNOR' then 1000
      else 0
    end;
  end if;
  if new.owner_type = 'FOUNDER' and new.commission_bps <> 0 then
    raise exception 'Founder-owned inventory cannot carry marketplace commission'
      using errcode='23514';
  end if;
  if new.commission_bps < 0 or new.commission_bps > 10000 then
    raise exception 'Commission basis points must be between 0 and 10000'
      using errcode='23514';
  end if;
  return new;
end;
$function$;

drop trigger if exists owners_commission_default_guard on tcg.owners;
create trigger owners_commission_default_guard
before insert or update of owner_type,commission_bps on tcg.owners
for each row execute function tcg.apply_owner_commission_default();

alter table tcg.owners
  alter column commission_bps set not null;

alter table tcg.owners
  drop constraint if exists owners_commission_bps_check;
alter table tcg.owners
  add constraint owners_commission_bps_check
  check (
    commission_bps between 0 and 10000
    and (owner_type <> 'FOUNDER' or commission_bps = 0)
  );

create or replace function tcg.calculate_commission_minor(
  net_sale_minor bigint,
  commission_bps integer
)
returns bigint
language plpgsql
immutable
strict
set search_path to 'pg_catalog'
as $function$
begin
  if net_sale_minor < 0 then
    raise exception 'Net sale cannot be negative'
      using errcode='23514';
  end if;
  if commission_bps < 0 or commission_bps > 10000 then
    raise exception 'Commission basis points must be between 0 and 10000'
      using errcode='23514';
  end if;
  return round((net_sale_minor::numeric * commission_bps::numeric) / 10000)::bigint;
end;
$function$;

revoke all on function tcg.calculate_commission_minor(bigint,integer) from public;
grant execute on function tcg.calculate_commission_minor(bigint,integer) to tcg_api;

alter table tcg.order_items
  add column if not exists commission_bps_snapshot integer not null default 0,
  add column if not exists commission_minor bigint not null default 0;

alter table tcg.order_items
  drop constraint if exists order_items_commission_bps_snapshot_check;
alter table tcg.order_items
  add constraint order_items_commission_bps_snapshot_check
  check (commission_bps_snapshot between 0 and 10000);

alter table tcg.order_items
  drop constraint if exists order_items_commission_minor_check;
alter table tcg.order_items
  add constraint order_items_commission_minor_check
  check (
    commission_minor >= 0
    and commission_minor <= (sale_price_minor - discount_minor)
  );

create or replace function tcg.snapshot_order_item_commission()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
declare
  rate_bps integer;
begin
  select commission_bps
  into rate_bps
  from tcg.owners
  where id = new.owner_id;

  if rate_bps is null then
    raise exception 'Order item owner has no commission configuration'
      using errcode='23503';
  end if;

  new.commission_bps_snapshot := rate_bps;
  new.commission_minor := tcg.calculate_commission_minor(
    new.sale_price_minor - new.discount_minor,
    rate_bps
  );
  return new;
end;
$function$;

drop trigger if exists order_items_commission_snapshot on tcg.order_items;
create trigger order_items_commission_snapshot
before insert on tcg.order_items
for each row execute function tcg.snapshot_order_item_commission();

alter table tcg.financial_ledger_entries
  drop constraint if exists financial_ledger_entries_entry_type_check;
alter table tcg.financial_ledger_entries
  add constraint financial_ledger_entries_entry_type_check
  check (entry_type in (
    'SALE_REVENUE',
    'SHIPPING_REVENUE',
    'PLATFORM_FEE',
    'PAYMENT_FEE',
    'SHIPPING_COST',
    'FULFILMENT_MATERIAL_COST',
    'COMMISSION',
    'COMMISSION_REVERSAL',
    'REFUND',
    'SHIPPING_REFUND',
    'ADJUSTMENT',
    'PAYOUT'
  ));

create or replace function tcg.apply_commission_ledger()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
declare
  original_commission bigint;
  rate_bps integer;
  net_sale bigint;
  cumulative_refund bigint;
  target_retained_commission bigint;
  target_reversal bigint;
  current_reversal bigint;
  reversal_delta bigint;
begin
  if new.order_item_id is null then
    return new;
  end if;

  if new.entry_type = 'SALE_REVENUE' then
    select commission_minor
    into original_commission
    from tcg.order_items
    where id = new.order_item_id;

    if original_commission is null then
      raise exception 'Sale revenue references an unknown order item'
        using errcode='23503';
    end if;

    if original_commission > 0 then
      insert into tcg.financial_ledger_entries(
        owner_id,order_id,order_item_id,entry_type,amount_minor,
        currency,funds_status,source_key,occurred_at,available_at,notes
      ) values(
        new.owner_id,new.order_id,new.order_item_id,'COMMISSION',
        -original_commission,new.currency,new.funds_status,
        'commission:' || new.order_item_id::text,
        new.occurred_at,new.available_at,
        'Drop Rate marketplace commission snapshotted at sale.'
      )
      on conflict(source_key) do nothing;
    end if;
    return new;
  end if;

  if new.entry_type <> 'REFUND' then
    return new;
  end if;

  perform pg_advisory_xact_lock(hashtext(new.order_item_id::text));

  select net_sale_minor,commission_bps_snapshot,commission_minor
  into net_sale,rate_bps,original_commission
  from tcg.order_items
  where id = new.order_item_id;

  if net_sale is null then
    raise exception 'Refund references an unknown order item'
      using errcode='23503';
  end if;

  select coalesce(-sum(amount_minor),0)::bigint
  into cumulative_refund
  from tcg.financial_ledger_entries
  where order_item_id = new.order_item_id
    and entry_type = 'REFUND';

  if cumulative_refund > net_sale then
    raise exception 'Item refunds exceed original net sale'
      using errcode='23514';
  end if;

  target_retained_commission := tcg.calculate_commission_minor(
    net_sale - cumulative_refund,
    rate_bps
  );
  target_reversal := original_commission - target_retained_commission;

  select coalesce(sum(amount_minor),0)::bigint
  into current_reversal
  from tcg.financial_ledger_entries
  where order_item_id = new.order_item_id
    and entry_type = 'COMMISSION_REVERSAL';

  reversal_delta := target_reversal - current_reversal;

  if reversal_delta < 0 then
    raise exception 'Commission reversal state is inconsistent'
      using errcode='23514';
  end if;

  if reversal_delta > 0 then
    insert into tcg.financial_ledger_entries(
      owner_id,order_id,order_item_id,entry_type,amount_minor,
      currency,funds_status,source_key,occurred_at,available_at,notes
    ) values(
      new.owner_id,new.order_id,new.order_item_id,'COMMISSION_REVERSAL',
      reversal_delta,new.currency,new.funds_status,
      'commission-reversal:' || new.source_key,
      new.occurred_at,new.available_at,
      'Drop Rate commission reversed proportionally to item refund.'
    )
    on conflict(source_key) do nothing;
  end if;

  return new;
end;
$function$;

drop trigger if exists financial_ledger_commission on tcg.financial_ledger_entries;
create trigger financial_ledger_commission
after insert on tcg.financial_ledger_entries
for each row execute function tcg.apply_commission_ledger();

create or replace function tcg.audit_owner_commission_change()
returns trigger
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
  if new.commission_bps is distinct from old.commission_bps then
    insert into tcg.audit_events(
      actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values(
      coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
      nullif(current_setting('tcg.request_id',true),''),
      'OWNER_COMMISSION_CHANGED',
      'OWNER',
      new.id,
      jsonb_build_object('commission_bps',old.commission_bps),
      jsonb_build_object('commission_bps',new.commission_bps)
    );
  end if;
  return null;
end;
$function$;

drop trigger if exists owners_commission_audit on tcg.owners;
create trigger owners_commission_audit
after update of commission_bps on tcg.owners
for each row execute function tcg.audit_owner_commission_change();
