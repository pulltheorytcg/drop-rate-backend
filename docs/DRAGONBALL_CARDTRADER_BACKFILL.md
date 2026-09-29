# Dragon Ball CardTrader backfill runner

This management script runs the existing import-enrichment core from the one-shot Railway worker.

## Why it exists

The production Dragon Ball backlog is one committed import batch containing 29 Dragon Ball Super Masters cards and 6 Dragon Ball Super Fusion World cards. The cards already have sale price, Near Mint condition and storage location. Their remaining work is identity/language confirmation and exact storefront media resolution.

The HTTP enrichment endpoint is founder-authenticated. The one-shot runner gives operations a safe way to execute the same backend rules from Railway without exposing a founder JWT, changing the live API process or duplicating business logic.

## Modes

`probe` is the default and performs no inventory/media writes. It:

- validates the batch and founder/owner actor relationship;
- selects one representative unlinked FOR_SALE card from each Dragon Ball game line;
- applies the supplied language in memory only;
- calls the deployed CardTrader resolver;
- prints sanitized provider results.

`apply` must be selected explicitly. It:

- seeds `import_enrichment_items` through the existing helper;
- processes only unlinked FOR_SALE Dragon Ball inventory from the chosen batch;
- calls the existing `_process_one` enrichment routine;
- preserves identity verification, pricing, media, Action Required and audit behavior;
- reports per-item statuses and failures.

Provider media remains PENDING and therefore cannot publish a Shopify product until exact-print media review is approved.

## Production run

Required environment/config values:

- `TCG_DRAGONBALL_BACKFILL_BATCH_ID`
- `TCG_DRAGONBALL_BACKFILL_ACTOR_USER_ID`
- `TCG_DRAGONBALL_BACKFILL_DEFAULT_LANGUAGE` (English for the current batch, explicitly confirmed by the founder)
- `TCG_CARDTRADER_API_TOKEN`

Optional:

- `TCG_DRAGONBALL_BACKFILL_LIMIT` (default 35)
- `TCG_DRAGONBALL_BACKFILL_MODE` (default `probe`)

The CardTrader token should be supplied to the one-shot worker as a Railway variable reference to the live API service. It must never be printed in logs.

## Failure behavior

The runner fails closed for:

- missing/invalid CardTrader credentials;
- actor not authorized for the import owner;
- non-COMMITTED batch;
- ambiguous/missing CardTrader identity or image evidence;
- provider/API errors;
- per-item enrichment exceptions.

No direct `inventory_items` update logic exists in the script; business mutations remain inside the existing backend enrichment functions.
