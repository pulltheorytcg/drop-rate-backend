-- Inactive, disposable D1 candidate schema v2. Apply ONLY after candidate
-- 0001_atomic_sale.sql to a FRESH test database; not ops_shadow or production.
-- Supports CARD-only refunds. Shipping refunds remain blocked until a
-- separately source-verified per-owner shipping allocation exists.
-- Single INSERT into candidate_card_refunds triggers all append-only ledger
-- entries, the conditional inventory inspection transition and outbox event.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS candidate_card_refunds (
  id TEXT PRIMARY KEY NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
  source_reference TEXT NOT NULL,
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  order_item_id TEXT NOT NULL REFERENCES candidate_order_items(id),
  inventory_id TEXT NOT NULL REFERENCES candidate_inventory(id),
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  card_amount_minor INTEGER NOT NULL CHECK(card_amount_minor BETWEEN 1 AND 1000000000000),
  currency TEXT NOT NULL CHECK(currency='GBP'),
  return_to_inspection INTEGER NOT NULL CHECK(return_to_inspection IN(0,1)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  occurred_at TEXT NOT NULL,
  UNIQUE(source,source_reference,order_item_id)
);
CREATE INDEX IF NOT EXISTS candidate_refunds_line ON candidate_card_refunds(order_item_id,occurred_at);

CREATE TRIGGER IF NOT EXISTS candidate_refund_before
BEFORE INSERT ON candidate_card_refunds
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM candidate_order_items AS i
    JOIN candidate_orders AS o ON o.id=i.order_id
    JOIN candidate_inventory AS stock ON stock.id=i.inventory_id
    WHERE i.id=NEW.order_item_id
      AND i.order_id=NEW.order_id
      AND i.owner_id=NEW.owner_id
      AND i.inventory_id=NEW.inventory_id
      AND o.source=NEW.source
      AND o.currency=NEW.currency
      AND stock.owner_id=NEW.owner_id
      AND i.net_sale_minor >= (
        NEW.card_amount_minor +
        COALESCE((SELECT sum(r.card_amount_minor)
                  FROM candidate_card_refunds AS r
                  WHERE r.order_item_id=i.id),0))
      -- A prior return is terminal for card refunds of this sale cycle.
      AND NOT EXISTS (
        SELECT 1 FROM candidate_card_refunds AS r
        WHERE r.order_item_id=i.id AND r.return_to_inspection=1)
      -- An existing ledger may never conceal a missing/refunded amount.
      AND COALESCE((
         SELECT sum(l.amount_minor) FROM candidate_ledger l
         WHERE l.order_item_id=i.id AND l.entry_type='REFUND'),0)
          = -COALESCE((
         SELECT sum(r.card_amount_minor) FROM candidate_card_refunds r
         WHERE r.order_item_id=i.id),0)
      -- Before a new refund, its cumulative commission reversal MUST
      -- equal the historical snapshot's remaining-card-value commission.
      AND COALESCE((
        SELECT sum(l.amount_minor) FROM candidate_ledger l
        WHERE l.order_item_id=i.id AND l.entry_type='COMMISSION_REVERSAL'),0)
        = i.commission_minor -
          ((i.net_sale_minor - COALESCE((
              SELECT sum(r.card_amount_minor) FROM candidate_card_refunds r
              WHERE r.order_item_id=i.id),0))
            * i.commission_bps_snapshot + 5000)/10000
      -- Never return the physical copy on a partial refund or after it
      -- has been sold in a newer sale cycle.
      AND (NEW.return_to_inspection=0 OR (
        stock.status='SOLD'
        AND stock.current_sale_item_id=i.id
        AND i.net_sale_minor = (
          NEW.card_amount_minor +
          COALESCE((SELECT sum(r.card_amount_minor)
                    FROM candidate_card_refunds r
                    WHERE r.order_item_id=i.id),0))
      ))
  ) THEN RAISE(ABORT,'candidate refund owner, source, prior ledger or amount mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS candidate_refund_post
AFTER INSERT ON candidate_card_refunds
BEGIN
  INSERT INTO candidate_ledger
    (id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
     funds_status,source_key,occurred_at)
  VALUES ('refund:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.order_item_id,
          'REFUND',-NEW.card_amount_minor,'GBP','PENDING',
          'refund:'||NEW.id,NEW.occurred_at);

  -- This is a *cumulative* commission reversal, not repeatedly rounding
  -- the percentage of each separate refund.
  INSERT INTO candidate_ledger
    (id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
     funds_status,source_key,occurred_at)
  SELECT 'commission-reversal:'||NEW.id,
         NEW.owner_id,NEW.order_id,NEW.order_item_id,
         'COMMISSION_REVERSAL',
         i.commission_minor -
           ((i.net_sale_minor -
             COALESCE((SELECT sum(r.card_amount_minor)
                       FROM candidate_card_refunds r
                       WHERE r.order_item_id=i.id),0))
            * i.commission_bps_snapshot + 5000)/10000 -
           COALESCE((SELECT sum(l.amount_minor)
                     FROM candidate_ledger l
                     WHERE l.order_item_id=i.id
                     AND l.entry_type='COMMISSION_REVERSAL'),0),
         'GBP','PENDING','commission-reversal:'||NEW.id,NEW.occurred_at
  FROM candidate_order_items i
  WHERE i.id=NEW.order_item_id
    AND (
         i.commission_minor -
           ((i.net_sale_minor -
             COALESCE((SELECT sum(r.card_amount_minor)
                       FROM candidate_card_refunds r
                       WHERE r.order_item_id=i.id),0))
              * i.commission_bps_snapshot + 5000)/10000 -
           COALESCE((SELECT sum(l.amount_minor)
                     FROM candidate_ledger l
                     WHERE l.order_item_id=i.id
                     AND l.entry_type='COMMISSION_REVERSAL'),0)
    ) > 0;

  -- The returned item is not automatically APPROVED or relisted.
  UPDATE candidate_inventory
  SET status='INSPECTION',version=version+1
  WHERE NEW.return_to_inspection=1
    AND id=NEW.inventory_id AND owner_id=NEW.owner_id
    AND status='SOLD' AND current_sale_item_id=NEW.order_item_id;
  SELECT CASE WHEN NEW.return_to_inspection=1 AND changes()!=1
    THEN RAISE(ABORT,'candidate refund inventory return lost sale-cycle CAS') END;

  -- Multiple partial refunds of one order require multiple unique outbox
  -- IDs. The original ORDER_POSTED event is preserved.
  INSERT INTO candidate_outbox
    (id,order_id,event_type,payload_sha256,status,created_at)
  VALUES ('refund:'||NEW.id,NEW.order_id,'REFUND_POSTED',NEW.payload_sha256,
          'PENDING',NEW.occurred_at);
END;

CREATE TRIGGER IF NOT EXISTS candidate_refund_no_update
BEFORE UPDATE ON candidate_card_refunds
BEGIN SELECT RAISE(ABORT,'candidate refund event append-only'); END;
CREATE TRIGGER IF NOT EXISTS candidate_refund_no_delete
BEFORE DELETE ON candidate_card_refunds
BEGIN SELECT RAISE(ABORT,'candidate refund event append-only'); END;
