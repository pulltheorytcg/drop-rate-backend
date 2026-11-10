-- READ-ONLY preview ONLY. Never turn this into an UPDATE without independent
-- rights, identity, recency, outlier and full physical-variant validation.
-- Captures one row per approved/published CARD/SEALED physical copy.
-- Zero writes, zero provider requests, no values applied.
WITH tier1 AS (
 SELECT i.id, i.inventory_code, i.catalogue_id, p.name, p.game, p.card_number, p.product_type,
        COALESCE(NULLIF(BTRIM(i.language),''), NULLIF(BTRIM(p.language),'')) AS item_language,
        NULLIF(BTRIM(i.condition),'') AS item_condition,
        NULLIF(BTRIM(i.grading_company),'') AS item_grader,
        NULLIF(BTRIM(i.grade),'') AS item_grade,
        NULLIF(BTRIM(i.seal_status),'') AS item_seal,
        i.market_value_minor, i.pricing_updated_at
 FROM tcg.inventory_items i
 JOIN tcg.catalogue_products p ON p.id=i.catalogue_id
 WHERE p.product_type IN ('CARD','SEALED')
   AND (i.status='APPROVED' OR EXISTS (
     SELECT 1 FROM tcg.shopify_inventory_links l
     WHERE l.inventory_id=i.id AND l.sync_state='PUBLISHED'))
), evidence AS (
 SELECT t.*,
 (SELECT COUNT(DISTINCT m.source_record_key)
  FROM tcg.market_observations m
  WHERE m.catalogue_id=t.catalogue_id
    AND m.source='EBAY' AND m.observation_type='SOLD'
    AND m.source_country='GB' AND m.price_gbp_minor>0
    AND m.observed_at>=now()-interval '14 days'
    AND m.metadata->>'access_method'='TRAWL_API'
    AND LOWER(COALESCE(m.language,''))=LOWER(COALESCE(t.item_language,''))
    AND (
      (t.product_type='CARD' AND t.item_grader IS NULL AND m.grading_company IS NULL
       AND t.item_condition IS NOT NULL AND LOWER(m.condition)=LOWER(t.item_condition))
      OR (t.product_type='CARD' AND t.item_grader IS NOT NULL
          AND LOWER(m.grading_company)=LOWER(t.item_grader) AND m.grade=t.item_grade)
      OR (t.product_type='SEALED' AND t.item_seal IS NOT NULL
          AND m.seal_status=t.item_seal AND m.grading_company IS NULL)
    )
 )::int AS recent_matching_sold
 FROM tier1 t
), preview AS (
 SELECT *,
 CASE
   WHEN (market_value_minor IS NULL OR market_value_minor<=0) AND recent_matching_sold>=3
      THEN 'INSERT_CANDIDATE_AWAITING_SOURCE_RIGHTS_AND_VALIDATION'
   WHEN market_value_minor>0 AND (pricing_updated_at IS NULL OR pricing_updated_at<now()-interval '14 days')
      AND recent_matching_sold>=3
      THEN 'UPDATE_CANDIDATE_AWAITING_SOURCE_RIGHTS_AND_VALIDATION'
   WHEN market_value_minor IS NULL OR market_value_minor<=0 THEN 'SKIP_MISSING_SOLD_EVIDENCE'
   WHEN pricing_updated_at IS NULL OR pricing_updated_at<now()-interval '14 days'
      THEN 'SKIP_STALE_NEEDS_SOLD_EVIDENCE'
   ELSE 'SKIP_RECENT_STORED_VALUE_UNVERIFIED_PROVENANCE'
 END AS proposed_action
 FROM evidence
)
-- Report counts without recording customer/owner information or inventory IDs.
SELECT COUNT(*) AS physical_items,
       COUNT(*) FILTER (WHERE recent_matching_sold>=1) AS any_recent_sold,
       COUNT(*) FILTER (WHERE recent_matching_sold>=3) AS three_recent_sold,
       COUNT(*) FILTER (WHERE proposed_action LIKE 'INSERT%') AS candidate_inserts,
       COUNT(*) FILTER (WHERE proposed_action LIKE 'UPDATE%') AS candidate_updates,
       COUNT(*) FILTER (WHERE proposed_action LIKE 'SKIP%') AS skipped
FROM preview;

-- To examine up to 20 private samples, use the identical CTE and substitute:
-- SELECT inventory_code,game,name,card_number,item_language,item_condition,
--        item_grader,item_grade,market_value_minor,recent_matching_sold,proposed_action
-- FROM preview
-- ORDER BY (market_value_minor IS NOT NULL) ASC, recent_matching_sold DESC, inventory_code
-- LIMIT 20;
