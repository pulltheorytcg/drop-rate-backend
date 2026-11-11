# Current eBay asking-price access — 2026-10-28

## Finding

Current listings are a usable source category alongside sold evidence and dated market guides. The earlier Decodo sold-search sign-in result did not establish that active-listing prices were unavailable.

A bounded official eBay Browse API test succeeded from the deployed Railway service. It used the existing application client and existing credentials, one application-token request and one Browse search, with no retries or database writes.

The search was `Energy Marker E-141 English`, marketplace `EBAY_GB`, UK item location, fixed-price listings, first page, limit 20. It returned one listing:

- Item: `920042953008`
- Title: BGS 9.5 E-141 Energy Marker Premium Card Collection Dragon Ball Fusion World
- Asking price: GBP 140.00
- Returned shipping cost: GBP 4.52
- Condition: Graded
- Buying options: FIXED_PRICE and BEST_OFFER
- Item country: GB

This proves access to a current-listing candidate for this search. It does not verify the exact variant or language, establish a sold price, or establish a representative market valuation. The BGS 9.5 listing must not value an ungraded reference. No reference price or store price changed.

## Separate Decodo active-search result

One additional Decodo request tested an active Buy It Now URL without sold/completed filters. It returned outer HTTP 200 and a 251-byte provider response without the expected results schema. The probe stopped with `PROVIDER_SCHEMA_CHANGED`. The raw body was not retained. This cannot establish the underlying provider error or whether active eBay search itself was blocked.

The reports are preserved separately:
- `evidence/decodo-active-probe-20261028.json`
- `evidence/ebay-active-probe-20261028.json`

Across this investigation there were three Decodo requests: original sold pilot, sold diagnostic, and active probe. The official API added one OAuth request and one Browse request. All probes performed zero database writes and priced zero new references.

## Existing pricing and coverage

Inspection of deployed commit `2b925b593aae6318b98710323d4c3855c0f7295c` shows:

- Existing reference coverage already includes current Cardmarket/TCGdex/PokeWallet guide paths and explicitly labelled mixed-language guides. It is not solely sold-data coverage.
- `ebay_official_client.py` already supports official active-listing search and a fixed-price filter.
- The existing official adapter emits ACTIVE observations.
- `pricing_engine.py` uses ACTIVE as supporting context and excludes it as a standalone UK/EU anchor.
- The catalogue coverage metric uses the reference-price caches. Collecting ACTIVE observations alone does not increase that metric.

The previously measured baseline remains 43,279 / 67,065 (64.53%) as of 19:39 UTC. This investigation did not refresh that snapshot or increase coverage.

## Bounded next implementation

Add a separately labelled current asking-price estimate for references without qualifying sold evidence or guides. Exact card, set/number, variant, language, raw/graded status, condition and bundle exclusions must be checked before comparison. Use multiple independent comparable listings, explicit shipping handling, robust statistics, freshness and confidence/sample-count display. Preserve historical observations and existing store-price safeguards.

Before bulk reuse, address the existing adapter's missing fixed-price-only argument, incomplete identity/condition checks, and free-shipping handling. Integrate the estimate into the reference cache and coverage reporting deliberately as its own evidence tier.

## Validation and limits

The Decodo active probe passed three offline fixtures. The official API wrapper passed syntax compilation and plan-only validation before the single live search. Its runtime result was downloaded and reviewed, including its graded condition and GBP fields. These were diagnostic scripts under /tmp, not deployed application changes. No scheduler or startup hook was introduced.
