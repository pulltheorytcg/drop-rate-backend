-- Drop Rate / Cloudflare D1 operational SHADOW schema v1 — 2026-11-06
-- NO production read path, NO Supabase replacement, NO imported customer data.
-- Apply only in a separate private D1 operational test database AFTER review.
-- D1 is SQLite: FastAPI verifies identity and owner access, NOT a browser D1 token.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS ops_shadow_generations (
 generation_id TEXT PRIMARY KEY,
 source_manifest_sha256 TEXT NOT NULL CHECK(length(source_manifest_sha256)=64),
 source_captured_at TEXT NOT NULL,
 source_schema_sha256 TEXT NOT NULL CHECK(length(source_schema_sha256)=64),
 state TEXT NOT NULL DEFAULT 'STAGING' CHECK(state IN ('STAGING','PARITY_VERIFIED','REJECTED')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE (source_manifest_sha256)
);

-- Identity mapping has NO credentials, passwords, old refresh tokens, session
-- tokens, MFA secrets, password hashes, OAuth provider secrets or IP addresses.
CREATE TABLE IF NOT EXISTS ops_shadow_identity_map (
 legacy_user_id TEXT NOT NULL,
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 external_subject TEXT,
 provider TEXT,
 verified_at TEXT,
 PRIMARY KEY (generation_id,legacy_user_id),
 UNIQUE (generation_id,provider,external_subject),
 CHECK (external_subject IS NULL OR (provider IS NOT NULL AND verified_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ops_shadow_owners (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 id TEXT NOT NULL,
 display_name TEXT NOT NULL,
 owner_type TEXT NOT NULL CHECK (owner_type IN ('FOUNDER','CONSIGNOR')),
 founder_slot INTEGER,
 active INTEGER NOT NULL CHECK(active IN(0,1)),
 commission_bps INTEGER NOT NULL CHECK(commission_bps BETWEEN 0 AND 10000),
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY (generation_id,id),
 CHECK ((owner_type='FOUNDER' AND founder_slot BETWEEN 1 AND 3)
     OR (owner_type='CONSIGNOR' AND founder_slot IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ops_shadow_founder_slot
 ON ops_shadow_owners(generation_id,founder_slot)
 WHERE founder_slot IS NOT NULL;

CREATE TABLE IF NOT EXISTS ops_shadow_memberships (
 generation_id TEXT NOT NULL,
 id TEXT NOT NULL,
 legacy_user_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 role TEXT NOT NULL,
 active INTEGER NOT NULL CHECK(active IN(0,1)),
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,legacy_user_id,owner_id),
 FOREIGN KEY(generation_id,legacy_user_id)
  REFERENCES ops_shadow_identity_map(generation_id,legacy_user_id),
 FOREIGN KEY(generation_id,owner_id)
  REFERENCES ops_shadow_owners(generation_id,id)
);

-- Store only approved stable external catalogue UUIDs, not the 274k raw
-- reference contents, in the single financial/operational database.
CREATE TABLE IF NOT EXISTS ops_shadow_catalogue_links (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 catalogue_id TEXT NOT NULL,
 reference_manifest_sha256 TEXT NOT NULL CHECK(length(reference_manifest_sha256)=64),
 PRIMARY KEY(generation_id,catalogue_id)
);

CREATE TABLE IF NOT EXISTS ops_shadow_inventory (
 generation_id TEXT NOT NULL,
 id TEXT NOT NULL,
 inventory_code TEXT NOT NULL,
 catalogue_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 acquisition_cost_minor INTEGER CHECK(acquisition_cost_minor IS NULL OR acquisition_cost_minor>=0),
 market_value_minor INTEGER CHECK(market_value_minor IS NULL OR market_value_minor>=0),
 store_price_minor INTEGER CHECK(store_price_minor IS NULL OR store_price_minor>=0),
 currency TEXT NOT NULL CHECK(length(currency)=3),
 condition TEXT,
 grading_company TEXT,
 grade TEXT,
 certificate_number TEXT,
 language TEXT,
 location TEXT,
 status TEXT NOT NULL,
 sale_intent TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version>=1),
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,inventory_code),
 FOREIGN KEY(generation_id,owner_id) REFERENCES ops_shadow_owners(generation_id,id),
 FOREIGN KEY(generation_id,catalogue_id) REFERENCES ops_shadow_catalogue_links(generation_id,catalogue_id)
);
CREATE INDEX IF NOT EXISTS ops_shadow_inventory_owner
 ON ops_shadow_inventory(generation_id,owner_id,status,inventory_code);

CREATE TABLE IF NOT EXISTS ops_shadow_orders (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 id TEXT NOT NULL,
 source TEXT NOT NULL,
 source_reference TEXT NOT NULL,
 currency TEXT NOT NULL CHECK(length(currency)=3),
 status TEXT NOT NULL,
 placed_at TEXT NOT NULL,
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,source,source_reference)
);

CREATE TABLE IF NOT EXISTS ops_shadow_order_items (
 generation_id TEXT NOT NULL,
 id TEXT NOT NULL,
 order_id TEXT NOT NULL,
 inventory_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 sale_price_minor INTEGER NOT NULL CHECK(sale_price_minor>=0),
 discount_minor INTEGER NOT NULL CHECK(discount_minor>=0),
 net_sale_minor INTEGER CHECK(net_sale_minor IS NULL OR net_sale_minor>=0),
 cost_basis_minor INTEGER CHECK(cost_basis_minor IS NULL OR cost_basis_minor>=0),
 commission_bps_snapshot INTEGER NOT NULL CHECK(commission_bps_snapshot BETWEEN 0 AND 10000),
 commission_minor INTEGER NOT NULL CHECK(commission_minor>=0),
 sold_at TEXT NOT NULL,
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,order_id,inventory_id),
 FOREIGN KEY(generation_id,order_id) REFERENCES ops_shadow_orders(generation_id,id),
 FOREIGN KEY(generation_id,inventory_id) REFERENCES ops_shadow_inventory(generation_id,id),
 FOREIGN KEY(generation_id,owner_id) REFERENCES ops_shadow_owners(generation_id,id),
 CHECK(discount_minor<=sale_price_minor),
 CHECK(net_sale_minor IS NULL OR net_sale_minor=sale_price_minor-discount_minor)
);

-- D1 does not implement Postgres RLS: all owner/inventory relationship checks
-- before a write belong in FastAPI in addition to these FK constraints.
CREATE TRIGGER IF NOT EXISTS ops_shadow_sale_owner_match
 BEFORE INSERT ON ops_shadow_order_items
 WHEN NEW.owner_id != (
   SELECT owner_id FROM ops_shadow_inventory
   WHERE generation_id=NEW.generation_id AND id=NEW.inventory_id
 )
 BEGIN SELECT RAISE(ABORT,'sale owner differs from inventory owner'); END;

CREATE TABLE IF NOT EXISTS ops_shadow_webhook_inbox (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 id TEXT NOT NULL,
 webhook_id TEXT NOT NULL,
 topic TEXT NOT NULL,
 shop_domain TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 status TEXT NOT NULL,
 received_at TEXT NOT NULL,
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,webhook_id)
);

CREATE TABLE IF NOT EXISTS ops_shadow_refunds (
 generation_id TEXT NOT NULL,
 id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 order_id TEXT NOT NULL,
 order_item_id TEXT NOT NULL,
 inventory_id TEXT NOT NULL,
 source_reference TEXT NOT NULL,
 amount_minor INTEGER NOT NULL CHECK(amount_minor>=0),
 currency TEXT NOT NULL CHECK(length(currency)=3),
 occurred_at TEXT NOT NULL,
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,order_id,order_item_id,source_reference),
 FOREIGN KEY(generation_id,owner_id) REFERENCES ops_shadow_owners(generation_id,id),
 FOREIGN KEY(generation_id,order_id) REFERENCES ops_shadow_orders(generation_id,id),
 FOREIGN KEY(generation_id,order_item_id) REFERENCES ops_shadow_order_items(generation_id,id),
 FOREIGN KEY(generation_id,inventory_id) REFERENCES ops_shadow_inventory(generation_id,id)
);

