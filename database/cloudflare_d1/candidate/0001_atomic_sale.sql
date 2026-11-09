-- INACTIVE CANDIDATE ONLY. Do not apply to the operational D1 shadow or production.
-- Separate disposable D1/SQLite test schema; no public API or financial authority.
-- All statements in one posting plan MUST execute as one Cloudflare Worker D1
-- db.batch() transaction; independent REST calls are expressly unsupported.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS candidate_owners (
  id TEXT PRIMARY KEY NOT NULL,
  owner_type TEXT NOT NULL CHECK(owner_type IN ('FOUNDER','CONSIGNOR')),
  founder_slot INTEGER,
  active INTEGER NOT NULL CHECK(active IN (0,1)),
  commission_bps INTEGER NOT NULL CHECK(commission_bps BETWEEN 0 AND 10000),
  CHECK ((owner_type='FOUNDER' AND founder_slot BETWEEN 1 AND 3 AND commission_bps=0)
      OR (owner_type='CONSIGNOR' AND founder_slot IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS candidate_founder_slot
  ON candidate_owners(founder_slot) WHERE founder_slot IS NOT NULL;

CREATE TABLE IF NOT EXISTS candidate_inventory (
  id TEXT PRIMARY KEY NOT NULL,
  inventory_code TEXT NOT NULL UNIQUE,
  catalogue_id TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  status TEXT NOT NULL CHECK(status IN
    ('RECEIVED','INSPECTION','APPROVED','RESERVED','SOLD','WITHDRAWN')),
  sale_intent TEXT NOT NULL CHECK(sale_intent IN ('FOR_SALE','PERSONAL_COLLECTION')),
  version INTEGER NOT NULL CHECK(version>=1),
  acquisition_cost_minor INTEGER CHECK(acquisition_cost_minor IS NULL OR acquisition_cost_minor>=0),
  currency TEXT NOT NULL CHECK(currency='GBP')
);
CREATE INDEX IF NOT EXISTS candidate_inventory_owner ON candidate_inventory(owner_id,status);

CREATE TABLE IF NOT EXISTS candidate_orders (
  id TEXT PRIMARY KEY NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
  source_reference TEXT NOT NULL,
  currency TEXT NOT NULL CHECK(currency='GBP'),
  status TEXT NOT NULL CHECK(status='RECONCILIATION_REQUIRED'),
  placed_at TEXT NOT NULL,
  UNIQUE(source,source_reference)
);
CREATE TABLE IF NOT EXISTS candidate_webhook_inbox (
  webhook_id TEXT PRIMARY KEY NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('SHOPIFY','EBAY')),
  shop_domain TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  order_id TEXT NOT NULL REFERENCES candidate_orders(id) DEFERRABLE INITIALLY DEFERRED,
  received_at TEXT NOT NULL,
  UNIQUE(source,shop_domain,webhook_id)
);
CREATE TABLE IF NOT EXISTS candidate_order_items (
  id TEXT PRIMARY KEY NOT NULL,
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  inventory_id TEXT NOT NULL UNIQUE REFERENCES candidate_inventory(id),
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  expected_inventory_version INTEGER NOT NULL CHECK(expected_inventory_version>=1),
  sale_price_minor INTEGER NOT NULL CHECK(sale_price_minor BETWEEN 1 AND 1000000000000),
  discount_minor INTEGER NOT NULL CHECK(discount_minor>=0),
  net_sale_minor INTEGER NOT NULL CHECK(net_sale_minor>0),
  cost_basis_minor INTEGER CHECK(cost_basis_minor IS NULL OR cost_basis_minor>=0),
  commission_bps_snapshot INTEGER NOT NULL CHECK(commission_bps_snapshot BETWEEN 0 AND 10000),
  commission_minor INTEGER NOT NULL CHECK(commission_minor>=0),
  sold_at TEXT NOT NULL,
  UNIQUE(order_id,inventory_id),
  CHECK(discount_minor<sale_price_minor),
  CHECK(net_sale_minor=sale_price_minor-discount_minor),
  CHECK(commission_minor=(net_sale_minor*commission_bps_snapshot+5000)/10000)
);
CREATE INDEX IF NOT EXISTS candidate_items_owner_order ON candidate_order_items(owner_id,order_id);

CREATE TABLE IF NOT EXISTS candidate_ledger (
  id TEXT PRIMARY KEY NOT NULL,
  owner_id TEXT NOT NULL REFERENCES candidate_owners(id),
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  order_item_id TEXT NOT NULL REFERENCES candidate_order_items(id),
  entry_type TEXT NOT NULL CHECK(entry_type IN ('SALE_REVENUE','COMMISSION')),
  amount_minor INTEGER NOT NULL CHECK(amount_minor<>0),
  currency TEXT NOT NULL CHECK(currency='GBP'),
  funds_status TEXT NOT NULL CHECK(funds_status='PENDING'),
  source_key TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL,
  CHECK((entry_type='SALE_REVENUE' AND amount_minor>0)
     OR (entry_type='COMMISSION' AND amount_minor<0))
);
CREATE INDEX IF NOT EXISTS candidate_ledger_owner ON candidate_ledger(owner_id,occurred_at);

CREATE TABLE IF NOT EXISTS candidate_outbox (
  id TEXT PRIMARY KEY NOT NULL,
  order_id TEXT NOT NULL REFERENCES candidate_orders(id),
  event_type TEXT NOT NULL CHECK(event_type='ORDER_POSTED'),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  status TEXT NOT NULL CHECK(status='PENDING'),
  created_at TEXT NOT NULL,
  UNIQUE(order_id,event_type)
);

-- The client cannot invent an owner, skip a version, mis-state cost basis or
-- silently change commission. This guard is checked at the point of INSERT.
CREATE TRIGGER IF NOT EXISTS candidate_item_sale_guard
BEFORE INSERT ON candidate_order_items
BEGIN
  SELECT CASE WHEN NOT EXISTS(
    SELECT 1 FROM candidate_inventory i
    JOIN candidate_owners o ON o.id=i.owner_id
    WHERE i.id=NEW.inventory_id
      AND i.owner_id=NEW.owner_id
      AND i.status='APPROVED'
      AND i.sale_intent='FOR_SALE'
      AND i.currency='GBP'
      AND i.version=NEW.expected_inventory_version
      AND i.acquisition_cost_minor IS NEW.cost_basis_minor
      AND o.active=1
      AND o.commission_bps=NEW.commission_bps_snapshot
  ) THEN RAISE(ABORT,'candidate sale state, cost, commission or ownership mismatch') END;
END;

-- The inventory transition and original ledger posting MUST be atomic with
-- inbox, order, lines and outbox. Commission is snapshotted per owner.
CREATE TRIGGER IF NOT EXISTS candidate_item_sale_post
AFTER INSERT ON candidate_order_items
BEGIN
  UPDATE candidate_inventory SET status='SOLD',version=version+1
  WHERE id=NEW.inventory_id AND owner_id=NEW.owner_id
    AND status='APPROVED' AND version=NEW.expected_inventory_version;
  SELECT CASE WHEN changes()!=1
    THEN RAISE(ABORT,'candidate inventory sale lost its compare-and-swap') END;
  INSERT INTO candidate_ledger
    (id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
     funds_status,source_key,occurred_at)
  VALUES
    ('sale:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.id,'SALE_REVENUE',
     NEW.net_sale_minor,'GBP','PENDING','sale:'||NEW.id,NEW.sold_at);
  INSERT INTO candidate_ledger
    (id,owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
     funds_status,source_key,occurred_at)
  SELECT
    'commission:'||NEW.id,NEW.owner_id,NEW.order_id,NEW.id,'COMMISSION',
    -NEW.commission_minor,'GBP','PENDING','commission:'||NEW.id,NEW.sold_at
  WHERE NEW.commission_minor>0;
END;

-- Ledger and source-linked sale lines are immutable. Financial corrections
-- will require separate signed, append-only reversal events in a later phase.
CREATE TRIGGER IF NOT EXISTS candidate_ledger_no_update BEFORE UPDATE ON candidate_ledger
BEGIN SELECT RAISE(ABORT,'candidate ledger append-only'); END;
CREATE TRIGGER IF NOT EXISTS candidate_ledger_no_delete BEFORE DELETE ON candidate_ledger
BEGIN SELECT RAISE(ABORT,'candidate ledger append-only'); END;
CREATE TRIGGER IF NOT EXISTS candidate_item_no_update BEFORE UPDATE ON candidate_order_items
BEGIN SELECT RAISE(ABORT,'candidate sale lineage immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_item_no_delete BEFORE DELETE ON candidate_order_items
BEGIN SELECT RAISE(ABORT,'candidate sale lineage immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_owner_transfer_block
BEFORE UPDATE OF owner_id ON candidate_inventory
BEGIN SELECT RAISE(ABORT,'candidate ownership transfer requires audited workflow'); END;
CREATE TRIGGER IF NOT EXISTS candidate_inbox_no_update BEFORE UPDATE ON candidate_webhook_inbox
BEGIN SELECT RAISE(ABORT,'candidate webhook inbox immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_inbox_no_delete BEFORE DELETE ON candidate_webhook_inbox
BEGIN SELECT RAISE(ABORT,'candidate webhook inbox immutable'); END;

CREATE TRIGGER IF NOT EXISTS candidate_ledger_lineage_guard
BEFORE INSERT ON candidate_ledger
BEGIN
  SELECT CASE WHEN NOT EXISTS(
    SELECT 1 FROM candidate_order_items oi WHERE oi.id=NEW.order_item_id
      AND oi.owner_id=NEW.owner_id AND oi.order_id=NEW.order_id
  ) THEN RAISE(ABORT,'candidate ledger owner/sale mismatch') END;
END;
