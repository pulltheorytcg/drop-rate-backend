# Reviewed Fusion World SB01/ST01 base guides

Official publisher releases:

- SB01: https://www.dbs-cardgame.com/fw/en/products/01_190.html
- ST01: https://www.dbs-cardgame.com/fw/en/products/01_401.html

A three-request readonly free-provider probe on 26 October 2026 established these
exact source release identities:

| Official checklist | Literal publisher title | Source set | Source title |
|---|---|---|---|
| 583201 | MANGA BOOSTER 01 [SB01] | 24335 | Manga Booster 01 |
| 583301 | STORY BOOSTER 01 [ST01] | 24680 | Story Booster 01 |

Both source releases explicitly distinguish base Cardmarket V1 paths from V2
alternate-art, Gold, and Dragon Ball Pattern products. The matcher requires the
literal publisher tuple, own-release number, unsuffixed official printing ID,
source set ID/title, exact release URL path, matching source rarity label and
matching base card name. Only an exact literal " - CARDNUMBER" name suffix may
be removed. Every competing row must independently prove its alternate status;
one unknown competitor, duplicate base, wrong source set or unlabelled variant
rejects the entire number. Missing price data never selects a different product.

The live audit found 19 unpriced SB01 base cards and 71 ST01 base cards. These
90 cards are an opportunity ceiling. A complete provider run may yield fewer
because of missing quotes, changed source identities, names or variants.

SB02 is deliberately not mapped: the probe's Cardmarket rows are misfiled under
Fusion World Energy Markers (23430) with null product type, number and rarity.
Release-event, promo, energy-marker and reprinted FB/FS numbers are not accepted.

## Scoped execution

The existing refresh accepts reference_set_id="583201" or "583301", an optional
UUID operator_run_id, and returns per-card preview rows. Scope is applied after
complete-catalogue collision checks. Every scoped invocation is capped at eight
free requests (including pagination) and honors the existing upstream remaining
quota check. Run a dry preview first:

```python
await refresh_pokewallet_dragon_ball(
    pool, actor, EcbHistoricalFxProvider(timeout_seconds=8),
    settings.pokewallet_api_key, dry_run=True, request_limit=8,
    reference_set_id="583301",
)
```

The caller must hold global catalogue lock 847220092, verify platform-admin and
database-capacity checks, and keep all previews/applies within the existing
shared budget. Explicit apply uses dry_run=False plus a unique operator_run_id;
record a durable reference_sync_runs receipt and count committed rows by that
exact quote UUID/source/set after the call. writes_attempted is not a committed
count. Existing other-provider positive guides, inventory values and Store Price
are preserved. No scheduling or quota increases are included.

The public identity fixtures retain only probe identity fields; their 1.23 EUR
values are synthetic unit-test prices, not claimed live market values.


A reproducible operator implements those guards, dry-run by default:

```sh
python backend/scripts/refresh_fusion_special_prices.py --from-settings --reference-set-id 583301 --max-seconds 90
python backend/scripts/refresh_fusion_special_prices.py --from-settings --reference-set-id 583201 --max-seconds 90
```

Inspect each FUSION_SPECIAL_PRICE_PREVIEW row before explicitly adding --apply.
Every invocation has its own maximum of eight requests; previews and applies
must share the existing allocation. Apply creates a durable
fusion_special_catalogue_prices receipt and attributes quotes to its UUID, then
reports only committed database readback as written. Incomplete/truncated
provider pages, deferred queries, interrupted work and readback mismatches retain
an INCOMPLETE receipt. Each committed public-card identity is printed separately.
The provider refresh timeout is at most 90 seconds; bounded preflight, readback,
receipt finalisation and pool cleanup run outside that timeout.

The reviewed special releases use Cardmarket quotes only: the merged TCGplayer
product is not independently proved by a Cardmarket V1 URL and cannot serve as
fallback. A request-budget stop reports unattempted_queries and leaves the
operator/receipt INCOMPLETE, even when its successfully matched subset committed.
