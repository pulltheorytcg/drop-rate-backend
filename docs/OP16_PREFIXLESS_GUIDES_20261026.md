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
