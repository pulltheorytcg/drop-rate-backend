-- INACTIVE D1/SQLite candidate v3; only apply after 0001 and 0002 in
-- disposable test DB. Production ops_shadow and Supabase remain untouched.
-- The real PostgreSQL source currently contains per-item SHIPPING_REVENUE,
-- SHIPPING_REFUND, and PAYMENT_FEE ledger entries. Their exact original
-- owner/order/item keys must be separately verified before replay.
PRAGMA foreign_keys=ON;

-- Source-verified allocation: exactly one positive shipping revenue amount
-- per historical physical sale item; no inferred shipping split at D1.
CREATE TABLE IF NOT EXISTS candidate_shipping_allocations (
  id TEXT PRIMARY KEY NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
  source_reference TEXT NOT NULL,
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  order_item_id TEXT NOT NULL UNIQUE REFERENCES candidate_order_items(id),
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  amount_minor INTEGER NOT NULL CHECK(amount_minor BETWEEN 1 AND 1000000000000),
  currency TEXT NOT NULL CHECK(currency='GBP'),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  occurred_at TEXT NOT NULL,
  UNIQUE(source,source_reference,order_item_id)
);

CREATE TRIGGER IF NOT EXISTS candidate_shipping_allocation_guard
BEFORE INSERT ON candidate_shipping_allocations
BEGIN
 SELECT CASE WHEN NOT EXISTS(
   SELECT 1 FROM candidate_order_items i
   JOIN candidate_orders o ON o.id=i.order_id
   WHERE i.id=NEW.order_item_id AND i.order_id=NEW.order_id
     AND i.owner_id=NEW.owner_id AND o.source=NEW.source
     AND o.currency=NEW.currency
 ) THEN RAISE(ABORT,'candidate shipping allocation owner/source mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS candidate_shipping_allocation_post
AFTER INSERT ON candidate_shipping_allocations
BEGIN
 INSERT INTO candidate_ledger(
  id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
  funds_status,source_key,occurred_at)
 VALUES (
  'shipping:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.order_item_id,
  'SHIPPING_REVENUE',NEW.amount_minor,'GBP','PENDING',
  'shipping:'||NEW.id,NEW.occurred_at);
 INSERT INTO candidate_outbox(
  id,order_id,event_type,payload_sha256,status,created_at)
 VALUES (
  'shipping:'||NEW.id,NEW.order_id,'SHIPPING_ALLOCATED',
  NEW.payload_sha256,'PENDING',NEW.occurred_at);
END;

-- Each distinct authenticated source refund may partially return shipping
-- revenue, independently from card price, refund amount and commission.
CREATE TABLE IF NOT EXISTS candidate_shipping_refunds (
  id TEXT PRIMARY KEY NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
  source_reference TEXT NOT NULL,
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  order_item_id TEXT NOT NULL REFERENCES candidate_order_items(id),
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  amount_minor INTEGER NOT NULL CHECK(amount_minor BETWEEN 1 AND 1000000000000),
  currency TEXT NOT NULL CHECK(currency='GBP'),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  occurred_at TEXT NOT NULL,
  UNIQUE(source,source_reference,order_item_id)
);
CREATE INDEX IF NOT EXISTS candidate_shipping_refunds_line
  ON candidate_shipping_refunds(order_item_id,occurred_at);

CREATE TRIGGER IF NOT EXISTS candidate_shipping_refund_guard
BEFORE INSERT ON candidate_shipping_refunds
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM candidate_shipping_allocations ship
    JOIN candidate_order_items item ON item.id=ship.order_item_id
    JOIN candidate_orders original ON original.id=item.order_id
    WHERE ship.order_item_id=NEW.order_item_id
      AND ship.order_id=NEW.order_id
      AND ship.owner_id=NEW.owner_id
      AND item.owner_id=NEW.owner_id
      AND original.source=NEW.source
      AND NEW.currency=ship.currency
      AND ship.amount_minor >= NEW.amount_minor +
        COALESCE((SELECT sum(r.amount_minor)
                  FROM candidate_shipping_refunds r
                  WHERE r.order_item_id=ship.order_item_id),0)
      AND COALESCE((SELECT sum(l.amount_minor)
                    FROM candidate_ledger l
                    WHERE l.order_item_id=item.id
                      AND l.entry_type='SHIPPING_REVENUE'),0)
         = ship.amount_minor
      AND COALESCE((SELECT sum(l.amount_minor)
                    FROM candidate_ledger l
                    WHERE l.order_item_id=item.id
                      AND l.entry_type='SHIPPING_REFUND'),0)
         = -COALESCE((SELECT sum(r.amount_minor)
                      FROM candidate_shipping_refunds r
                      WHERE r.order_item_id=item.id),0)
  ) THEN RAISE(ABORT,'candidate shipping refund amount/source/ledger mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS candidate_shipping_refund_post
AFTER INSERT ON candidate_shipping_refunds
BEGIN
 INSERT INTO candidate_ledger(
  id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
  funds_status,source_key,occurred_at)
 VALUES (
  'shipping-refund:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.order_item_id,
  'SHIPPING_REFUND',-NEW.amount_minor,'GBP','PENDING',
  'shipping-refund:'||NEW.id,NEW.occurred_at);
 INSERT INTO candidate_outbox(
  id,order_id,event_type,payload_sha256,status,created_at)
 VALUES (
  'shipping-refund:'||NEW.id,NEW.order_id,'SHIPPING_REFUND_POSTED',
  NEW.payload_sha256,'PENDING',NEW.occurred_at);
END;

-- Source-verified card/payment processor fee is an owner-specific debit.
-- No fee formula, guessed percent, currency conversion or payout execution.
CREATE TABLE IF NOT EXISTS candidate_payment_fees (
 id TEXT PRIMARY KEY NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
 source_reference TEXT NOT NULL,
 order_id TEXT NOT NULL REFERENCES candidate_orders(id),
 order_item_id TEXT NOT NULL REFERENCES candidate_order_items(id),
 owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
 amount_minor INTEGER NOT NULL CHECK(amount_minor BETWEEN 1 AND 1000000000000),
 currency TEXT NOT NULL CHECK(currency='GBP'),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 occurred_at TEXT NOT NULL,
 UNIQUE(source,source_reference,order_item_id)
);
CREATE INDEX IF NOT EXISTS candidate_payment_fees_item
  ON candidate_payment_fees(order_item_id,occurred_at);

CREATE TRIGGER IF NOT EXISTS candidate_payment_fee_guard
BEFORE INSERT ON candidate_payment_fees
BEGIN
 SELECT CASE WHEN NOT EXISTS(
   SELECT 1 FROM candidate_order_items i
   JOIN candidate_orders o ON o.id=i.order_id
   WHERE i.id=NEW.order_item_id AND i.order_id=NEW.order_id
     AND i.owner_id=NEW.owner_id AND o.source=NEW.source
     AND NEW.currency=o.currency
     AND NEW.amount_minor <= i.net_sale_minor +
       COALESCE((SELECT sum(s.amount_minor)
                 FROM candidate_shipping_allocations s
                 WHERE s.order_item_id=i.id),0)
 ) THEN RAISE(ABORT,'candidate payment fee owner/source or amount mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS candidate_payment_fee_post
AFTER INSERT ON candidate_payment_fees
BEGIN
 INSERT INTO candidate_ledger(
  id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
  funds_status,source_key,occurred_at)
 VALUES (
  'payment-fee:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.order_item_id,
  'PAYMENT_FEE',-NEW.amount_minor,'GBP','PENDING',
  'payment-fee:'||NEW.id,NEW.occurred_at);
 INSERT INTO candidate_outbox(
  id,order_id,event_type,payload_sha256,status,created_at)
 VALUES (
  'payment-fee:'||NEW.id,NEW.order_id,'PAYMENT_FEE_POSTED',
  NEW.payload_sha256,'PENDING',NEW.occurred_at);
END;

-- Every posting event is append-only: corrections require an independently
-- verified new compensating event, not editing historical amounts.
CREATE TRIGGER IF NOT EXISTS candidate_shipping_allocation_no_update
BEFORE UPDATE ON candidate_shipping_allocations
BEGIN SELECT RAISE(ABORT,'candidate shipping allocation immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_shipping_allocation_no_delete
BEFORE DELETE ON candidate_shipping_allocations
BEGIN SELECT RAISE(ABORT,'candidate shipping allocation immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_shipping_refund_no_update
BEFORE UPDATE ON candidate_shipping_refunds
BEGIN SELECT RAISE(ABORT,'candidate shipping refund immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_shipping_refund_no_delete
BEFORE DELETE ON candidate_shipping_refunds
BEGIN SELECT RAISE(ABORT,'candidate shipping refund immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_payment_fee_no_update
BEFORE UPDATE ON candidate_payment_fees
BEGIN SELECT RAISE(ABORT,'candidate payment fee immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_payment_fee_no_delete
BEFORE DELETE ON candidate_payment_fees
BEGIN SELECT RAISE(ABORT,'candidate payment fee immutable'); END;
