-- Drop Rate D1 Market Value shadow, 6 November 2026.
-- Source prices and full histories stay private, immutable, hashed in R2.
-- This schema does NOT create a production-current pointer or publish prices.
-- No RRP, guide, asking, or unverified AI estimate can become an eligible value.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS market_shadow_generations (
 generation_id TEXT PRIMARY KEY,
 r2_source_manifest_sha256 TEXT NOT NULL CHECK(length(r2_source_manifest_sha256)=64),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 state TEXT NOT NULL DEFAULT 'STAGING'
  CHECK(state IN ('STAGING','SOURCE_PARITY_VERIFIED','REJECTED')),
 UNIQUE(r2_source_manifest_sha256)
);

-- Exact complete card/product/condition profile, not a fuzzy title/number.
CREATE TABLE IF NOT EXISTS market_shadow_profiles (
 generation_id TEXT NOT NULL REFERENCES market_shadow_generations(generation_id),
 profile_key TEXT NOT NULL,
 provider TEXT NOT NULL,
 system_code TEXT NOT NULL,
 language TEXT NOT NULL,
 provider_id TEXT NOT NULL,
 product_kind TEXT NOT NULL CHECK(product_kind IN
  ('RAW_CARD','GRADED_CARD','SEALED','COMIC','MANGA','FIGURE','SPORTS_CARD','LEGO')),
 finish TEXT NOT NULL,
 condition TEXT,
 grading_company TEXT,
 grade TEXT,
 currency TEXT NOT NULL DEFAULT 'GBP' CHECK(currency='GBP'),
 source_identity_sha256 TEXT NOT NULL CHECK(length(source_identity_sha256)=64),
 PRIMARY KEY(generation_id,profile_key),
 UNIQUE(generation_id,provider,system_code,language,provider_id,product_kind,
        finish,condition,grading_company,grade),
 CHECK((product_kind='GRADED_CARD'
    AND grading_company IS NOT NULL AND grade IS NOT NULL)
    OR (product_kind<>'GRADED_CARD' AND grading_company IS NULL AND grade IS NULL))
);

-- SQLite UNIQUE treats NULL as distinct; this expression index also blocks
-- duplicate ungraded/raw profiles with optional condition, company and grade.
CREATE UNIQUE INDEX IF NOT EXISTS market_shadow_exact_profile_unique
 ON market_shadow_profiles(generation_id,provider,system_code,language,provider_id,
   product_kind,finish,ifnull(condition,''),ifnull(grading_company,''),ifnull(grade,''));

-- R2 objects hold full source/provider evidence. D1 indexes its provenance only.
-- Provider terms must be reviewed; external display permission separate from
-- permission to use a price privately in the deterministic pricing engine.
CREATE TABLE IF NOT EXISTS market_shadow_source_proofs (
 generation_id TEXT NOT NULL,
 proof_id TEXT NOT NULL,
 profile_key TEXT NOT NULL,
 r2_evidence_sha256 TEXT NOT NULL CHECK(length(r2_evidence_sha256)=64),
 evidence_type TEXT NOT NULL CHECK(evidence_type IN
  ('VERIFIED_SOLD','ACTIVE_ASKING','STATISTICAL_GUIDE','MODEL_ESTIMATE')),
 source_name TEXT NOT NULL,
 source_run_key TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 source_country TEXT,
 distinct_comparables INTEGER NOT NULL CHECK(distinct_comparables>=0),
 distinct_sellers INTEGER NOT NULL CHECK(distinct_sellers>=0),
 usage_rights TEXT NOT NULL CHECK(usage_rights IN
  ('INTERNAL_APPROVED','DISPLAY_APPROVED','PENDING','BLOCKED')),
 currency TEXT NOT NULL DEFAULT 'GBP' CHECK(currency='GBP'),
 PRIMARY KEY(generation_id,proof_id),
 UNIQUE(generation_id,proof_id,profile_key),
 UNIQUE(generation_id,source_name,source_run_key,profile_key),
 FOREIGN KEY(generation_id,profile_key)
  REFERENCES market_shadow_profiles(generation_id,profile_key),
 CHECK(distinct_sellers<=distinct_comparables)
);

