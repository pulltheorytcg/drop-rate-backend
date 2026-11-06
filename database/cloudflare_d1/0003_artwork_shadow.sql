-- Cloudflare R2/D1 ARTWORK-ONLY SHADOW, not the production database.
-- No owner, payment, Auth, live media pointers, or Shopify publication.
-- Apply only to a separate Cloudflare artwork staging D1 database.
CREATE TABLE IF NOT EXISTS artwork_shadow_candidates (
  reference_key TEXT NOT NULL CHECK(length(reference_key)=66 AND substr(reference_key,1,2)='x:'),
  provider TEXT NOT NULL,
  system_code TEXT NOT NULL,
  language TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  set_id TEXT NOT NULL,
  card_number TEXT NOT NULL,
  rarity TEXT NOT NULL,
  finish TEXT NOT NULL,
  source_manifest_sha256 TEXT NOT NULL CHECK(length(source_manifest_sha256)=64),
  object_key TEXT NOT NULL,
  content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
  size_bytes INTEGER NOT NULL CHECK(size_bytes BETWEEN 12 AND 10000000),
  rights_review_id TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'STAGED_PRIVATE' CHECK(state='STAGED_PRIVATE'),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (reference_key,source_manifest_sha256),
  CHECK(object_key='drop-rate/private-media/'||content_sha256||'.webp')
);
CREATE INDEX IF NOT EXISTS artwork_shadow_by_scope
 ON artwork_shadow_candidates (provider,system_code,language,set_id,card_number);
-- Deliberately NO ACTIVE/PUBLISHED state or mutable public pointer.
-- Image bytes are R2 only, D1 holds index/receipt only.
