# PokéWallet free-market guide bridge (24 October 2026)

## Scope and provenance

- **One Piece only in this first adapter:** English and Japanese base printings in complete publisher releases. The same API key supports Pokémon and Dragon Ball, but their free set-list endpoints do not reliably include priced card details, so they need separate quota-aware adapters and are **not** claimed as integrated by this release.
- `https://api.pokewallet.io/op/sets?language=jp|en`, followed only by `/op/sets/{unique_numeric_group_id}?page=…&limit=200`. The paid `/op/prices` endpoint is blocked in code.
- The source is PokéWallet's API with Cardmarket EUR `trend` as the underlying market guide. No TCGPlayer USD context, low asks, provider-set averages, artificial minimums, or sales estimates are promoted to a GBP card price.
- Official ECB spot-rate conversion and timestamp are recorded per quote. Values are **mixed-language indicative catalogue guides**, not exact UK sold comparables and **not** physical-copy valuation or selling-price authority.
- Exact release code, language, card number, rarity and unique *complete-set* product are required. English names must also agree. Japanese publisher names may not transliterate into the English source label; their prices remain explicitly non-physical. Parallel identifiers (`_p1`, etc.) and duplicate artwork products cannot inherit a base price.
- If PokéWallet returns a set with inconsistent pagination, duplicate printing IDs or incorrect totals, quarantine **that entire set** with bounded diagnostic counts. The daily cursor moves on to other sets, and no product from the problematic release receives a guide.
- No customer, owner, physical inventory, cost, Store Price or Shopify writes. The existing `tcg.reference_catalogue_prices` history trigger appends immutable history.

## Free limits

PokéWallet's documented free tier is 100 requests/hour and 1,000/day **shared across all games**. One guarded daily job allows at most 60 calls (12 in verification mode); a rate-limit header under five requests remaining stops the importer. The next pass waits for the next 03:00 UK daily slot. Client timeouts and failures keep prior prices unchanged. No plan upgrade, trial, or charge is required.

Official docs: https://pokewallet.io/api-docs/one-piece and terms: https://pokewallet.io/terms-conditions. Commercial API access is allowed under PokéWallet's terms; this integration respects its published free usage limits. The underlying aggregated market data is attributed explicitly.

## Controlled rollout

1. Apply database migration `20261024214300_pokewallet_price_guides.sql` before the application release. It only expands `tcg.catalogue_job_runs_job_check` to admit the new `POKEWALLET_PRICES` job.
2. Keep the existing production secret `TCG_POKEWALLET_API_KEY` only in Railway's `drop-rate-api-live` service; **never** expose or commit its value.
3. Release with `TCG_POKEWALLET_PRICING_APPLY_ENABLED` unset/false. The daily worker makes a **dry-run** request budget of 12, logs only bounded aggregate counts and records a `POKEWALLET_PRICES` receipt.
4. Verify source schemas, exact-print candidates, no unexpected failures, healthy database capacity, and the observed free request count. For live guide writes set `TCG_POKEWALLET_PRICING_APPLY_ENABLED=true` on the same service; the importer revision forces one new pass without waiting until tomorrow. That change will redeploy the service.
5. Run the official coverage query and verify that positive guides have identity/provenance and **no** inventory/Store Price/Shopify changes. Export new immutable `tcg.reference_market_history` entries to the correct Drop Rate Google Drive and verify the file before considering history archived.

## Expected limitations

Existing mapped base cards may already have adequate guides. Most missing One Piece references are **alternate printings** or promo products; this bridge deliberately leaves them blank rather than assigning the base price. A free One Piece feed alone cannot deliver the global 90% physical-reference coverage goal: Dragon Ball, Pokémon, Naruto and exact-printing gaps require independent permitted evidence.