CREATE TABLE IF NOT EXISTS ops_shadow_ledger (
 generation_id TEXT NOT NULL,
 id TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 order_id TEXT,
 order_item_id TEXT,
 payout_request_id TEXT,
 entry_type TEXT NOT NULL,
 amount_minor INTEGER NOT NULL,
 currency TEXT NOT NULL CHECK(length(currency)=3),
 funds_status TEXT NOT NULL,
 source_key TEXT NOT NULL,
 occurred_at TEXT NOT NULL,
 available_at TEXT,
 source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
 source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
 PRIMARY KEY(generation_id,id),
 UNIQUE(generation_id,source_key),
 FOREIGN KEY(generation_id,owner_id) REFERENCES ops_shadow_owners(generation_id,id),
 FOREIGN KEY(generation_id,order_id) REFERENCES ops_shadow_orders(generation_id,id),
 FOREIGN KEY(generation_id,order_item_id) REFERENCES ops_shadow_order_items(generation_id,id)
);
CREATE INDEX IF NOT EXISTS ops_shadow_ledger_owner
 ON ops_shadow_ledger(generation_id,owner_id,currency,occurred_at);
CREATE TRIGGER IF NOT EXISTS ops_shadow_ledger_no_update BEFORE UPDATE ON ops_shadow_ledger
 BEGIN SELECT RAISE(ABORT,'ledger entries are append-only'); END;
CREATE TRIGGER IF NOT EXISTS ops_shadow_ledger_no_delete BEFORE DELETE ON ops_shadow_ledger
 BEGIN SELECT RAISE(ABORT,'ledger entries are append-only'); END;

-- This is a private isolated staging database. There is intentionally
-- NO production active-generation pointer, no Shopify publishing endpoint,
-- no payments/money movement and no public D1 token.
CREATE TABLE IF NOT EXISTS ops_shadow_table_receipts (
 generation_id TEXT NOT NULL REFERENCES ops_shadow_generations(generation_id),
 source_schema TEXT NOT NULL,
 source_table TEXT NOT NULL,
 exact_source_rows INTEGER NOT NULL CHECK(exact_source_rows>=0),
 exact_staged_rows INTEGER NOT NULL CHECK(exact_staged_rows>=0),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 staged_sha256 TEXT NOT NULL CHECK(length(staged_sha256)=64),
 verified_at TEXT NOT NULL,
 PRIMARY KEY(generation_id,source_schema,source_table),
 CHECK(exact_source_rows=exact_staged_rows),
 CHECK(source_sha256=staged_sha256)
);