CREATE TABLE IF NOT EXISTS market_shadow_current_values (
 generation_id TEXT NOT NULL,
 profile_key TEXT NOT NULL,
 price_status TEXT NOT NULL CHECK(price_status IN
  ('ELIGIBLE_MARKET_VALUE','GUIDE_ONLY','ASKING_ONLY','STALE','REVIEW_REQUIRED','MISSING')),
 market_value_gbp_minor INTEGER,
 source_proof_id TEXT,
 calculated_at TEXT,
 deterministic_rule_version TEXT,
 original_record_sha256 TEXT NOT NULL CHECK(length(original_record_sha256)=64),
 PRIMARY KEY(generation_id,profile_key),
 FOREIGN KEY(generation_id,profile_key)
  REFERENCES market_shadow_profiles(generation_id,profile_key),
 FOREIGN KEY(generation_id,source_proof_id,profile_key)
  REFERENCES market_shadow_source_proofs(generation_id,proof_id,profile_key),
 CHECK ((price_status='ELIGIBLE_MARKET_VALUE'
        AND market_value_gbp_minor>0
        AND source_proof_id IS NOT NULL
        AND calculated_at IS NOT NULL
        AND length(deterministic_rule_version)>0)
   OR (price_status<>'ELIGIBLE_MARKET_VALUE'
       AND market_value_gbp_minor IS NULL))
);

-- Database-level defence in depth, beyond FastAPI deterministic validation.
CREATE TRIGGER IF NOT EXISTS market_shadow_market_value_source_gate
 BEFORE INSERT ON market_shadow_current_values
 WHEN NEW.price_status='ELIGIBLE_MARKET_VALUE'
 BEGIN
  SELECT CASE WHEN NOT EXISTS(
   SELECT 1 FROM market_shadow_source_proofs s
   JOIN market_shadow_profiles p
     ON p.generation_id=s.generation_id AND p.profile_key=s.profile_key
   WHERE s.generation_id=NEW.generation_id
     AND s.proof_id=NEW.source_proof_id
     AND s.profile_key=NEW.profile_key
     AND s.evidence_type='VERIFIED_SOLD'
     AND s.source_country='GB'
     AND julianday(s.observed_at) IS NOT NULL
     AND julianday(NEW.calculated_at) IS NOT NULL
     AND julianday(NEW.calculated_at) >= julianday(s.observed_at)
     AND julianday(NEW.calculated_at) - julianday(s.observed_at) <= 90
     AND s.usage_rights IN ('INTERNAL_APPROVED','DISPLAY_APPROVED')
     AND s.distinct_comparables >= 1
     AND s.distinct_sellers >= 1
     AND (p.product_kind <> 'GRADED_CARD'
          OR (s.distinct_comparables >= 5 AND s.distinct_sellers >= 5))
  ) THEN RAISE(ABORT, 'Market Value source proof is not sold-grade eligible') END;
 END;

-- Ingest an immutable new snapshot generation rather than overwriting any
-- historical observation, proof or previously staged Market Value.
CREATE TRIGGER IF NOT EXISTS market_shadow_price_no_update
 BEFORE UPDATE ON market_shadow_current_values
 BEGIN SELECT RAISE(ABORT,'market value snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_shadow_price_no_delete
 BEFORE DELETE ON market_shadow_current_values
 BEGIN SELECT RAISE(ABORT,'market value snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_shadow_proof_no_update
 BEFORE UPDATE ON market_shadow_source_proofs
 BEGIN SELECT RAISE(ABORT,'market evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_shadow_proof_no_delete
 BEFORE DELETE ON market_shadow_source_proofs
 BEGIN SELECT RAISE(ABORT,'market evidence is immutable'); END;

-- Never let a completed raw reference silently become a slab/other printing.
CREATE TRIGGER IF NOT EXISTS market_shadow_profile_no_update
 BEFORE UPDATE ON market_shadow_profiles
 BEGIN SELECT RAISE(ABORT,'market profile identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_shadow_profile_no_delete
 BEFORE DELETE ON market_shadow_profiles
 BEGIN SELECT RAISE(ABORT,'market profile identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_shadow_generation_source_immutable
 BEFORE UPDATE OF r2_source_manifest_sha256 ON market_shadow_generations
 BEGIN SELECT RAISE(ABORT,'market source generation is immutable'); END;

-- Private-only diagnostic view. NO production active generation pointer.
-- Only already-classified eligible prices are visible to these internal tests.
CREATE VIEW IF NOT EXISTS market_shadow_eligible_values AS
 SELECT v.generation_id,v.profile_key,v.market_value_gbp_minor,
        p.product_kind,p.provider,p.system_code,p.language,p.provider_id,
        p.finish,p.condition,p.grading_company,p.grade,
        s.source_name,s.observed_at,s.r2_evidence_sha256,s.usage_rights
 FROM market_shadow_current_values v
 JOIN market_shadow_profiles p
   ON p.generation_id=v.generation_id AND p.profile_key=v.profile_key
 JOIN market_shadow_source_proofs s
   ON s.generation_id=v.generation_id AND s.proof_id=v.source_proof_id
 WHERE v.price_status='ELIGIBLE_MARKET_VALUE'
   AND s.evidence_type='VERIFIED_SOLD'
   AND s.usage_rights='DISPLAY_APPROVED'
   AND s.source_country='GB';
