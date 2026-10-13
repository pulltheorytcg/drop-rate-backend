-- Japanese Fusion World must never inherit an English or US quote simply
-- because its collector number is identical to a different market printing.
-- Existing Japanese rows were confirmed empty/zero before this additive guard.
-- No owner data, price history, RLS, Shopify or settlement changes.
ALTER TABLE tcg.reference_market_prices
  ADD CONSTRAINT reference_market_fusion_japanese_region_source_guard
  CHECK (
    NOT (
      system_code = 'DRAGON_BALL_SUPER_FUSION_WORLD'
      AND language = 'Japanese'
      AND quotes <> '[]'::jsonb
      AND COALESCE(quotes->0->>'source','') = 'CARDMARKET_BULK_SINGLES'
      AND (
        COALESCE(quotes->0->>'reference_language','') <> 'Japanese'
        OR COALESCE(quotes->0->>'valuation_role','') <> 'MIXED_NON_ENGLISH_REFERENCE'
        OR COALESCE(quotes->0->>'match_basis','') <> 'OFFICIAL_FUSION_JP_EN_BASE_PRINT_AND_UNIQUE_NONENGLISH_MARKET_PRODUCT'
        OR COALESCE(quotes->0->>'physical_language_confirmed','') <> 'false'
        OR COALESCE(quotes->0->>'physical_valuation_eligible','') <> 'false'
        OR COALESCE(quotes->0->>'condition_specific','') <> 'false'
        OR COALESCE(quotes->0->>'marketplace_region_label','') NOT IN
           ('Non-English','Japanese','Asia Region Legal',
            'Asia Region Legal/Non-English','Japanese/Non-English')
      )
    )
  ) NOT VALID;

ALTER TABLE tcg.reference_market_prices
  VALIDATE CONSTRAINT reference_market_fusion_japanese_region_source_guard;

COMMENT ON CONSTRAINT reference_market_fusion_japanese_region_source_guard
 ON tcg.reference_market_prices IS
 'Japanese Fusion World bulk guides require exact two-checklist base-print evidence, distinct Non-English region, explicit JP reference language, and non-publishable physical basis. Prevents cross-language price inheritance.';
