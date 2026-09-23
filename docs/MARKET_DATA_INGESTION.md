# Market Data Ingestion

Drop Rate treats market data as evidence, not as the source of truth for live store pricing.

## Flow

Provider adapter → VERIFIED source mapping → normalized observation → immutable `market_observations` → deterministic pricing engine → pricing snapshot → Market Value / Recommended Retail → future Shopify publication policy.

## Provider rules

Supported adapter slots:

- eBay
- Collectr
- TCGplayer
- Cardmarket

Adapters stay disabled until legitimate provider access is available. Scraping is not assumed to be permitted.

## Integrity rules

- Only `VERIFIED` source mappings may be ingested automatically.
- An adapter must return the same provider source and catalogue ID requested by the runner.
- Provider observations must have timezone-aware timestamps.
- `(source, source_record_key)` is unique, making repeated runs idempotent at the observation layer.
- Market observations are append-only and cannot be updated/deleted by the API role.
- Provider failures are isolated per mapping; one failed card does not discard valid evidence for other mappings.
- Each run records fetched, inserted, duplicate and failed-mapping counts in immutable ingestion history.
- Store Price is not overwritten by ingestion or pricing calculation.

## Automation

The authenticated ingestion endpoint is intentionally separate from n8n. When orchestration is introduced, n8n should trigger the backend ingestion API using a purpose-built service authentication mechanism; n8n must not duplicate provider normalization or pricing rules.
