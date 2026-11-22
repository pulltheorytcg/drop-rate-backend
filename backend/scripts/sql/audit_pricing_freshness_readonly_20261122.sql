-- Read-only production pricing freshness audit. Run against Supabase Pro with a read-only role.
-- Freshness means expires_at > database now(), NOT that an asking quote is a sale.
-- Counts are table-local and must never be summed into distinct catalogue coverage.
-- No price, inventory, ownership, Shopify or settlement writes.
BEGIN READ ONLY;
SELECT now() AS audited_at_utc;
SELECT 'regional_context' AS source, count(*) AS stored,
       count(*) FILTER (WHERE expires_at > now()) AS fresh,
       max(expires_at) AS latest_expiry
  FROM tcg.reference_regional_price_context
UNION ALL
SELECT 'sealed_market', count(*), count(*) FILTER (WHERE expires_at > now()), max(expires_at)
  FROM tcg.reference_sealed_market_prices
UNION ALL
SELECT 'catalogue', count(*), count(*) FILTER (WHERE expires_at > now()), max(expires_at)
  FROM tcg.reference_catalogue_prices
UNION ALL
SELECT 'reference_market', count(*), count(*) FILTER (WHERE expires_at > now()), max(expires_at)
  FROM tcg.reference_market_prices
UNION ALL
SELECT 'active_asking', count(*), count(*) FILTER (WHERE expires_at > now()), max(expires_at)
  FROM tcg.reference_asking_prices;
ROLLBACK;
