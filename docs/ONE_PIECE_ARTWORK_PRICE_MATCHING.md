# One Piece: artwork-verified printing prices

## Problem

Cardmarket's permitted, public bulk One Piece singles export provides an
`idProduct`, release, printed card number and name but **no product artwork or
V.1/V.2 label**. The same name, number and release can represent dramatically
different prices for a standard and an alternate-art printing. Never resolve
these collisions by product ID order, cheapest price or V.2 == `_p1` alone.

## What this change adds

The existing (authenticated) free PokéWallet One Piece source already delivers
card-level Cardmarket guide information and independently labelled variants.
Its documented, free `GET /images/{op_card_id}` serves the corresponding
artwork. No new provider, account, paid endpoint or scraping method is added.

Opt-in feature flag:

`TCG_POKEWALLET_ONE_PIECE_ARTWORK_MATCH_ENABLED=false`

To stop spending the constrained free quota on already-priced references while
the overall coverage target is unmet, the operator can independently enable:

`TCG_POKEWALLET_PRICING_COVERAGE_FIRST_ENABLED=true`

In coverage-first mode, references with an existing positive guide are still
loaded for identity collision checks but are not selected for price refresh or
write. The same rule also excludes any positive detail price, even when its
freshness has expired: coverage already counts that card as priced. Only
genuinely unpriced references are eligible for new catalogue guides. This
queue rule now applies to the existing **One Piece, Dragon Ball and Japanese
Pokémon** PokéWallet importers, without adding a data provider or raising its
hourly allowance.
Turn this flag OFF after the coverage push so normal daily guide refreshes
resume; stale prices must not be mistaken for recent sold comparables.

When artwork matching and coverage-first mode are both enabled, complete
publisher-artwork release sets run before ordinary starter decks. The release
cursor rotates within that priority tier, and each attempted artwork group
records its own cursor to avoid retrying an ambiguous first pair forever.
This fixes the observed 29 Oct 16:42 UTC pass which spent ten allowed requests
on eight starter-deck sets and made no new price matches. The release order
does **not** loosen card identity or pricing acceptance rules.

With the flag on, the existing bounded hourly importer:

1. Selects publisher-confirmed **English** Bandai references with an original
   `OPxx-nnn` image and one or more distinct `OPxx-nnn_pN` image URLs.
2. Requires the **complete** source set, the exact printed number, official
   release name, Cardmarket URL and version label, compatible rarities, and
   one Normal item plus independently labelled alternate items.
3. Reads each source card's actual image through the documented authenticated
   free API, compares it to the corresponding official Bandai images, and
   requires a **reciprocal unique match** (similarity >= 0.93, next-best
   separation >= 0.09). Neither prices nor numeric ID ordering can affect it.
4. Requires the source's Normal/alternate labels to agree with the publisher's
   unsuffixed/`_pN` printing identity.
5. Writes only eligible per-printing **reference catalogue guides**, preserving
   other providers' prices and checking that the official image and identity
   did not change before the write. It **never** writes physical inventory,
   ownership, retail price or Shopify data. Observations remain flagged
   `physical_valuation_eligible=false` and `sold_comparable=false`.

The image bytes are used in memory only. No copyrighted art is copied into R2.
The supplier's API key stays on the server.

## Safeguards and trade-offs

- OFF by default until the first operator-reviewed dry-run. The normal
  hourly updater stays unchanged with the flag off.
- At most two complete artwork groups are tested per hourly run; image calls
  spend the existing free API budget alongside set/list calls.
- Missing images, visually similar candidates, wrong-language/version evidence,
  source rate limits and expired FX evidence never trigger a guessed price.
- If a provider cannot label a parallel version or its images are missing, the
  parallel stays unpriced and requires a different permitted evidence source.
- PokéWallet's terms permit commercial API use subject to quotas. Its official
  SDK requests a visible **Data by PokéWallet** link to
  <https://pokewallet.io> when sourced data is displayed publicly. Check this
  attribution in the consumer UI before broad public use.

## Rollout and verification

1. Deploy code with the flag OFF, verify existing jobs and 64.80%-baseline
   catalogue counts are unaffected.
2. In a scoped dry-run, enable the artwork matcher but keep database writes
   disabled. Inspect the `POKEWALLET_PRICES` receipt fields
   `artwork_groups_tested`, `artwork_groups_verified`,
   `artwork_groups_ambiguous`, and `artwork_printings_quoted`.
3. Visually review the matching pairs and their source release and version.
   The strict image threshold may need adjustment only after this review.
4. Enable live writes in bounded runs. Verify returned references and stored
   quote evidence, re-read aggregate coverage and inventory ownership/Shopify
   hashes. A zero-quote run is a valid result if artwork is insufficient.
5. Turn the flag OFF immediately on unexpected prices or provider errors.

Focused tests: `tests/test_one_piece_artwork_match.py`,
`tests/test_pokewallet_one_piece_market.py`,
`tests/test_catalogue_maintenance.py`.
