# Exact OP-16 catalogue-guide recovery

The live Bandai Official set `569116` is named `The Time of Battle [OP-16]`.
The official product page identifies the same English OP-16 release and the
official checklist is keyed by that exact series ID:

- https://en.onepiece-cardgame.com/products/op16.html
- https://en.onepiece-cardgame.com/cardlist/?series=569116

The previous PokéWallet adapter required a BOOSTER PACK/EXTRA BOOSTER prefix even
though the shared release parser recognised this full title and code. The narrow
exception now requires provider, set ID and literal title together. Parallel IDs,
another provider/set, a different title or a mismatched card number remain rejected.

Live pre-change audit: 155 OP-16 records, 119 literal base-printing IDs, 28 base
records without a positive detail or catalogue guide. This is an opportunity
ceiling, not a claim that the provider supplies 28 usable quotes.

The existing refresh function accepts the explicit operator scope
`reference_set_id="569116"`. It retains complete-catalogue collision checks first,
then visits only the OP-16 English source group and writes only exact eligible
base references. It consumes at most ten free requests, with complete pagination,
upstream quota headers and all source/rarity/name/variant/FX guards unchanged.
It returns per-card previews. Other providers' positive guides and physical
inventory values are unchanged; absent prices never clear existing evidence.

The operator must hold the existing catalogue advisory lock, verify the configured
platform administrator and database capacity, run with `dry_run=True`, inspect
the returned preview, then explicitly apply and verify database readback.
No schedule or hourly quota changes are included. The default unspecialised
hourly refresh will also benefit from the corrected identity gate.

## Bounded operator

Run the default preview first, using the existing configured administrator:

```sh
python backend/scripts/refresh_op16_prices.py --from-settings --max-seconds 90
```

After reviewing every OP16_PRICE_PREVIEW row and ensuring remaining shared quota
can support a second pass, apply explicitly:

```sh
python backend/scripts/refresh_op16_prices.py --from-settings --max-seconds 90 --apply
```

Both commands acquire advisory lock 847220092, verify platform-admin access and
the existing database-capacity guard, and cap the provider at ten free requests.
Each pass consumes its own requests; it does not increase the scheduler budget.
The refresh operation is cancelled after at most 90 seconds; bounded database
preflight, readback, receipt finalisation and pool cleanup run outside that
refresh timeout.

Apply creates a durable op16_catalogue_prices reference_sync_runs receipt before
requesting provider data. A unique operator_run_id is attached to each accepted
quote. Readback counts persisted rows with that exact UUID, source and official
set, including after a provider timeout. The written count is committed readback,
never writes_attempted. The receipt stores the count and committed public-card
identities; OP16_PRICE_COMMITTED logs list each persisted guide. A count mismatch,
interruption or unreadable outcome remains INCOMPLETE rather than claiming
success. No provider keys or customer/inventory data are printed.

The Fusion source-identity probe is a separate readonly operation so its three
requests remain within the existing Dragon Ball allocation.
