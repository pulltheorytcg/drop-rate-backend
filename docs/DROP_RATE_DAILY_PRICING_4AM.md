# Drop Rate — 04:00 Europe/London internally calculated market values

## Purpose and scope
A deterministic catalogue-only pricing run in the existing Railway/FastAPI worker.
New UK-time slot: **04:00 every calendar day** (DST-safe; best effort at the
first eligible worker pass, not a guaranteed exact wall-clock second).

The first supported cohort is **ordinary standard Common / Uncommon** One Piece
and Dragon Ball Masters cards. Pokémon has no verified rarity field in the
reference index, while alternate arts, SP, SR, SEC and any numbered parallels
require source- and artwork-specific evidence; they are not assigned a
same-rarity blanket price. Naruto is excluded.

A Drop Rate rules-verified calculation is our own catalogue market-value
estimate, not an externally verified transaction. The original source
evidence and model version remain visible in the price record. It may be
low-confidence even after passing the deterministic peer-cohort rule.

## Data path
Existing permitted market-price guides -> exact game/set/printing/language
reference -> same-release standard rarity cohort -> five or more independent
reference prices -> conservative 25th percentile, after dispersion guard
(P75/P25 <=3) -> identity-guarded reference_catalogue_prices upsert ->
history trigger -> browser DROP_RATE_COMPUTED_MARKET_V1 source -> separate
DROP_RATE_CALCULATED_VALUE coverage bucket.

The model never uses its own previous outputs as peers. Existing positive
values from other providers remain untouched, even if stale. Market-value
amounts below £1 remain recorded accurately; the Shopify Store Price floor
is £1, in the existing store_price_floor function.

The daily pass uses fixed 1,000-reference batches and a durable cursor.
Both display and global coverage treat a model quote as current only during its
two-day TTL. Revisions and the dry-run -> apply transition replay the same
input cursor once, rather than skipping previewed candidates.

## Configuration
- TCG_DROP_RATE_DAILY_MODEL_ENABLED=false by default.
- TCG_DROP_RATE_DAILY_MODEL_APPLY_ENABLED=false by default.
- TCG_DROP_RATE_DAILY_MODEL_BATCH_LIMIT=1000, capped to [1, 1000].

The existing capacity guard, advisory lock, restricted platform-admin actor
and catalogue_job_runs receipt protect the pipeline. The new allowed receipt
name is DROP_RATE_DAILY_MODEL.

## Shopify integration: separate owner-authorised gate
There are currently no owner rows in tcg.pricing_policies, and no
verified provider/catalogue mappings to the 506 approved-for-sale physical
items. Consequently the catalogue calculation must not silently update
physical Store Prices. The existing Shopify price reconciler is the sole
path to push future approved Store Prices to Shopify; it reads the canonical
inventory value and verifies the remote variant and database versions.

Before enabling physical repricing for any owner:
1. Establish exact catalogue-to-provider printing links (including artwork
   and language) with duplicate/reprint safeguards.
2. Owner/consignor explicitly opts into auto_reprice_enabled with a signed
   review of max-change/high-value/low-confidence rules.
3. Run a price-change preview for their real stock; exclude overrides,
   slabs, multi-owner pooled offers, reserved/sold items, and disputes.
4. Apply transactional store-price updates with audit and idempotency.
5. Allow the existing Shopify reconciler to sync eligible non-pooled variants,
   then verify returned prices. Alert on mismatch; never silently retry
   until a price has crossed the review thresholds.

## Failure tests
Timezone/DST, stale or mixed-market observations, parallel/art collision,
zero peer samples, unbounded batch requests, concurrency, other-provider
positive prices, disconnected owner mapping, provider outages, R2 archive
capacity guard, database job-name allowlist, and Shopify sync mismatch.

## Acceptance
Measure both externally sourced and internally calculated coverage, printings
examined, model values accepted, new persisted values, Shopify items eligible
by owner, and successful Shopify price readbacks. No claim of additional
verified sales may be made from a model-derived price.
