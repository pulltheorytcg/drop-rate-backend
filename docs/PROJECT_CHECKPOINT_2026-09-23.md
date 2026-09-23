# Drop Rate Project Checkpoint — 23 September 2026

This checkpoint exists so work can resume without relying on chat history.

## Production state before this branch

- Founder authentication live.
- Inventory foundation live: canonical catalogue, physical inventory, purchase lots, storage locations, manual intake, imports, readiness/approval.
- Internal commerce/finance foundation live: orders, sold inventory state, immutable ledger, refunds/returns foundation, founder balances and payout requests.
- Seller dashboard live with Dashboard / Inventory / Sales / Reports / Balance / Settings navigation.
- Market-data schema and deterministic pricing engine live.
- Pricing operations API live for policy, recalculation, history and inventory pricing overview.
- Shopify intentionally deferred until internal backend/accounting and pricing workflows are stable.

## This branch

Adds the provider-neutral market ingestion runner, immutable ingestion-run history, provider health/status API and dashboard visibility for market/pricing operations. No live provider adapter is enabled without legitimate provider access.

## Next after this branch

1. Obtain/confirm permitted access for provider adapters.
2. Build eBay adapter first if official sold/active data access is available; otherwise use approved data sources/exports only.
3. Add provider mappings/review tooling.
4. Add scheduled ingestion with service authentication.
5. Complete final Milestone 1 regression QA and import review resolution.
6. Prepare Shopify only after the internal system is clean and stable.
