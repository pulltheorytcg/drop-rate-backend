-- REVIEW ONLY: this is NOT an applied migration.
-- Activate only after the latest successful Supabase backup is independently
-- verified and the release owner approves the production migration.
-- This view deliberately describes evidence, NOT strict coverage certification.
-- R2 physical HEAD/list parity is outside PostgreSQL and remains NOT_VERIFIED.
-- No ownership, Auth, finance, RLS, Shopify, D1 or Railway writes.
CREATE OR REPLACE VIEW tcg_private.catalogue_coverage_audit_v1
WITH (security_invoker = true)
AS
WITH published AS (
  SELECT DISTINCT inventory_id
  FROM tcg.shopify_inventory_links WHERE sync_state = 'PUBLISHED'
), live_items AS (
  SELECT
    'TIER_1_LIVE_INVENTORY'::text tier,
    p.game::text game,
    COALESCE(p.set_name,'')::text set_label,
    1::bigint total,
    CASE
      WHEN i.market_value_minor > 0
        AND i.pricing_updated_at >= now() - interval '14 days'
      THEN 'FRESH_STORED_NOT_VARIANT_CERTIFIED'
      WHEN i.market_value_minor > 0 AND i.pricing_updated_at IS NOT NULL
      THEN 'STALE_STORED'
      ELSE 'MISSING_STORED'
    END::text price_evidence_state,
    EXISTS (
      SELECT 1
      FROM tcg.media_assets a
      JOIN tcg.media_object_mirrors m ON m.media_asset_id = a.id
      WHERE a.approval_status = 'APPROVED'
        AND a.rights_status = 'VERIFIED'
        AND m.object_key IS NOT NULL AND m.size_bytes > 0
        AND (
          (i.grading_company IS NOT NULL AND a.inventory_id = i.id)
          OR
          (i.grading_company IS NULL AND
             (a.inventory_id = i.id OR a.catalogue_id = i.catalogue_id))
        )
    ) AS image_mirror_metadata_exists
  FROM tcg.inventory_items i
  JOIN tcg.catalogue_products p ON p.id = i.catalogue_id
  LEFT JOIN published s ON s.inventory_id = i.id
  WHERE i.status IN ('APPROVED','DRAFT','INSPECTION','LISTED')
    OR s.inventory_id IS NOT NULL
), reference_items AS (
  SELECT
    'TIER_2_LAUNCH_REFERENCE'::text tier,
    CASE
      WHEN c.system_code = 'POKEMON_TCG' THEN 'Pokemon'
      WHEN c.system_code = 'ONE_PIECE_CARD_GAME' THEN 'One Piece'
      WHEN c.system_code LIKE 'DRAGON_BALL%' THEN 'Dragon Ball'
      WHEN c.system_code LIKE 'NARUTO%' THEN 'Naruto'
      ELSE c.system_code
    END::text game,
    concat_ws(' / ',c.language,c.system_code,COALESCE(c.set_id,''))::text set_label,
    1::bigint total,
    CASE
      WHEN COALESCE(q.fresh,false) THEN 'FRESH_QUALIFYING_QUOTE_NOT_VARIANT_CERTIFIED'
      WHEN COALESCE(q.eligible_any,false) THEN 'STALE_QUALIFYING_QUOTE'
      ELSE 'MISSING_QUALIFYING_QUOTE'
    END::text price_evidence_state,
    (c.image_url LIKE 'http%'
      AND m.status='VERIFIED'
      AND m.object_key IS NOT NULL AND m.size_bytes>0) AS image_mirror_metadata_exists
  FROM tcg.reference_cards c
  LEFT JOIN tcg.reference_market_prices p
    ON (c.provider,c.system_code,c.language,c.provider_id)
     = (p.provider,p.system_code,p.language,p.provider_id)
  LEFT JOIN tcg.reference_image_mirrors m
    ON (c.provider,c.system_code,c.language,c.provider_id)
     = (m.provider,m.system_code,m.language,m.provider_id)
  LEFT JOIN LATERAL (
    SELECT
      bool_or(
        q.value->>'physical_valuation_eligible'='true'
        AND q.value->>'reference_language'=c.language
        AND CASE WHEN (q.value->>'price_gbp_minor') ~ '^[0-9]+$'
          THEN (q.value->>'price_gbp_minor')::numeric>0 ELSE false END
      ) AS eligible_any,
      bool_or(
        q.value->>'physical_valuation_eligible'='true'
        AND q.value->>'reference_language'=c.language
        AND CASE WHEN (q.value->>'price_gbp_minor') ~ '^[0-9]+$'
          THEN (q.value->>'price_gbp_minor')::numeric>0 ELSE false END
        AND CASE
          WHEN pg_input_is_valid(q.value->>'observed_at','timestamptz')
            THEN (q.value->>'observed_at')::timestamptz >= now()-interval '14 days'
          ELSE false
        END
      ) AS fresh
    FROM jsonb_array_elements(COALESCE(p.quotes,'[]'::jsonb)) AS q(value)
  ) q ON true
), external_publications AS (
  SELECT
    'TIER_3_R2_PUBLICATION'::text tier,
    CASE system_code
      WHEN 'MAGIC_THE_GATHERING' THEN 'Magic'
      WHEN 'DISNEY_LORCANA' THEN 'Lorcana'
      WHEN 'YUGIOH' THEN 'Yu-Gi-Oh'
      ELSE system_code
    END::text game,
    ''::text set_label,
    record_count::bigint total,
    'NOT_MEASURED'::text price_evidence_state,
    NULL::boolean image_mirror_metadata_exists
  FROM tcg_private.r2_first_catalogue_publications
  WHERE active AND system_code IN
    ('MAGIC_THE_GATHERING','DISNEY_LORCANA','YUGIOH')
), all_evidence AS (
  SELECT * FROM live_items
  UNION ALL SELECT * FROM reference_items
  UNION ALL SELECT * FROM external_publications
)
SELECT
  tier,game,set_label,sum(total)::bigint item_count,
  CASE WHEN tier='TIER_3_R2_PUBLICATION' THEN NULL::bigint
    ELSE coalesce(sum(total) FILTER(WHERE price_evidence_state LIKE 'FRESH%'),0)::bigint END
    AS fresh_price_evidence_count,
  CASE WHEN tier='TIER_3_R2_PUBLICATION' THEN NULL::bigint
    ELSE coalesce(sum(total) FILTER(WHERE price_evidence_state LIKE 'STALE%'),0)::bigint END
    AS stale_price_evidence_count,
  CASE WHEN tier='TIER_3_R2_PUBLICATION' THEN NULL::bigint
    ELSE coalesce(sum(total) FILTER(WHERE price_evidence_state LIKE 'MISSING%'),0)::bigint END
    AS missing_price_evidence_count,
  CASE WHEN tier='TIER_3_R2_PUBLICATION' THEN NULL::bigint
    ELSE coalesce(sum(total) FILTER(WHERE image_mirror_metadata_exists),0)::bigint END
    AS mirrored_image_metadata_count,
  CASE WHEN tier='TIER_3_R2_PUBLICATION' THEN NULL::bigint
    ELSE coalesce(sum(total) FILTER(WHERE NOT coalesce(image_mirror_metadata_exists,false)),0)::bigint END
    AS missing_image_metadata_count,
  'NOT_VERIFIED'::text r2_physical_head_status
FROM all_evidence
GROUP BY tier,game,set_label;

-- Keep it private; no browser/anon access or SECURITY DEFINER bypass.
REVOKE ALL ON tcg_private.catalogue_coverage_audit_v1
FROM PUBLIC, anon, authenticated;
